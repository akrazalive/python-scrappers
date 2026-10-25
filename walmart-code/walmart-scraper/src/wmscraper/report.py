"""Run report: everything the contest asks to see, generated from the checkpoint."""
from __future__ import annotations

from collections import Counter

from .validate import completeness
from .version import version_info


def _category_completeness(listings, records) -> dict:
    """Per category: listings done/failed, Walmart-reported vs collected, kept records, key-field fill rates."""
    out = {}
    for l in listings:
        c = out.setdefault(l["category"], {"listings": 0, "listings_done": 0, "listings_failed": 0,
                                           "walmart_reported": 0, "collected": 0, "kept_records": 0})
        c["listings"] += 1
        c["listings_done"] += l["status"] == "done"
        c["listings_failed"] += l["status"] == "failed"
        c["walmart_reported"] += l.get("reported_total") or 0
        c["collected"] += l["seen"]
    for cat, c in out.items():
        recs = [r for r in records if r["category"] == cat]
        c["kept_records"] = len(recs)
        n = len(recs) or 1
        c["fill"] = {f: round(sum(1 for r in recs if r[f]) / n, 3) for f in ("upc", "ppm", "weight", "image_url", "regular_price")}
    return out


def _availability(ck) -> dict:
    rows = ck.availability_rows()
    by_status, by_price = Counter(r["status"] for r in rows), Counter(r["price_source"] for r in rows)
    return {"by_status": dict(by_status), "by_price_source": dict(by_price),
            "carried_forward": ck.get("carried_forward", 0),
            "examples": {s: [r for r in rows if r["status"] == s][:3] for s in by_status}}


def _offer_census(census: dict) -> dict:
    """Classify every displayed label with the same rules used for the output fields."""
    from .parse import deals

    rows = []
    for text, e in sorted(census.items(), key=lambda kv: -kv[1]["count"]):
        d = deals.classify([text])
        kind = ("volume_deal" if d.volume_description else "digital_deal" if d.digital_description
                else "reward_not_a_price_reduction" if d.ignored_rewards else "other_label")
        rows.append({"label": text, "classified_as": kind, **e})
    totals = {}
    for r in rows:
        totals[r["classified_as"]] = totals.get(r["classified_as"], 0) + r["count"]
    return {"distinct_labels": len(rows), "occurrences_by_class": totals, "labels": rows}


def _examples(records, predicate, n=5):
    return [r for r in records if predicate(r)][:n]


def build_report(run_id: str, location, store: dict, ck, records: list[dict], runtime_s: float,
                 fetch_stats: dict, validation: dict, settings) -> dict:
    reasons = ck.skip_reasons()
    listings = ck.listings()
    by_cat = Counter(r["category"] for r in records)
    by_sub = Counter(f"{r['category']} > {r['sub_category']}" for r in records)
    urls = Counter(r["url"] for r in records)
    return {
        "run_id": run_id,
        "scraper": version_info(),
        "location": {"key": location.key, "store_id": location.store_id, "zipcode": location.zipcode,
                     "fulfillment": location.fulfillment},
        "store_verification": store,
        "fulfillment_context": {
            "listing_filter": {k: str(v).replace("{store_id}", location.store_id)
                               for k, v in (settings.get("crawl.listing_params") or {}).items()},
            "provider_pinning": {"store_id": location.store_id, "fulfillment_type": location.fulfillment,
                                 "delivery_zip": location.zipcode},
            "store_mismatch_pages": ck.get("store_mismatches", 0),
            "pages_with_store_verified": ck.get("store_verified_pages", 0),
        },
        "runtime_seconds": round(runtime_s, 1),
        "total_unique_records": len(records),
        "duplicate_records_in_output": sum(c - 1 for c in urls.values() if c > 1),
        "duplicates_prevented": reasons.get("duplicate", 0),
        "excluded": {k: v for k, v in reasons.items() if k not in ("kept", "duplicate")},
        "count_by_category": dict(sorted(by_cat.items())),
        "count_by_subcategory": dict(sorted(by_sub.items())),
        "listings": listings,
        "field_completeness": completeness(records),
        "category_completeness": _category_completeness(listings, records),
        "examples": {
            "ppm": _examples(records, lambda r: r["ppm"]),
            "volume_deals": _examples(records, lambda r: r["volume_deals_description"]),
            "digital_deals": _examples(records, lambda r: r["digital_deals_description"]),
            "sale_price": _examples(records, lambda r: r["sale_price"]),
            "no_deals": _examples(records, lambda r: not (r["volume_deals_description"] or r["digital_deals_description"] or r["sale_price"])),
            "private_label": _examples(records, lambda r: r["store_brand"] == "yes"),
        },
        "offer_census": _offer_census(ck.get("offer_census", {})),
        "availability": _availability(ck),
        "count_reconciliation": [{k: l.get(k) for k in ("category", "sub_category", "url", "expected_store_total",
                                                          "store_available", "store_oos", "stop_reason", "next_page",
                                                          "max_page", "reported_total", "seen", "kept", "page_size",
                                                          "status", "error")} for l in listings],
        "product_identity": {"variant_mismatches": ck.db.execute(
            "SELECT COUNT(*) FROM events WHERE kind='variant_mismatch'").fetchone()[0],
            "enriched": ck.db.execute("SELECT COUNT(*) FROM items WHERE enriched=1").fetchone()[0],
            "listing_data_only": ck.db.execute("SELECT COUNT(*) FROM items WHERE enriched IN (2, 3)").fetchone()[0],
            "upc_reused_from_last_verified_run": ck.db.execute("SELECT COUNT(*) FROM items WHERE enriched=5").fetchone()[0]},
        "fetch_stats": fetch_stats,
        "canary": ck.get("canary", {}),
        "validation": validation,
        "events_tail": [dict(zip(("ts", "kind", "detail"), e)) for e in ck.db.execute(
            "SELECT ts, kind, detail FROM events ORDER BY rowid DESC LIMIT 50").fetchall()],
    }
