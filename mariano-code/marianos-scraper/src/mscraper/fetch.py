"""Fetching layer: provider adapter + pacing, retries with backoff, block and latency detection.

Provider: Oxylabs Web Scraper API, Kroger endpoint. Every request carries the configured
`store_id`, so Mariano's serves that store's assortment and prices; the store is still
re-checked on every page by the runner (a provider that silently ignores the pin fails the run).
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("mscraper.fetch")


@dataclass
class FetchResult:
    url: str
    status: int
    html: str
    elapsed: float


class FetchError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # http | blocked | timeout | budget | error


class Fetcher:
    name = "base"

    def __init__(self, settings, location):
        self.s, self.loc = settings, location
        self.timeout = float(settings.get("fetch.timeout_seconds", 120))
        self.retries = int(settings.get("fetch.max_retries", 4))
        self.backoff = float(settings.get("fetch.backoff_base_seconds", 3))
        self.min_delay = float(settings.get("fetch.min_delay_seconds", 0.4))
        self.max_delay = float(settings.get("fetch.max_delay_seconds", 1.0))
        self.slow = float(settings.get("fetch.slow_response_seconds", 60))
        self.min_bytes = int(settings.get("fetch.min_page_bytes", 50000))
        self.budget = int(settings.get("fetch.max_requests_per_run", 0))
        self.total_budget = None   # budget.TotalBudget shared by all commands of one bounded test (persists on disk)
        self.concurrency = int(os.getenv("MSCRAPER_CONCURRENCY") or settings.get("fetch.concurrency", 4))
        self.sem = asyncio.Semaphore(self.concurrency)
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.stats = {"requests": 0, "ok": 0, "retries": 0, "blocked": 0, "http_errors": 0, "slow": 0,
                      "provider_faults": 0, "seconds": 0.0}

    async def start(self):
        return None

    async def close(self):
        return None

    async def _fetch_once(self, url: str, render_js: bool) -> FetchResult:  # pragma: no cover
        raise NotImplementedError

    async def _pace(self):
        async with self._lock:
            wait = self._last + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def get(self, url: str, render_js: bool = False, validate=None, retries: int | None = None) -> FetchResult:
        """Fetch with retries. `validate(html)` may raise to mark a response unusable (retried like a block)."""
        last: Exception | None = None
        max_retries = self.retries if retries is None else retries
        for attempt in range(max_retries + 1):
            if self.budget and self.stats["requests"] >= self.budget:
                raise FetchError(f"request budget of {self.budget} reached", "budget")
            async with self.sem:
                await self._pace()
                if self.total_budget is not None:   # counted before sending; raises once the test's total is used
                    self.total_budget.take(url, self.loc.store_id)
                self.stats["requests"] += 1
                try:
                    res = await asyncio.wait_for(self._fetch_once(url, render_js), self.timeout + 90)
                    self.stats["seconds"] += res.elapsed
                    if res.elapsed > self.slow:
                        self.stats["slow"] += 1
                        log.warning("slow response", extra={"url": url, "seconds": round(res.elapsed, 1)})
                    if res.status >= 400:
                        raise FetchError(f"HTTP {res.status}", "http")
                    if len(res.html) < self.min_bytes:
                        raise FetchError(f"response too small ({len(res.html)} bytes) – blocked or empty", "blocked")
                    if validate:
                        validate(res.html)
                    self.stats["ok"] += 1
                    return res
                except FetchError as exc:
                    last = exc
                    if exc.kind == "budget":
                        raise
                    self.stats["blocked" if exc.kind == "blocked" else "http_errors"] += 1
                except asyncio.TimeoutError:
                    last = FetchError("timeout", "timeout")
                except Exception as exc:  # parse errors raised by validate(), provider faults
                    last = exc
                    self.stats["blocked"] += 1 if getattr(exc, "kind", "") in ("challenge", "malformed") else 0
            if attempt < max_retries:
                self.stats["retries"] += 1
                delay = self.backoff * (2 ** attempt) + random.uniform(0, 1.5)
                log.info("retry", extra={"url": url, "attempt": attempt + 1, "error": str(last)[:200], "sleep": round(delay, 1)})
                await asyncio.sleep(delay)
        raise FetchError(f"failed after {max_retries + 1} attempts: {last}", getattr(last, "kind", "error"))


class OxylabsKrogerFetcher(Fetcher):
    name = "oxylabs_kroger"
    endpoint = "https://webapi.oxylabs.io/v1/scrape/kroger"

    async def start(self):
        import httpx

        key = os.getenv("OXYLABS_WEBAPI_KEY")
        if not key:
            raise FetchError("OXYLABS_WEBAPI_KEY is not set (env var / Key Vault secret)", "error")
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=self.timeout + 60)

    async def close(self):
        await self.client.aclose()

    async def _fetch_once(self, url: str, render_js: bool) -> FetchResult:
        body = {"url": url, "location": "US", "output": ["html"], "store_id": self.loc.store_id}
        if render_js:
            body["run_js"] = True
        t0 = time.monotonic()
        r = await self.client.post(self.endpoint, json=body)
        elapsed = time.monotonic() - t0
        if r.status_code >= 500:
            self.stats["provider_faults"] += 1
            raise FetchError(f"provider fault {r.status_code}: {r.text[:160]}", "http")
        if r.status_code >= 400:
            raise FetchError(f"provider HTTP {r.status_code}: {r.text[:200]}", "http")
        res = (r.json().get("results") or [{}])[0]
        meta = res.get("metadata") or {}
        status = int(((meta.get("statuses") or {}).get("http_request") or {}).get("code") or 200)
        return FetchResult(url, status, res.get("html") or "", elapsed)


class FixtureFetcher(Fetcher):
    """Serves saved pages (tests and offline replays). Map: url substring -> file under fixtures dir."""

    name = "fixture"

    def __init__(self, settings, location, fixtures: dict[str, str] | None = None, root: str | None = None):
        super().__init__(settings, location)
        self.min_delay = self.max_delay = 0
        self.backoff = 0
        self.fixtures = fixtures or {}
        self.root = Path(root or settings.get("fetch.fixtures_dir", "tests/fixtures"))
        self.calls: list[str] = []
        self.fail_once: set[str] = set()

    async def _fetch_once(self, url: str, render_js: bool) -> FetchResult:
        self.calls.append(url)
        for key in list(self.fail_once):
            if key in url:
                self.fail_once.discard(key)
                raise FetchError("injected failure", "http")
        for key, fname in sorted(self.fixtures.items(), key=lambda kv: -len(kv[0])):
            if key in url:
                p = self.root / fname
                raw = gzip.decompress(p.read_bytes()).decode("utf-8") if p.suffix == ".gz" else p.read_text(encoding="utf-8")
                return FetchResult(url, 200, raw, 0.01)
        return FetchResult(url, 404, "", 0.01)


def _fill(template, **values):
    """Recursively replace {placeholders} in a JSON-like provider payload template."""
    if isinstance(template, str):
        for k, v in values.items():
            template = template.replace("{" + k + "}", str(v))
        return template
    if isinstance(template, list):
        return [_fill(x, **values) for x in template]
    if isinstance(template, dict):
        return {k: _fill(v, **values) for k, v in template.items()}
    return template


class OxylabsRealtimeFetcher(Fetcher):
    """Oxylabs Web Scraper API, classic realtime endpoint (username / password), for clients whose existing paid
    Oxylabs service is that product. The request body is configuration (`fetch.oxylabs_realtime.payload`) so it can be
    matched to the plan's Kroger source without code changes; it must be validated with `mscraper probe` first –
    every response is still checked for the configured store, so a payload that does not pin the store fails the run."""

    name = "oxylabs_realtime"
    endpoint = "https://realtime.oxylabs.io/v1/queries"

    async def start(self):
        import httpx

        user, pwd = os.getenv("OXYLABS_USERNAME"), os.getenv("OXYLABS_PASSWORD")
        if not (user and pwd):
            raise FetchError("OXYLABS_USERNAME / OXYLABS_PASSWORD are not set (env vars / Key Vault secrets)", "error")
        self.client = httpx.AsyncClient(auth=(user, pwd), timeout=self.timeout + 60)

    async def close(self):
        await self.client.aclose()

    async def _fetch_once(self, url: str, render_js: bool) -> FetchResult:
        tpl = self.s.get("fetch.oxylabs_realtime.payload") or {"source": "kroger", "url": "{url}", "store_id": "{store_id}"}
        body = _fill(tpl, url=url, store_id=self.loc.store_id, zipcode=self.loc.zipcode)
        if render_js:
            body["render"] = "html"
        t0 = time.monotonic()
        r = await self.client.post(self.endpoint, json=body)
        elapsed = time.monotonic() - t0
        if r.status_code >= 500:
            self.stats["provider_faults"] += 1
            raise FetchError(f"provider fault {r.status_code}: {r.text[:160]}", "http")
        if r.status_code >= 400:
            raise FetchError(f"provider HTTP {r.status_code}: {r.text[:200]}", "http")
        res = (r.json().get("results") or [{}])[0]
        content = res.get("content") or ""
        status = int(res.get("status_code") or 200)
        return FetchResult(url, status, content if isinstance(content, str) else "", elapsed)


def build_fetcher(settings, location, **kw) -> Fetcher:
    name = os.getenv("MSCRAPER_FETCH_PROVIDER") or settings.get("fetch.provider", "oxylabs_kroger")
    if name == "oxylabs_kroger":
        return OxylabsKrogerFetcher(settings, location)
    if name == "oxylabs_realtime":
        return OxylabsRealtimeFetcher(settings, location)
    if name == "fixture":
        return FixtureFetcher(settings, location, **kw)
    raise ValueError(f"unknown fetch provider: {name}")
