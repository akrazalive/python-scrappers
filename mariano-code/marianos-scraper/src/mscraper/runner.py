"""One run for one store location: verify store → discover → crawl → coupons → validate → publish.

Every step is checkpointed; `run --resume` continues an interrupted run from the exact query where it stopped
(records already stored are never fetched or written twice). Every page used is written to the provenance ledger
with the SHA-256 of the exact response and a gzip excerpt of its price-bearing product data (see evidence.py).
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from . import coverage, evidence, parse, retention
from .checkpoint import Checkpoint
from .config import Category, Location, Settings
from .fetch import FetchError, build_fetcher
from .report import build_report
from .validate import validate_run

log = logging.getLogger("mscraper.run")


def _has_monetary_price(store_prices: dict) -> bool:
    """Return whether a store-price block contains a source-returned money value."""
    for kind in ("regular", "promo"):
        value = store_prices.get(kind)
        if isinstance(value, dict):
            for key in ("price", "nforPrice", "unitPrice", "defaultDescription"):
                text = value.get(key)
                if isinstance(text, (int, float)) and text >= 0:
                    return True
                if isinstance(text, str) and re.search(r"\d+(?:\.\d{1,2})?", text):
                    return True
    return False


def _with_page(url: str, page: int) -> str:
    if page <= 1:
        return url
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "page"] + [("page", str(page))]
    return p._replace(query=urlencode(q)).geturl()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Runner:
    def __init__(self, settings: Settings, location: Location, storage, state_dir: Path, run_id: str | None = None,
                 categories: list[str] | None = None, limit_per_category: int = 0, fetcher=None):
        self.s, self.loc, self.storage = settings, location, storage
        self.cats: list[Category] = settings.categories_for(location, categories)
        self.scoped = bool(categories or location.categories)
        self.limit = int(limit_per_category or location.limit_per_category or 0)
        self.base = settings.get("base_url", "https://www.marianos.com").rstrip("/")
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
        self.dir = Path(state_dir) / location.key / "runs" / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ck = Checkpoint(self.dir / "checkpoint.sqlite")
        self.fetcher = fetcher or build_fetcher(settings, location)
        self.fetcher.on_refusal = self._archive_refusal
        self.census: dict[str, dict] = self.ck.get("offer_census", {})
        self.page_size = int(settings.get("crawl.page_size", 24))
        self.max_pages = int(settings.get("crawl.max_pages_per_query", 42))
        self.empty_stop = int(settings.get("crawl.stop_after_empty_pages", 3))
        self.skip_shelves = [re.compile(p, re.I) for p in settings.get("crawl.skip_shelf_patterns") or []]
        self.raw_per_cat = int(settings.get("evidence.raw_pages_per_category", 2))
        self._raw_count: dict[str, int] = {}

    def _archive_refusal(self, res) -> None:
        evidence.save_refusal(self.dir, res)

    # ------------------------------------------------------------------ helpers
    def _ctx(self, category: str, sub: str) -> dict:
        st = self.ck.get("store_verification") or {}
        return {"store_id": self.loc.store_id, "zipcode": st.get("zipcode", ""), "store_name": st.get("store_name", ""),
                "store_location": st.get("store_location", ""), "store_logo": st.get("store_logo", ""),
                "brands": self.s.private_label_brands, "category": category, "sub_category": sub, "base_url": self.base,
                "crawl_date": self.ck.get("crawl_date"),
                "approx_price_wording": self.s.get("crawl.approximate_weight_price_wording", True)}

    def _record_page(self, kind: str, where: dict, url: str, html: str, state: dict | None,
                     sp: parse.SearchPage | None = None, store: parse.StoreInfo | None = None) -> str:
        cat = where.get("category", "")
        keep_raw = self._raw_count.get(cat or kind, 0) < self.raw_per_cat
        if keep_raw:
            self._raw_count[cat or kind] = self._raw_count.get(cat or kind, 0) + 1
        sha, size, rel = evidence.save_page(self.dir, html, state, keep_raw)
        store = store or (sp.store if sp else (parse.store_info(state) if state else parse.StoreInfo()))
        modal = ""
        for m in (((state or {}).get("calypso") or {}).get("domains") or {}).get("modalityPreferences", {}).get("modalities") or []:
            modal = m.get("modalityType") or modal
        priced, srcs = 0, set()
        if sp:
            for u in sp.upcs:
                p = ((sp.products.get(u) or {}).get("data") or {}).get("price") or {}
                s = p.get("storePrices") or {}
                if s.get("regular"):
                    priced += 1
                if s.get("sourceLocationId"):
                    srcs.add(str(s.get("sourceLocationId")))
        self.ck.ledger_add({"ts": _now(), "kind": kind, "category": cat, "sub_category": where.get("sub", ""),
                            "query": where.get("query", ""), "url": url, "response_sha256": sha, "response_bytes": size,
                            "evidence_file": rel, "store_location_id": store.location_id,
                            "request_location_id": sp.request_location if sp else "", "active_modality": modal,
                            "listed": len(sp.upcs) if sp else 0, "priced": priced,
                            "price_source_locations": ",".join(sorted(srcs)),
                            "reported_total": sp.total if sp else 0,
                            "store_ok": int(store.location_id == self.loc.store_id
                                            and (not srcs or srcs == {self.loc.store_id}))})
        return sha

    async def _search(self, url: str, where: dict, kind: str = "search") -> tuple[parse.SearchPage, str, str]:
        box = {}

        def check(html: str):
            st = parse.extract_state(html)
            box["state"], box["sp"] = st, parse.search_page(st)

        res = await self.fetcher.get(url, validate=check)
        sha = self._record_page(kind, where, url, res.html, box["state"], sp=box["sp"])
        return box["sp"], res.html, sha

    def _store_ok(self, store: parse.StoreInfo, where: str) -> bool:
        if store.location_id == self.loc.store_id:
            self.ck.incr("store_verified_pages")
            return True
        self.ck.incr("store_mismatches")
        self.ck.event("store_mismatch", {"where": where, "got": store.location_id, "name": store.name, "want": self.loc.store_id})
        log.error("store mismatch", extra={"where": where, "got": store.location_id, "want": self.loc.store_id})
        return False

    # ------------------------------------------------------------------ 1. store + canary
    async def verify_store(self) -> dict:
        q = self.loc.canary_query or "milk"
        box = {}

        def keep_state(html):
            box["state"] = parse.extract_state(html)
            box["sp"] = parse.search_page(box["state"])

        url = f"{self.base}/search?query={quote(q)}&searchType=default_search"
        res = await self.fetcher.get(url, validate=keep_state)
        sp, html = box["sp"], res.html
        sha = self._record_page("store_verification", {"query": q}, url, html, box["state"], sp=sp)
        st = sp.store
        modality = ""
        for m in (((box["state"].get("calypso") or {}).get("domains") or {}).get("modalityPreferences") or {}).get("modalities") or []:
            modality = m.get("modalityType") or modality
        want_modality = self.s.get("store.expected_modality", "IN_STORE")
        price_sources: set[str] = set()
        priced_from_store = 0
        for u in sp.upcs:
            store_prices = (((sp.products.get(u) or {}).get("data") or {}).get("price") or {}).get("storePrices") or {}
            source = str(store_prices.get("sourceLocationId") or "")
            if source:
                price_sources.add(source)
            if source == self.loc.store_id and _has_monetary_price(store_prices):
                priced_from_store += 1
        checks = {
            "fulfillment_modality_matches": modality == want_modality,
            "location_id_matches": st.location_id == self.loc.store_id,
            "search_request_pinned_to_store": sp.request_location == self.loc.store_id,
            "zipcode_matches": (not self.loc.zipcode) or st.zipcode == self.loc.zipcode,
            "address_matches": (not self.loc.expected_address) or self.loc.expected_address.lower() in st.full_address.lower(),
            "banner_matches": "mariano" in st.banner.lower(),
            "prices_from_store": priced_from_store > 0,
            "price_source_locations_match": bool(price_sources) and price_sources == {self.loc.store_id},
        }
        result = {"verified": all(checks.values()), "checks": checks, "configured_store_id": self.loc.store_id,
                  "selected_store_id": st.location_id, "store_name": st.name, "store_location": st.full_address,
                  "zipcode": st.zipcode, "banner": st.banner, "fulfillment_modality": modality,
                  "store_logo": parse.store_logo(html, self.base) or self.s.get("store_logo_fallback", ""),
                  "verified_at": _now(), "evidence_query": q, "evidence_response_sha256": sha}
        self.ck.set("store_verification", result)
        log.info("store verification", extra=result)
        return result

    async def canary(self, phase: str) -> dict:
        q = self.loc.canary_query or "milk"
        found, priced = set(), 0
        try:
            sp, _, sha = await self._search(f"{self.base}/search?query={quote(q)}&searchType=default_search",
                                            {"query": q}, kind=f"canary_{phase}")
            self._store_ok(sp.store, f"canary-{phase}")
            for u in sp.upcs:
                sprice = ((sp.products.get(u, {}).get("data") or {}).get("price") or {}).get("storePrices") or {}
                if sprice.get("regular") and sprice.get("sourceLocationId") == self.loc.store_id:
                    priced += 1
                    found.add(u)
            missing = [u for u in self.loc.canary_upcs if u not in found]
            ok = priced >= self.page_size // 2 and not missing
            res = {"ok": ok, "priced_products": priced, "missing_canary_upcs": missing, "response_sha256": sha,
                   "detail": "" if ok else f"priced={priced}, missing={missing}"}
        except FetchError as exc:
            res = {"ok": False, "detail": f"fetch failed: {exc}"}
        c = self.ck.get("canary", {})
        c[phase] = res
        self.ck.set("canary", c)
        return res

    # ------------------------------------------------------------------ 2. discovery
    async def _site_menu(self) -> dict:
        """The site menu (every department with its sub-category links) is embedded in every Mariano's page;
        it is read once per run from a store-verified search page and kept in the checkpoint."""
        menu = self.ck.get("site_menu")
        if not menu:
            box = {}

            def check(html):
                st = parse.extract_state(html)
                m = {k: v for k, v in (st.get("dynamicdata") or {}).items() if "site-menu" in k}
                if not m:
                    raise parse.PageError("site menu missing", "malformed")
                box["m"], box["state"] = m, st

            url = f"{self.base}/search?query={quote(self.loc.canary_query or 'milk')}&searchType=default_search"
            res = await self.fetcher.get(url, validate=check)
            self._record_page("site_menu", {}, url, res.html, box["state"])
            self._store_ok(parse.store_info(box["state"]), "site menu page")
            menu = box["m"]
            self.ck.set("site_menu", menu)
        return {"dynamicdata": menu}

    async def discover(self, cat: Category) -> None:
        key = f"discovered:{cat.name}"
        if self.ck.get(key):
            return
        if cat.kind == "coupons":
            self.ck.set(key, {"kind": "coupons"})
            return
        if cat.kind == "list":
            sh = parse.shelf_from_url(cat.name, urlparse(cat.url).path)
            for q in sh.queries():
                self.ck.add_listing(cat.name, cat.name, f"{self.base}/search?query={quote(q)}&searchType=default_search",
                                    q, cat.taxonomy_id, False)
            self.ck.set(key, {"kind": "list", "shelves": 1, "taxonomy": cat.taxonomy_id, "queries": sh.queries()})
            return
        menu_state = await self._site_menu()
        shelves = parse.department_shelves(menu_state, cat.slug)          # complete sub-category tree from the site menu
        box = {}

        def check(html):
            box["state"] = parse.extract_state(html)

        try:  # the department page adds its curated tiles; it is optional because the menu already lists every shelf
            res = await self.fetcher.get(cat.url, validate=check, retries=int(self.s.get("crawl.department_page_retries", 2)))
            self._record_page("department", {"category": cat.name}, cat.url, res.html, box["state"])
            self._store_ok(parse.store_info(box["state"]), f"department {cat.name}")
            known = {(x.taxonomy or x.query.lower()) for x in shelves}
            for x in parse.department_shelves(box["state"], cat.slug):
                if (x.taxonomy or x.query.lower()) not in known:
                    shelves.append(x)
        except FetchError as exc:
            self.ck.event("department_page_unavailable", {"category": cat.name, "url": cat.url, "error": str(exc)[:200],
                                                         "used": "site menu sub-categories"})
        dept = parse.department_code(shelves)
        kept, skipped = 0, []
        for sh in shelves:
            if any(rx.search(sh.name) for rx in self.skip_shelves):
                skipped.append(sh.name)
                continue
            if sh.curated and not self.s.get("crawl.include_curated_shelves", True):
                skipped.append(sh.name)
                continue
            urls = []
            if sh.curated:  # the shelf's own curated search first, then its name
                urls.append((self.base + sh.url if sh.url.startswith("/") else sh.url, sh.query))
                tax = dept if self.s.get("crawl.curated_department_filter", True) else ""
            else:
                tax = sh.taxonomy
            for q in sh.queries():
                if sh.curated and q == sh.query:
                    continue        # the curated search itself is already queued with its own URL
                urls.append((f"{self.base}/search?query={quote(q)}&searchType=default_search", q))
            for url, q in urls:
                self.ck.add_listing(cat.name, sh.name, url, q, tax, sh.curated)
            if self.s.get("coupons.product_flag_via_search_filter", True) and not sh.curated:
                self.ck.add_listing(cat.name, sh.name, f"{self.base}/search?query={quote(sh.query)}&searchType=default_search"
                                    f"&savings=Coupons", f"{sh.query} | savings=Coupons", tax, False, mode="coupon_filter")
            kept += 1
        if not kept:
            self.ck.event("discovery_failed", {"category": cat.name, "url": cat.url})
            raise FetchError(f"no sub-categories found on {cat.url}", "malformed")
        self.ck.set(key, {"kind": "department", "shelves": kept, "skipped_brand_shelves": skipped, "department_code": dept,
                          "subcategories": [s.name for s in shelves if s.name not in skipped]})

    # ------------------------------------------------------------------ 3. crawl one listing
    async def crawl_pending(self) -> None:
        """Continuous work queue: every pending request starts as soon as the fetcher has a free slot, and requests
        queued by expansion / brand slices start as soon as they appear. (Up to 1.1.1 the crawl ran in waves: a wave
        waited for its slowest request, retries and back-off included, before the next wave started, leaving most
        parallel slots idle - the main reason for ~8-9 requests per minute on 21 Oct.) The fetcher's semaphore still
        bounds parallel requests (`fetch.concurrency`). Each request is started at most once per session; one left
        pending is picked up by the next resume."""
        running: dict[tuple, asyncio.Task] = {}
        started: set[tuple] = set()
        n = 0
        while True:
            for l in self.ck.pending():
                key = (l["category"], l["url"])
                if key not in started:
                    started.add(key)
                    running[key] = asyncio.create_task(self.crawl_listing(l))
            if not running:
                break
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for key in [k for k, t in running.items() if t in done]:
                exc = running.pop(key).exception()
                if exc:
                    for t in running.values():
                        t.cancel()
                    raise exc
            n += len(done)
            if n % 50 < len(done):
                log.info("crawl", extra={"requests_done": n, "requests_running": len(running),
                                         "requests_total": len(self.ck.listings()), "fetch": dict(self.fetcher.stats)})

    async def crawl_listing(self, l: dict) -> None:
        """Read one search request of a shelf.

        Mariano's server-rendered search returns the first 24 results of a request whatever page is asked for.
        Two mechanisms extend coverage: (1) brand slices – a request that reports more products than it returned is
        partitioned with Mariano's own `brandName` filter, one request per brand (slices are disjoint, and their
        reported totals reconcile against the parent request in coverage.json); (2) query expansion – new products
        queue queries built from their sub-commodity names and brands. Neither is capped by default."""
        cat, url, sub = l["category"], l["url"], l["sub_category"]
        page, streak = int(l["next_page"]), int(l["empty_streak"])
        paginate = bool(self.s.get("crawl.paginate", False))
        mode = l.get("mode") or "query"
        while True:
            if self.limit and self.ck.kept_in_category(cat) >= self.limit:
                self.ck.finish_listing(cat, url, "demo_limit_reached")
                return
            where = {"category": cat, "sub": sub, "query": l["query"]}
            try:
                sp, _, sha = await self._search(_with_page(url, page), where, kind=f"search_{mode}")
            except FetchError as exc:
                self.ck.fail_listing(cat, url, f"page {page}: {exc}")
                self.ck.event("listing_failed", {"category": cat, "sub": sub, "query": l["query"], "error": str(exc)})
                return
            if not self._store_ok(sp.store, f"{cat} / {sub} [{l['query']}]") or (
                    sp.request_location and sp.request_location != self.loc.store_id):
                self.ck.fail_listing(cat, url, f"page {page}: store context mismatch")
                return
            if mode == "brand_slice" and sp.upcs:
                want = l["query"].split("| brand=", 1)[-1].strip().lower()
                got = [((sp.products.get(u) or {}).get("data") or {}).get("item", {}).get("brand", {}).get("name", "").lower()
                       for u in sp.upcs]
                share = sum(1 for b in got if b == want) / len(got)
                if share < float(self.s.get("crawl.brand_slice_min_share", 0.9)):
                    # Mariano's ignored the brand filter: never count this response as coverage of the slice
                    self.ck.fail_listing(cat, url, f"brand filter not honored ({share:.0%} of products are '{want}')")
                    self.ck.event("brand_filter_not_honored", {"query": l["query"], "share": share})
                    return
            accepted, skipped, matched, terms, obs, excl, listed = [], [], 0, [], [], [], []
            coupon_rows: list[tuple[str, str, str]] = []
            ctx = self._ctx(cat, sub)
            for upc in sp.upcs:
                prod = sp.products.get(upc)
                item = ((prod or {}).get("data") or {}).get("item") or {}
                listed.append((upc, (item.get("brand") or {}).get("name", "")))
                if not parse.matches(parse.product_codes(prod, sp.codes.get(upc)), l["taxonomy"]):
                    skipped.append((upc, "outside_subcategory"))
                    continue
                matched += 1
                if not prod or "data" not in prod:
                    skipped.append((upc, "no_product_data"))
                    continue
                m = parse.map_product(prod, ctx)
                if m.reason == "store_mismatch":
                    self.ck.incr("store_mismatches")
                    self.ck.event("store_mismatch", {"upc": upc, "source": m.source_location})
                for text, tpl in m.offer_labels:
                    e = self.census.setdefault(text, {"count": 0, "template": tpl})
                    e["count"] += 1
                if m.record:
                    accepted.append((m.identity, sub, m.record))
                    obs.append({"identity": m.identity, "upc": m.record["upc"], "source_product_id": m.source_product_id,
                                "identity_source": m.identity_source, "availability": m.availability,
                                "sell_by": m.sell_by, "modalities": json.dumps(m.modalities),
                                "offers": json.dumps(m.offers, ensure_ascii=False), "response_sha256": sha,
                                "observed_at": _now(), "query": l["query"]})
                else:
                    skipped.append((m.identity or upc, m.reason))
                    if m.reason == "approximate_weight":
                        excl.append({"identity": m.identity, "category": cat, "sub_category": sub, "reason": m.reason,
                                     "trigger_field": m.trigger[0], "trigger_text": m.trigger[1], "response_sha256": sha})
                if mode in ("query", "expansion"):
                    terms.extend(parse.expansion_terms(prod, l["taxonomy"], sub))
                if mode == "coupon_filter" and m.identity:
                    coupon_rows.append((m.identity, l["query"], sha))
            streak = 0 if matched else streak + 1
            done, reason = True, "single_page_request"
            if paginate:
                done, reason = False, ""
                if len(sp.upcs) < self.page_size or (sp.total and page * self.page_size >= sp.total):
                    done, reason = True, "end_of_results"
                elif streak >= self.empty_stop:
                    done, reason = True, f"no_matching_products_in_{self.empty_stop}_pages"
                elif page >= self.max_pages:
                    done, reason = True, "query_page_window_reached"
            self.ck.listing_items_add(url, listed)
            self.ck.observe(obs)
            self.ck.exclude(excl)
            self.ck.flag_coupons(coupon_rows)
            new = self.ck.commit_page(cat, url, page, accepted, skipped, len(sp.upcs), matched, done, reason, streak, sp.total)
            sliced = self._slice(l, sp, listed) if mode == "query" else 0
            queued = self._expand(l, terms) if (new and mode in ("query", "expansion")) else 0
            log.info("request", extra={"category": cat, "sub": sub, "query": l["query"], "mode": mode,
                                       "listed": len(sp.upcs), "matched": matched, "new_records": new,
                                       "reported_total": sp.total, "brand_slices_queued": sliced,
                                       "queries_queued": queued, "response_sha256": sha})
            if done:
                return
            page += 1

    def _slice(self, l: dict, sp: parse.SearchPage, listed: list[tuple[str, str]]) -> int:
        """Partition a SEED request (the shelf's own name / parts) that reports more than it returned into brand slices
        (Mariano's brandName filter). Expansion requests are discovery helpers and are not partitioned."""
        if not self.s.get("crawl.brand_slices", True) or sp.total <= len(sp.upcs):
            return 0
        brands = {b for _, b in listed if b}
        # brands seen anywhere in this shelf can also hide in this request's unseen remainder
        for (b,) in self.ck.db.execute(
                "SELECT DISTINCT li.brand FROM listing_items li JOIN listings l ON l.url = li.url "
                "WHERE l.category=? AND l.sub_category=? AND li.brand != ''", (l["category"], l["sub_category"])):
            brands.add(b)
        cap = int(self.s.get("crawl.max_brand_slices_per_request", 0))
        added = 0
        for b in sorted(brands):
            if cap and added >= cap:
                break
            sep = "&" if "?" in l["url"] else "?"
            if self.ck.add_listing(l["category"], l["sub_category"], f"{l['url']}{sep}brandName={quote(b)}",
                                   f"{l['query']} | brand={b}", l["taxonomy"], bool(l["curated"]),
                                   mode="brand_slice", parent=l["url"]):
                added += 1
        return added

    def _expand(self, l: dict, terms: list[str]) -> int:
        cap = int(self.s.get("crawl.max_queries_per_shelf", 0))
        shelf = [x for x in self.ck.listings() if x["category"] == l["category"] and x["sub_category"] == l["sub_category"]
                 and (x.get("mode") or "query") in ("query", "expansion")]
        used = {x["query"].lower() for x in shelf}
        added = 0
        for t in terms:
            if cap and len(shelf) + added >= cap:
                break
            if t.lower() in used:
                continue
            used.add(t.lower())
            self.ck.add_listing(l["category"], l["sub_category"],
                                f"{self.base}/search?query={quote(t)}&searchType=default_search",
                                t, l["taxonomy"], bool(l["curated"]), mode="expansion")
            added += 1
        return added

    # ------------------------------------------------------------------ 4. coupons
    async def collect_coupons(self, cat: Category) -> None:
        if self.ck.get("coupons_done"):
            return
        box = {}

        def check(html):
            box["coupons"] = parse.coupons(html)
            box["state"] = parse.extract_state(html)

        res = await self.fetcher.get(cat.url, render_js=bool(self.s.get("coupons.render_js", True)), validate=check)
        sha = self._record_page("coupons", {"category": cat.name}, cat.url, res.html, box["state"])
        self._store_ok(parse.store_info(box["state"]), "coupons page")
        cps = [{**c, "response_sha256": sha} for c in box["coupons"]]
        (self.dir / "coupons.json").write_text(json.dumps(cps, indent=2, ensure_ascii=False), encoding="utf-8")
        self.ck.set("coupons", {"count": len(cps), "url": cat.url, "bytes": len(res.html), "response_sha256": sha})
        self.ck.set("coupons_done", True)

    # ------------------------------------------------------------------ main
    async def run(self, publish: bool = True) -> dict:
        t0 = time.monotonic()
        started = self.ck.get("started_at")
        if not started:
            self.ck.set("started_at", _now())
            self.ck.set("crawl_date", datetime.now(timezone.utc).date().isoformat())
            self.ck.set("scope", {"categories": [c.name for c in self.cats], "limit_per_category": self.limit,
                                  "scoped_demo": self.scoped or bool(self.limit)})
            self.ck.set("provenance_start", {**evidence.fingerprints(self.s), "recorded_at": _now()})
        else:
            self.ck.incr("resumes")
            fp = {**evidence.fingerprints(self.s), "recorded_at": _now()}
            hist = self.ck.get("provenance_resumes", [])
            hist.append(fp)
            self.ck.set("provenance_resumes", hist)
            self.ck.event("resumed", {"retried_failed_listings": self.ck.retry_failed(),
                                      "items_already_kept": self.ck.db.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                                      "pending_requests": len(self.ck.pending()), "code_sha256": fp["code_sha256"]})
        await self.fetcher.start()
        try:
            store = self.ck.get("store_verification") or {}
            if not store.get("verified"):
                store = await self.verify_store()
                if not store["verified"]:
                    raise RuntimeError(f"store verification failed: {store['checks']}")
            if not (self.ck.get("canary") or {}).get("start"):
                await self.canary("start")
            for cat in self.cats:
                try:
                    await self.discover(cat)
                    if self.ck.get(f"discovery_error:{cat.name}"):
                        self.ck.set(f"discovery_error:{cat.name}", None)   # earlier failure healed on resume
                except FetchError as exc:
                    self.ck.set(f"discovery_error:{cat.name}", str(exc))
                    log.error("discovery failed", extra={"category": cat.name, "error": str(exc)})
            await self.crawl_pending()
            self.ck.set("offer_census", self.census)
            for cat in self.cats:
                if cat.kind == "coupons" and self.s.get("coupons.enabled", True):
                    try:
                        await self.collect_coupons(cat)
                    except FetchError as exc:
                        self.ck.set("coupons_error", str(exc))
            await self.canary("end")
        finally:
            self.ck.set("offer_census", self.census)
            prev = self.ck.get("fetch_stats_before_resume", [])
            self.ck.set("fetch_stats", {**self.fetcher.stats, "provider": self.fetcher.name, "earlier_sessions": prev})
            prev.append({**self.fetcher.stats, "ended_at": _now()})
            self.ck.set("fetch_stats_before_resume", prev)
            await self.fetcher.close()
            self.ck.flush(force=True)
        runtime = time.monotonic() - t0 + float(self.ck.get("runtime_before_resume", 0))
        self.ck.set("runtime_before_resume", runtime)
        return self.finish(runtime, publish)

    # ------------------------------------------------------------------ finish: retention, evidence, validation, publish
    def _previous(self) -> tuple[dict, dict]:
        prev_recs = self.storage.get_json(f"{self.loc.key}/latest/records.json") or []
        prev_obs = self.storage.get_json(f"{self.loc.key}/latest/observations.json") or {}
        by_url = {o.get("url"): k for k, o in prev_obs.items() if o.get("url")}
        out = {}
        for r in prev_recs:
            ident = r.get("upc") or by_url.get(r.get("url"), "")
            if ident:
                out[ident] = r
        return out, prev_obs

    def finish(self, runtime: float, publish: bool) -> dict:
        fresh = self.ck.identified_records()
        fresh_obs = {}
        for o in self.ck.table("observations"):
            o = dict(o)
            o["modalities"] = json.loads(o["modalities"] or "{}")
            o["offers"] = json.loads(o["offers"] or "[]")
            if o["identity"] in fresh:
                o["url"] = fresh[o["identity"]].get("url", "")
            fresh_obs[o["identity"]] = o
        for row in self.ck.table("coupon_flags"):
            o = fresh_obs.get(row["identity"])
            if o is not None:   # Mariano's savings=Coupons filter lists this product (coupon terms not exposed)
                o.setdefault("digital_coupon_available", {"source": "marianos.com search filter savings=Coupons",
                                                          "evidence_response_sha256": row["response_sha256"],
                                                          "query": row["query"]})
        demo = (self.ck.get("scope") or {}).get("scoped_demo")
        prev_recs, prev_obs = ({}, {}) if demo else self._previous()   # demo scope never carries / publishes
        recs_by_id, obs = retention.carry_forward(fresh, fresh_obs, prev_recs, prev_obs, self.run_id, self.ck.get("crawl_date"))
        records = list(recs_by_id.values())
        prev_report = self.storage.get_json(f"{self.loc.key}/latest/report.json")
        v = validate_run(self.s, self.ck, records, self.cats, prev_report, obs, recs_by_id)
        cov = coverage.reconcile(self.ck.listings(), self.ck.table("listing_items"), self.ck.table("ledger"))
        if cov["summary"]["unexplained_gap"]:
            v.fail(f"coverage: {cov['summary']['unexplained_gap']} product(s) in gaps without an explained reason")
        if cov["summary"]["queries"] and cov["summary"]["queries_complete"] < cov["summary"]["queries"]:
            v.warn(f"coverage: {cov['summary']['queries'] - cov['summary']['queries_complete']} of "
                   f"{cov['summary']['queries']} seed requests not proven complete (explained in coverage.json)")
        if demo:
            v.warn("demo scope (category subset / per-category limit): never published to latest/")
        provenance = {"start": self.ck.get("provenance_start"), "resumes": self.ck.get("provenance_resumes", []),
                      "finish": {**evidence.fingerprints(self.s), "recorded_at": _now()}}
        report = build_report(self.run_id, self.loc, self.ck, records, runtime, v.as_dict(), self.s, self.cats,
                              obs=obs, coverage=cov, provenance=provenance)
        files = {
            "records.json": json.dumps(records, ensure_ascii=False, indent=2),
            "report.json": json.dumps(report, ensure_ascii=False, indent=2),
            "observations.json": json.dumps(obs, ensure_ascii=False, indent=2),
            "coverage.json": json.dumps(cov, ensure_ascii=False, indent=2),
            "exclusions.json": json.dumps(self.ck.table("exclusions"), ensure_ascii=False, indent=2),
            "ledger.json": json.dumps(self.ck.table("ledger"), ensure_ascii=False, indent=2),
        }
        cp = self.dir / "coupons.json"
        if cp.exists():
            files["coupons.json"] = cp.read_text(encoding="utf-8")
        base = f"{self.loc.key}/runs/{self.run_id}"
        for name, body in files.items():
            (self.dir / name).write_text(body, encoding="utf-8")
            self.storage.put_bytes(f"{base}/{name}", body.encode("utf-8"))
        status = "validation_failed"
        self.ck.flush(force=True)       # durable checkpoint before anything is published
        if v.ok and not demo and publish:
            extras = {k: files[k] for k in ("observations.json", "coverage.json") if k in files}
            self.storage.publish(self.loc.key, self.run_id, records, report, extras=extras)
            status = "published"
        elif v.ok:
            status = "valid_not_published_demo" if demo else "valid_not_published"
        self.ck.set("final_status", status)
        self.ck.event("final_status", {"status": status, "records": len(records), "errors": v.errors[:20]})
        self.ck.flush(force=True)
        log.info("run finished", extra={"status": status, "records": len(records), "errors": v.errors[:10]})
        return {"run_id": self.run_id, "status": status, "records": len(records), "dir": str(self.dir),
                "errors": v.errors, "warnings": v.warnings}
