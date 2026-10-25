"""Run validation – the gate between a finished run and publication.

A run is publishable only if ALL of these hold:
  1. store verified before collection and on every listing / product page used
  2. every configured category and discovered subcategory finished (no failed / blocked listing)
  3. no category returned zero products (a block is not an empty category)
  4. canary products readable with a local offer at the start and end of the run
  5. field completeness meets the configured minimums
  6. schema: exact field order, strings only, gupc/unit_price empty, no approx weights
Yield drops versus the last successful run are flagged; a drop below the configured
threshold blocks publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import FIELD_ORDER
from .parse.text import is_approximate_weight


@dataclass
class Validation:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, msg: str):
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    def as_dict(self):
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def completeness(records: list[dict]) -> dict[str, float]:
    n = len(records) or 1
    return {f: round(sum(1 for r in records if r.get(f, "") != "") / n, 4) for f in FIELD_ORDER}


def validate_run(settings, ck, records: list[dict], categories, previous_report: dict | None) -> Validation:
    v = Validation()

    # 1. store context
    store = ck.get("store_verification") or {}
    if not store.get("verified"):
        v.fail(f"store not verified before collection: {store.get('reason', 'unknown')}")
    mismatches = ck.get("store_mismatches", 0)
    if mismatches:
        v.fail(f"{mismatches} page(s) returned a different store context – run not publishable")

    # 2/3. category coverage
    listings = ck.listings()
    failed = [l for l in listings if l["status"] != "done"]
    for l in failed:
        v.fail(f"listing not completed: {l['category']} / {l['sub_category']} ({l['status']}: {l['error']})")
    by_cat: dict[str, int] = {}
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    expected = [c.name for c in categories]
    min_per_cat = int(settings.get("validation.min_products_per_category", 1))
    for name in expected:
        if not any(l["category"] == name for l in listings):
            v.fail(f"category never discovered/queued: {name}")
        elif by_cat.get(name, 0) < min_per_cat:
            v.fail(f"category returned {by_cat.get(name, 0)} products (min {min_per_cat}): {name}")
    for l in listings:
        if l["status"] == "done" and l["seen"] == 0:
            if not l.get("reported_total"):  # Walmart itself reports 0 products (e.g. an empty price band)
                v.warn(f"empty at source (Walmart reports 0 products): {l['category']} / {l['sub_category']} ({l['url']})")
            elif not l.get("page_size"):     # Walmart reports a count but serves no product, also on a re-fetch
                v.warn(f"Walmart count not backed by products: {l['category']} / {l['sub_category']} reports "
                       f"{l['reported_total']}, serves 0 ({l['url']})")
            else:
                v.fail(f"zero products on listing (possible silent block): {l['category']} / {l['sub_category']}")
        if l["capped"] or l.get("stop_reason") == "page_window_reached":
            v.fail(f"incomplete coverage: listing reached the page window without exhausting it: "
                   f"{l['category']} / {l['sub_category']} ({l['url']})")

    # thin results: collected vs Walmart's own reported count for the listing
    thin_ratio = float(settings.get("validation.thin_listing_ratio", 0.7))
    thin_fail = settings.get("validation.thin_listing_action", "fail") == "fail"
    max_pages = int(ck.get("pages_per_listing") or settings.get("crawl.max_pages_per_listing", 25))
    # count reconciliation: split listings must reach Walmart's own available-store-assortment count
    rec_ratio = float(settings.get("validation.store_count_reconciliation", 0.97))
    for l in listings:
        exp = int(l.get("expected_store_total") or 0)
        if l["status"] == "done" and exp and int(l.get("store_available") or 0) < rec_ratio * exp:
            v.fail(f"count reconciliation failed: {l['category']} / {l['sub_category']} collected "
                   f"{l.get('store_available')} available store offers, Walmart reports {exp} ({l['url']})")
    for l in listings:
        if l["status"] != "done" or not l.get("reported_total") or not l.get("page_size") or l.get("expected_store_total"):
            continue
        reachable = min(l["reported_total"], max_pages * l["page_size"])
        tolerance = int(settings.get("validation.source_count_tolerance", 2))
        if l["seen"] >= thin_ratio * reachable or reachable - l["seen"] <= tolerance:
            continue
        if l.get("stop_reason") == "walmart_served_no_more_products" or l["page_size"] < int(
                settings.get("crawl.full_page_min_items", 20)):
            # every page Walmart serves was read until it served no more products: its total is not backed by
            # served products (search-fallback count); reported per listing, never hidden
            v.warn(f"Walmart count not backed by products: {l['category']} / {l['sub_category']} reports "
                   f"{l['reported_total']}, served {l['seen']} until it stopped serving ({l['url']})")
            continue
        msg = (f"source-count reconciliation failed: {l['category']} / {l['sub_category']} saw {l['seen']} of "
               f"{reachable} reachable products (Walmart reports {l['reported_total']}) ({l['url']})")
        if thin_fail:
            v.fail(msg)
        else:
            v.warn(msg)

    # optional absolute floors per category (config: validation.category_minimums)
    for name, floor in (settings.get("validation.category_minimums") or {}).items():
        if name in expected and by_cat.get(name, 0) < int(floor):
            v.fail(f"category below configured minimum: {name} {by_cat.get(name, 0)} < {floor}")

    # yield vs previous successful run
    if previous_report:
        threshold = float(settings.get("validation.yield_drop_threshold", 0.6))
        prev = previous_report.get("count_by_category", {})
        for name, prev_n in prev.items():
            cur = by_cat.get(name, 0)
            if prev_n and cur < prev_n * threshold:
                v.fail(f"yield drop in {name}: {cur} vs {prev_n} last good run")

    # 4. canaries
    if settings.get("validation.canary_required", True):
        canary = ck.get("canary", {})
        for phase in ("start", "end"):
            res = canary.get(phase)
            if res is None:
                if ck.get("canary_configured"):
                    v.fail(f"canary check ({phase}) missing")
                else:
                    v.warn(f"canary check ({phase}) skipped – no canary_items configured")
            elif not res.get("ok"):
                v.fail(f"canary check ({phase}) failed: {res.get('detail')}")

    # 5. completeness (price fields only over records whose price is a fresh local store price; shipping-only
    #    offers have intentionally empty prices and carried-forward records keep last-observed values)
    comp = completeness(records)
    fresh = ({r["url"] for r in ck.availability_rows() if r["price_source"] in ("fresh", "fresh_store_offer")}
             if hasattr(ck, "availability_rows") else None)
    if fresh is not None:
        priced = [r for r in records if r["url"] in fresh]
        comp_price = completeness(priced) if priced else comp
        for f in ("regular_price",):
            comp[f] = comp_price.get(f, 0)
    for f, minimum in (settings.get("validation.min_field_completeness") or {}).items():
        if comp.get(f, 0) < float(minimum):
            v.fail(f"field completeness {f}={comp.get(f, 0):.2%} below {float(minimum):.0%}")

    # 6. schema
    for r in records[:]:
        if tuple(r.keys()) != FIELD_ORDER:
            v.fail("record field order does not match the required schema")
            break
        if any(not isinstance(x, str) for x in r.values()):
            v.fail("non-string value found (nulls are not allowed)")
            break
        if r["gupc"] or r["unit_price"]:
            v.fail("gupc/unit_price must be empty at scraper stage")
            break
        if is_approximate_weight(r["weight"]):
            v.fail(f"approximate-weight record leaked: {r['url']}")
            break
    if not records:
        v.fail("run produced no records")
    return v
