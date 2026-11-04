"""Machine-readable coverage / remaining-gap reconciliation (coverage.json).

Rules (client review of v1.1.0):
* Zero UNEXPLAINED gaps: for every seed request, `reported - read` is split into explained gap items, each with a
  reason and the SHA-256 of the response(s) it rests on; `unexplained_gap` must be 0 (validation fails otherwise).
* Every count Mariano's reported for a request is kept (`observed_totals`: each fetch's total + response SHA-256), so a
  stale, capped or changing count is visible and reconciled, never silently replaced.
* A request is `complete` only when it is proven: done, not capped, and the distinct products read reach the reported
  total (directly, or through brand slices that are each complete and whose totals cover the parent total).
  An incomplete request is never counted as complete.

Mechanics: Mariano's server-rendered search returns the first 24 results of a request whatever page is asked for. A
seed request (shelf name / parts) that reports more is partitioned with Mariano's own `brandName` filter; a product has
one brand, so slices are disjoint. Expansion and coupon-filter requests are listed separately (not part of the proof).

Gap reasons:
  request_not_completed            the request itself failed / was never fetched
  reported_total_capped            Mariano's showed its 1,000 display cap: the true total is unknown; only slices can prove it
  slice_not_completed              a brand slice failed (incl. "brand filter not honored") or was never fetched
  slice_exceeds_page               a brand slice reports more than one page returns and cannot be partitioned further
  brands_not_discovered            the parent reports more than its slices together: products of brands never seen
  site_count_inconsistent          slice totals exceed the parent total or a count changed between fetches (reconciled
                                   on the larger figure; both counts kept)
"""
from __future__ import annotations

from collections import defaultdict

REPORTED_TOTAL_CAP = 1000   # Mariano's search reports "1,000" for very broad requests (display cap)


def _totals(ledger: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in ledger:
        if str(r.get("kind", "")).startswith("search"):
            out[r["url"]].append({"reported_total": int(r.get("reported_total") or 0), "listed": int(r.get("listed") or 0),
                                  "response_sha256": r.get("response_sha256", ""), "ts": r.get("ts", "")})
    return out


def _request_view(l: dict, items: set, totals: dict) -> dict:
    obs = totals.get(l["url"], [])
    figures = sorted({o["reported_total"] for o in obs}) or [int(l.get("reported_total") or 0)]
    total = max(figures)
    return {"status": l["status"], "reported_total": total, "observed_totals": obs, "count_changed": len(figures) > 1,
            "capped": total >= REPORTED_TOTAL_CAP, "read": len(items),
            "evidence": [o["response_sha256"] for o in obs if o["response_sha256"]]}


def reconcile(listings: list[dict], listing_items: list[dict], ledger: list[dict] | None = None) -> dict:
    items_by_url: dict[str, set] = defaultdict(set)
    for r in listing_items:
        items_by_url[r["url"]].add(r["upc"])
    totals = _totals(ledger or [])
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for l in listings:
        if l.get("parent"):
            by_parent[l["parent"]].append(l)

    queries, shelves, supplementary = [], {}, []
    for l in listings:
        mode = l.get("mode") or "query"
        if l.get("parent") or mode == "coupon_filter":
            continue
        if mode == "expansion":   # discovery helpers: listed, not part of the proof
            supplementary.append({"category": l["category"], "sub_category": l["sub_category"], "query": l["query"],
                                  "status": l["status"], "reported_total": int(l.get("reported_total") or 0),
                                  "read": len(items_by_url.get(l["url"], ())), "new_records": int(l.get("kept") or 0)})
            continue
        me = _request_view(l, items_by_url.get(l["url"], set()), totals)
        slices = [(s, _request_view(s, items_by_url.get(s["url"], set()), totals)) for s in by_parent.get(l["url"], [])]
        distinct = set(items_by_url.get(l["url"], set()))
        for s, _ in slices:
            distinct |= items_by_url.get(s["url"], set())
        gap_items: list[dict] = []
        if me["status"] != "done":
            gap_items.append({"reason": "request_not_completed", "count": None,
                              "detail": l.get("error", "") or me["status"], "evidence": me["evidence"]})
        slice_sum = 0
        for s, sv in slices:
            slice_sum += sv["reported_total"]
            if sv["status"] != "done":
                gap_items.append({"reason": "slice_not_completed", "brand_filter": s["query"],
                                  "count": sv["reported_total"] if sv["reported_total"] else None,
                                  "detail": s.get("error", "") or sv["status"], "evidence": sv["evidence"]})
            elif sv["reported_total"] > sv["read"]:
                gap_items.append({"reason": "slice_exceeds_page", "brand_filter": s["query"],
                                  "count": sv["reported_total"] - sv["read"], "evidence": sv["evidence"]})
            if sv["count_changed"]:
                gap_items.append({"reason": "site_count_inconsistent", "brand_filter": s["query"], "count": 0,
                                  "detail": f"slice count changed between fetches: "
                                            f"{[o['reported_total'] for o in sv['observed_totals']]}",
                                  "evidence": sv["evidence"]})
        if me["capped"]:
            gap_items.append({"reason": "reported_total_capped", "count": None,
                              "detail": f"Mariano's shows at most {REPORTED_TOTAL_CAP}; brand slices sum to {slice_sum}",
                              "evidence": me["evidence"]})
        elif slice_sum < me["reported_total"] and me["status"] == "done":
            missing = me["reported_total"] - max(slice_sum, me["read"])
            if missing > 0:
                gap_items.append({"reason": "brands_not_discovered", "count": missing,
                                  "detail": f"request reports {me['reported_total']}, its {len(slices)} brand slices report "
                                            f"{slice_sum}, one page returns {me['read']}", "evidence": me["evidence"]})
        elif slices and slice_sum > me["reported_total"]:
            gap_items.append({"reason": "site_count_inconsistent", "count": 0,
                              "detail": f"slices report {slice_sum} > request total {me['reported_total']}; reconciled on {slice_sum}",
                              "evidence": me["evidence"]})
        if me["count_changed"]:
            gap_items.append({"reason": "site_count_inconsistent", "count": 0,
                              "detail": f"count changed between fetches: {[o['reported_total'] for o in me['observed_totals']]}",
                              "evidence": me["evidence"]})
        # proof target: the larger of the request total and its slice sum (a stale / low site total never hides products)
        target = max(me["reported_total"], slice_sum)
        gap = max(0, target - len(distinct))
        explained = sum(g["count"] for g in gap_items if isinstance(g.get("count"), int))
        open_ended = any(g["count"] is None for g in gap_items)   # capped / not fetched: size unknown, reason explicit
        unexplained = 0 if open_ended else max(0, gap - explained)
        slices_ok = all(sv["status"] == "done" and sv["reported_total"] <= sv["read"] for _, sv in slices)
        complete = (me["status"] == "done" and not me["capped"] and gap == 0 and slices_ok
                    and not any(g["reason"] in ("request_not_completed", "slice_not_completed") for g in gap_items))
        q = {"category": l["category"], "sub_category": l["sub_category"], "query": l["query"], "url": l["url"],
             "status": me["status"], "reported_total": me["reported_total"], "observed_totals": me["observed_totals"],
             "reported_total_is_capped": me["capped"], "listed_first_page": me["read"],
             "brand_slices": len(slices), "brand_slice_reported_sum": slice_sum, "distinct_products_read": len(distinct),
             "gap": gap, "gap_items": gap_items, "unexplained_gap": unexplained, "complete": complete,
             "slices": [{"brand_filter": s["query"], "status": sv["status"], "reported_total": sv["reported_total"],
                         "read": sv["read"], "observed_totals": sv["observed_totals"]} for s, sv in slices]}
        queries.append(q)
        sh = shelves.setdefault((l["category"], l["sub_category"]), {
            "category": l["category"], "sub_category": l["sub_category"], "queries": 0, "queries_complete": 0,
            "gap_sum": 0, "unexplained_gap": 0, "failed": 0})
        sh["queries"] += 1
        sh["queries_complete"] += complete
        sh["gap_sum"] += gap
        sh["unexplained_gap"] += unexplained
        sh["failed"] += me["status"] == "failed"
    cats: dict[str, dict] = {}
    for sh in shelves.values():
        c = cats.setdefault(sh["category"], {"shelves": 0, "shelves_all_queries_complete": 0, "queries": 0,
                                             "queries_complete": 0, "gap_sum": 0, "unexplained_gap": 0})
        c["shelves"] += 1
        c["shelves_all_queries_complete"] += sh["queries"] == sh["queries_complete"]
        for k in ("queries", "queries_complete", "gap_sum", "unexplained_gap"):
            c[k] += sh[k]
    reasons: dict[str, int] = defaultdict(int)
    for q in queries:
        for g in q["gap_items"]:
            reasons[g["reason"]] += 1
    return {
        "method": "per seed request: every Mariano's count kept with its response; the gap is split into explained items",
        "summary": {"queries": len(queries), "queries_complete": sum(q["complete"] for q in queries),
                    "queries_with_capped_total": sum(q["reported_total_is_capped"] for q in queries),
                    "products_in_gaps": sum(q["gap"] for q in queries),
                    "unexplained_gap": sum(q["unexplained_gap"] for q in queries),
                    "gap_reasons": dict(reasons)},
        "by_category": cats,
        "shelves": list(shelves.values()),
        "queries": queries,
        "expansion_requests": supplementary,
    }
