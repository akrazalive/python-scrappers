"""Run validation – the gate between a finished run and publication.

A run is publishable only if ALL of these hold:
  1. store verified before collection, and every page / product came from the configured store
  2. every CSV category was discovered and every listing finished (no failed / blocked listing)
  3. no category returned zero products (a block is not an empty category); the Coupons
     category must show at least one coupon
  4. canary searches return store-priced products incl. the canary UPCs, at start and end
  5. field completeness meets the configured minimums
  6. schema: exact field order, strings only, gupc/unit_price empty, no approximate weights,
     no duplicate UPCs
  7. no category drops below the configured share of the last successful run
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import FIELD_ORDER
from .text import is_approximate


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


# fields whose completeness is measured only over fresh, priced, UPC-bearing observations: products kept
# without a current store price or without a UPC are valid rows with empty strings (retention rule)
PRICE_FIELDS = {"regular_price"}
UPC_FIELDS = {"upc"}


def scoped_completeness(recs_by_id: dict, obs: dict) -> dict[str, float]:
    fresh = {k: r for k, r in recs_by_id.items() if (obs.get(k) or {}).get("status", "fresh") == "fresh"}
    out = completeness(list(fresh.values()))
    priced = [r for k, r in fresh.items() if (obs.get(k) or {}).get("availability", "priced") == "priced"]
    with_upc = [r for k, r in fresh.items() if (obs.get(k) or {}).get("identity_source", "item.upc") == "item.upc"]
    for f in PRICE_FIELDS:
        out[f] = completeness(priced).get(f, 0) if priced else 1.0
    for f in UPC_FIELDS:
        out[f] = completeness(with_upc).get(f, 0) if with_upc else 1.0
    return out


def validate_run(settings, ck, records: list[dict], categories, previous_report: dict | None,
                 obs: dict | None = None, recs_by_id: dict | None = None) -> Validation:
    v = Validation()
    obs = obs or {}
    recs_by_id = recs_by_id if recs_by_id is not None else {r["upc"]: r for r in records}

    # 1. store
    store = ck.get("store_verification") or {}
    if not store.get("verified"):
        v.fail(f"store not verified before collection: {store.get('checks')}")
    if ck.get("store_mismatches", 0):
        v.fail(f"{ck.get('store_mismatches')} page(s)/product(s) came from a different store – run not publishable")

    # 2/3. coverage
    listings = ck.listings()
    by_cat = Counter(r["category"] for k, r in recs_by_id.items() if (obs.get(k) or {}).get("status", "fresh") == "fresh")
    min_per_cat = int(settings.get("validation.min_products_per_category", 1))
    for cat in categories:
        if cat.kind == "coupons":
            cps = ck.get("coupons") or {}
            if settings.get("coupons.enabled", True) and not cps.get("count"):
                v.fail(f"Coupons: no digital coupons read from {cat.url} ({ck.get('coupons_error', 'empty page')})")
            continue
        if ck.get(f"discovery_error:{cat.name}"):
            v.fail(f"category discovery failed: {cat.name}: {ck.get(f'discovery_error:{cat.name}')}")
        elif not any(l["category"] == cat.name for l in listings):
            v.fail(f"category never discovered/queued: {cat.name}")
        elif by_cat.get(cat.name, 0) < min_per_cat:
            v.fail(f"category returned {by_cat.get(cat.name, 0)} products (min {min_per_cat}): {cat.name}")
    shelves: dict[tuple, dict] = {}
    for l in listings:
        if l["status"] != "done":
            v.fail(f"listing not completed: {l['category']} / {l['sub_category']} [{l['query']}] ({l['status']}: {l['error']})")
        sh = shelves.setdefault((l["category"], l["sub_category"]), {"seen": 0, "matched": 0, "demo": False})
        sh["seen"] += l["seen"]
        sh["matched"] += l["matched"]
        sh["demo"] |= l["stop_reason"] == "demo_limit_reached"
    for (cat, sub), sh in shelves.items():
        if sh["demo"]:
            continue
        if sh["seen"] == 0:
            v.fail(f"zero products on shelf (all queries empty – possible silent block): {cat} / {sub}")
        elif sh["matched"] == 0:
            # a menu link whose taxonomy has no searchable products at this store (e.g. coffee filters are filed
            # under Kitchen): reported, not fatal - a whole category without products still fails above
            v.warn(f"menu shelf without products of its own taxonomy at this store: {cat} / {sub}")

    # 4. canaries
    if settings.get("validation.canary_required", True):
        canary = ck.get("canary", {})
        for phase in ("start", "end"):
            res = canary.get(phase)
            if res is None:
                v.fail(f"canary check ({phase}) missing")
            elif not res.get("ok"):
                v.fail(f"canary check ({phase}) failed: {res.get('detail')}")

    # 5. completeness (fresh observations; price over priced products, UPC over products that carry one)
    comp = scoped_completeness(recs_by_id, obs)
    for f, minimum in (settings.get("validation.min_field_completeness") or {}).items():
        if records and comp.get(f, 0) < float(minimum):
            v.fail(f"field completeness {f}={comp.get(f, 0):.2%} below {float(minimum):.0%}")

    # 6. schema + duplicates
    for r in records:
        if tuple(r.keys()) != FIELD_ORDER:
            v.fail("record field order does not match the required schema")
            break
        if any(not isinstance(x, str) for x in r.values()):
            v.fail("non-string value found (nulls are not allowed)")
            break
        if r["gupc"] or r["unit_price"]:
            v.fail("gupc/unit_price must be empty at scraper stage")
            break
        if is_approximate(r["weight"]):
            v.fail(f"approximate-weight record leaked: {r['url']}")
            break
    dups = [u for u, n in Counter(r["upc"] for r in records if r["upc"]).items() if n > 1]
    if dups:
        v.fail(f"{len(dups)} duplicate UPC(s) in output")
    if not records:
        v.fail("run produced no records")

    # 7. yield vs previous successful run
    if previous_report:
        threshold = float(settings.get("validation.yield_drop_threshold", 0.6))
        for name, prev_n in (previous_report.get("count_by_category") or {}).items():
            if prev_n and by_cat.get(name, 0) < prev_n * threshold:
                v.fail(f"yield drop in {name}: {by_cat.get(name, 0)} vs {prev_n} in last good run")
    return v
