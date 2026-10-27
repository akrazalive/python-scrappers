"""Shared fetching layer: pacing, retries with backoff, challenge and latency detection.

Provider adapters only implement `_fetch_once`. Everything that protects data quality
(retries, block detection, slow-response logging) lives here so it behaves the same
whichever provider is configured.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass

from ..config import Location, Settings
from ..parse.walmart import detect_challenge

log = logging.getLogger("wmscraper.fetch")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    html: str
    elapsed: float


class FetchError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # http | challenge | timeout | error


def fill(template, **values):
    """Recursively replace {placeholders} in a JSON-like provider template."""
    if isinstance(template, str):
        out = template
        for k, v in values.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    if isinstance(template, list):
        return [fill(x, **values) for x in template]
    if isinstance(template, dict):
        return {k: fill(v, **values) for k, v in template.items()}
    return template


class Fetcher:
    name = "base"

    def __init__(self, settings: Settings, location: Location):
        self.s = settings
        self.loc = location
        self.timeout = float(settings.get("fetch.timeout_seconds", 90))
        self.retries = int(settings.get("fetch.max_retries", 4))
        self.backoff = float(settings.get("fetch.backoff_base_seconds", 4))
        self.min_delay = float(settings.get("fetch.min_delay_seconds", 2))
        self.max_delay = float(settings.get("fetch.max_delay_seconds", 5))
        self.slow = float(settings.get("fetch.slow_response_seconds", 45))
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.budget = int(settings.get("fetch.max_requests_per_run", 0))  # 0 = unlimited
        self.total_budget = None  # persistent TotalBudget (budget.py), shared by every process of one approved test
        self.stats = {"requests": 0, "retries": 0, "challenges": 0, "http_errors": 0, "slow": 0}

    async def start(self):  # pragma: no cover - overridden where needed
        return None

    async def close(self):  # pragma: no cover
        return None

    async def _fetch_once(self, url: str) -> FetchResult:  # pragma: no cover
        raise NotImplementedError

    async def _pace(self):
        async with self._lock:  # pacing is global even when requests run concurrently
            wait = self._last + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def get(self, url: str) -> FetchResult:
        last_exc: FetchError | None = None
        for attempt in range(1, self.retries + 2):
            if self.budget and self.stats["requests"] >= self.budget:
                raise FetchError(f"request budget of {self.budget} reached (fetch.max_requests_per_run)", "budget")
            if self.total_budget is not None:  # counted and saved before the request is sent, retries included
                self.total_budget.take(url, self.loc.store_id)
            await self._pace()
            self.stats["requests"] += 1
            try:
                res = await self._fetch_once(url)
            except FetchError as exc:
                last_exc = exc
            except Exception as exc:  # network, provider errors
                last_exc = FetchError(f"{type(exc).__name__}: {exc}", "error")
            else:
                if res.elapsed > self.slow:
                    self.stats["slow"] += 1
                    log.warning("slow_response", extra={"url": url, "seconds": round(res.elapsed, 1)})
                if res.status >= 400:
                    self.stats["http_errors"] += 1
                    last_exc = FetchError(f"HTTP {res.status}", "http")
                elif detect_challenge(res.html, res.final_url):
                    self.stats["challenges"] += 1
                    last_exc = FetchError("bot challenge / block page", "challenge")
                elif len(res.html) < 2000:
                    last_exc = FetchError(f"suspiciously small response ({len(res.html)} bytes)", "error")
                else:
                    return res
            if attempt <= self.retries:
                self.stats["retries"] += 1
                delay = self.backoff * (2 ** (attempt - 1)) + random.uniform(0, self.backoff)
                log.warning("retry", extra={"url": url, "attempt": attempt, "reason": str(last_exc), "sleep": round(delay, 1)})
                await asyncio.sleep(delay)
        raise last_exc or FetchError("unknown fetch failure")


# ----------------------------------------------------------------------------- providers
class OxylabsFetcher(Fetcher):
    """Oxylabs Web Scraper API (realtime). Request body comes from settings so the
    store / fulfillment parameters can be adjusted without code changes."""

    name = "oxylabs"
    endpoint = "https://realtime.oxylabs.io/v1/queries"

    async def start(self):
        import httpx

        user, pwd = os.getenv("OXYLABS_USERNAME"), os.getenv("OXYLABS_PASSWORD")
        if not user or not pwd:
            raise FetchError("OXYLABS_USERNAME / OXYLABS_PASSWORD are not set", "error")
        self.client = httpx.AsyncClient(auth=(user, pwd), timeout=self.timeout + 30)

    async def close(self):
        await self.client.aclose()

    async def _fetch_once(self, url: str) -> FetchResult:
        tpl = self.s.get("fetch.oxylabs.payload", {"source": "universal", "url": "{url}", "render": "html", "geo_location": "{zipcode}"})
        body = fill(tpl, url=url, store_id=self.loc.store_id, zipcode=self.loc.zipcode)
        t0 = time.monotonic()
        r = await self.client.post(self.endpoint, json=body)
        if r.status_code >= 400:
            raise FetchError(f"provider HTTP {r.status_code}: {r.text[:200]}", "http")
        res = (r.json().get("results") or [{}])[0]
        return FetchResult(url, res.get("url") or url, int(res.get("status_code") or 200), res.get("content") or "", time.monotonic() - t0)


class OxylabsWebApiFetcher(Fetcher):
    """Oxylabs Web API, dedicated Walmart endpoint. Pins the store and fulfillment for every request:
    store_id, fulfillment_type=pickup and delivery_zip come from the location config. Bearer key from env."""

    name = "oxylabs_webapi"
    endpoint = "https://webapi.oxylabs.io/v1/scrape/walmart"
    general_endpoint = "https://webapi.oxylabs.io/v1/scrape"

    async def start(self):
        import httpx

        key = os.getenv("OXYLABS_WEBAPI_KEY")
        if not key:
            raise FetchError("OXYLABS_WEBAPI_KEY is not set", "error")
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=self.timeout + 60)

    async def close(self):
        await self.client.aclose()

    async def _fetch_once(self, url: str) -> FetchResult:
        fulfillment = self.s.get("fetch.oxylabs_fulfillment_type", "")  # "" = store pinned, no availability facet
        if "/store/" in url:  # the store's own page needs no store pinning; served by the general endpoint
            endpoint, body = self.general_endpoint, {"url": url, "location": "US", "output": ["html"]}
        else:
            endpoint = self.endpoint
            body = {"url": url, "store_id": self.loc.store_id, "delivery_zip": self.loc.zipcode,
                    "location": "US", "output": ["html"]}
            if fulfillment:
                body["fulfillment_type"] = fulfillment
        t0 = time.monotonic()
        r = await self.client.post(endpoint, json=body)
        if r.status_code >= 400:
            raise FetchError(f"provider HTTP {r.status_code}: {r.text[:200]}", "http")
        res = (r.json().get("results") or [{}])[0]
        meta = res.get("metadata") or {}
        status = int(((meta.get("statuses") or {}).get("http_request") or {}).get("code") or 200)
        return FetchResult(url, meta.get("url") or url, status, res.get("html") or "", time.monotonic() - t0)


class ZyteFetcher(Fetcher):
    name = "zyte"
    endpoint = "https://api.zyte.com/v1/extract"

    async def start(self):
        import httpx

        key = os.getenv("ZYTE_API_KEY")
        if not key:
            raise FetchError("ZYTE_API_KEY is not set", "error")
        self.client = httpx.AsyncClient(auth=(key, ""), timeout=self.timeout + 30)

    async def close(self):
        await self.client.aclose()

    async def _fetch_once(self, url: str) -> FetchResult:
        tpl = self.s.get("fetch.zyte.payload", {"url": "{url}", "browserHtml": True, "geolocation": "US"})
        body = fill(tpl, url=url, store_id=self.loc.store_id, zipcode=self.loc.zipcode)
        t0 = time.monotonic()
        r = await self.client.post(self.endpoint, json=body)
        if r.status_code >= 400:
            raise FetchError(f"provider HTTP {r.status_code}: {r.text[:200]}", "http")
        data = r.json()
        return FetchResult(url, data.get("url") or url, int(data.get("statusCode") or 200), data.get("browserHtml") or "", time.monotonic() - t0)


class PlaywrightFetcher(Fetcher):
    """Plain Chromium session for environments with authorised access.

    No CAPTCHA solving or fingerprint spoofing is performed: if Walmart serves a
    challenge, it is detected and reported, and the run fails safely.
    """

    name = "playwright"

    async def start(self):
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        proxy = None
        if os.getenv("PLAYWRIGHT_PROXY_SERVER"):
            proxy = {"server": os.environ["PLAYWRIGHT_PROXY_SERVER"],
                     "username": os.getenv("PLAYWRIGHT_PROXY_USERNAME") or None,
                     "password": os.getenv("PLAYWRIGHT_PROXY_PASSWORD") or None}
        self._browser = await self._pw.chromium.launch(headless=True, proxy=proxy)
        self._ctx = await self._browser.new_context(locale="en-US")
        cookies = fill(self.s.get("fetch.playwright.store_cookies", []), store_id=self.loc.store_id, zipcode=self.loc.zipcode)
        if cookies:
            await self._ctx.add_cookies(cookies)
        self._page = await self._ctx.new_page()

    async def close(self):
        await self._browser.close()
        await self._pw.stop()

    async def _fetch_once(self, url: str) -> FetchResult:
        t0 = time.monotonic()
        resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
        await self._page.wait_for_timeout(1500)
        html = await self._page.content()
        return FetchResult(url, self._page.url, resp.status if resp else 0, html, time.monotonic() - t0)


class FixtureFetcher(Fetcher):
    """Serves saved HTML from a directory (url -> file map). Used by tests only."""

    name = "fixture"

    async def _fetch_once(self, url: str) -> FetchResult:
        mapping = json.loads(open(os.path.join(self.s.get("fetch.fixture_dir"), "map.json"), encoding="utf-8").read())
        path = mapping.get(url)
        if not path:
            return FetchResult(url, url, 404, "", 0.0)
        html = open(os.path.join(self.s.get("fetch.fixture_dir"), path), encoding="utf-8").read()
        return FetchResult(url, url, 200, html, 0.0)


PROVIDERS = {c.name: c for c in (OxylabsWebApiFetcher, OxylabsFetcher, ZyteFetcher, PlaywrightFetcher, FixtureFetcher)}


def build_fetcher(settings: Settings, location: Location) -> Fetcher:
    name = settings.get("fetch.provider", "oxylabs")
    if name not in PROVIDERS:
        raise ValueError(f"unknown fetch.provider '{name}', choose one of {sorted(PROVIDERS)}")
    fetcher = PROVIDERS[name](settings, location)
    spec = settings.get("fetch.total_budget")  # NAME:TOTAL from --budget / WMSCRAPER_BUDGET (cli.py)
    if spec:
        from ..budget import TotalBudget, parse_spec
        from ..storage import build_storage

        bname, total = parse_spec(spec)
        fetcher.total_budget = TotalBudget(build_storage(settings), bname, total, command=f"{name} {location.key}")
    return fetcher
