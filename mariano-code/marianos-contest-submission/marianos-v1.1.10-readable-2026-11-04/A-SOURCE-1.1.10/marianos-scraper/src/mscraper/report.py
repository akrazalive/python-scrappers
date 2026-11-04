"""Run report: everything the contest asks to see, generated from the checkpoint."""
from __future__ import annotations

import json
from collections import Counter

from . import deals
from .validate import completeness, scoped_completeness


def _scoped(records: list[dict], obs: dict) -> dict:
    by_url = {o.get("url"): k for k, o in obs.items() if o.get("url")}
    recs = {(r.get("upc") or by_url.get(r.get("url"), r.get("url"))): r for r in records}
    return scoped_completeness(recs, obs)
from .version import version_info


def _examples(records, predicate, n=5):
    return [r for r in records if predicate(r)][:n]


def _offer_census(census: dict) -> dict:
    rows = []
    for text, e in sorted(census.items(), key=lambda kv: -kv[1]["count"]):
        rows.append({"label": text, "template": e.get("template", ""), "count": e["count"],
                     "classified_as": deals.kind_of(text, e.get("template", ""))})
    totals = Counter()
    for r in rows:
        totals[r["classified_as"]] += r["count"]
    return {"distinct_labels": len(rows), "occurrences_by_class": dict(totals), "labels": rows[:200]}


def build_report(run_id, location, ck, records, runtime_s, validation, settings, categories,
                 obs: dict | None = None, coverage: dict | None = None, provenance: dict | None = None) -> dict:
    obs = obs or {}
    listings = ck.listings()
    reasons = ck.skip_reasons()
    by_cat = Counter(r["category"] for r in records)
    by_sub = Counter(f"{r['category']} > {r['sub_category']}" for r in records)
    upc_counts = Counter(r["upc"] for r in records if r["upc"])
    ledger = ck.table("ledger")
    excl = ck.table("exclusions")
    cat_cov = {}
    for c in categories:
        ls = [l for l in listings if l["category"] == c.name]
        cat_cov[c.name] = {
            "kind": c.kind, "csv_url": c.url, "discovery": ck.get(f"discovered:{c.name}"),
            "listings": len(ls), "listings_done": sum(l["status"] == "done" for l in ls),
            "listings_failed": sum(l["status"] == "failed" for l in ls),
            "pages_read": sum(l["pages"] for l in ls), "products_listed": sum(l["seen"] for l in ls),
            "products_in_subcategory": sum(l["matched"] for l in ls), "records_kept": by_cat.get(c.name, 0),
        }
        if c.kind == "coupons":
            cat_cov[c.name]["coupons_read"] = (ck.get("coupons") or {}).get("count", 0)
    return {
        "run_id": run_id,
        "scraper": version_info(),
        "location": {"key": location.key, "store_id": location.store_id, "zipcode": location.zipcode},
        "scope": ck.get("scope"),
        "started_at": ck.get("started_at"),
        "crawl_date": ck.get("crawl_date"),
        "store_verification": ck.get("store_verification"),
        "store_checks_during_run": {"pages_with_store_verified": ck.get("store_verified_pages", 0),
                                    "store_mismatches": ck.get("store_mismatches", 0)},
        "runtime_seconds": round(runtime_s, 1),
        "resumes": ck.get("resumes", 0),
        "total_unique_records": len(records),
        "duplicate_records_in_output": sum(n - 1 for n in upc_counts.values() if n > 1),
        "duplicates_prevented": reasons.get("duplicate", 0),
        "excluded": {k: v for k, v in reasons.items() if k not in ("kept", "duplicate")},
        "count_by_category": dict(sorted(by_cat.items())),
        "count_by_subcategory": dict(sorted(by_sub.items())),
        "category_coverage": cat_cov,
        "listings": listings,
        "field_completeness_all_rows": completeness(records),
        "field_completeness_scoped": _scoped(records, obs),
        "retention": {
            "fresh": sum(1 for o in obs.values() if o.get("status") == "fresh"),
            "carried": sum(1 for o in obs.values() if o.get("status") == "carried"),
            "no_store_price": sum(1 for o in obs.values() if o.get("availability") == "no_store_price"),
            "without_upc_identity_is_product_id": sum(1 for o in obs.values() if o.get("identity_source") == "data.id"),
            "sold_by_weight_kept": sum(1 for o in obs.values() if str(o.get("sell_by", "")).lower() == "weight"),
            "upc_source": dict(Counter(o.get("identity_source", "") for o in obs.values())),
        },
        "approximate_weight_exclusions": {
            "count": len(excl),
            "by_trigger_field": dict(Counter(e["trigger_field"] for e in excl)),
            "examples": excl[:10],
        },
        "provenance": provenance or {},
        "ledger_summary": {
            "pages": len(ledger),
            "pages_store_ok": sum(int(r["store_ok"] or 0) for r in ledger),
            "store_location_ids_seen": dict(Counter(r["store_location_id"] for r in ledger)),
            "request_location_ids_seen": dict(Counter(r["request_location_id"] for r in ledger if r["request_location_id"])),
            "active_modalities_seen": dict(Counter(r["active_modality"] for r in ledger if r["active_modality"])),
            "price_source_locations_seen": dict(Counter(x for r in ledger for x in (r["price_source_locations"] or "").split(",") if x)),
            "priced_products_in_responses": sum(int(r["priced"] or 0) for r in ledger),
            "by_kind": dict(Counter(r["kind"] for r in ledger)),
        },
        "coverage_summary": (coverage or {}).get("summary", {}),
        "coverage_by_category": (coverage or {}).get("by_category", {}),
        "examples": {
            "ppm": _examples(records, lambda r: r["ppm"]),
            "sale_price": _examples(records, lambda r: r["sale_price"]),
            "volume_deals": _examples(records, lambda r: r["volume_deals_description"]),
            "digital_deals": _examples(records, lambda r: r["digital_deals_description"]),
            "no_deals": _examples(records, lambda r: not (r["sale_price"] or r["volume_deals_description"]
                                                         or r["digital_deals_description"])),
            "store_brand": _examples(records, lambda r: r["store_brand"] == "yes"),
        },
        "coupons": ck.get("coupons", {}),
        "offer_census": _offer_census(ck.get("offer_census", {})),
        "canary": ck.get("canary", {}),
        "fetch_stats": ck.get("fetch_stats", {}),
        "validation": validation,
        "events_tail": [{"ts": t, "kind": k, "detail": json.loads(d)} for t, k, d in ck.db.execute(
            "SELECT ts, kind, detail FROM events ORDER BY rowid DESC LIMIT 50").fetchall()],
    }
