"""Machine-readable coverage / remaining-gap reconciliation for the v1.0.0 runs (entry #69 and the stopped run).

  python tools/reconcile_v100_runs.py <out.json>

Reads only the runs' own checkpoints (state/<location>/runs/<run>/checkpoint.sqlite) and the CSV. v1.0.0 did not keep
the per-request product list that v1.1.0 keeps, so "read" per request is derived from its counters:
* stop_reason 'page_repeats_previous_results' (page 2 returned page 1 again) -> distinct read = seen / pages
* otherwise distinct read = seen
gap = Mariano's reported total for the request - distinct read (lower bound when the total is capped at 1,000).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOC = "marianos-544-crystal-lake"
RUNS = {
    "20261021T042105Z-fa0c1b": "entry #69 (1,027 rows delivered)",
    "20261021T044142Z-cf40b8": "query-expansion run stopped by the trial quota (not delivered)",
}
CAP = 1000


def csv_rows() -> list[dict]:
    with (ROOT / "config" / "categories.csv").open(encoding="utf-8-sig", newline="") as fh:
        return [{"category": r["Category (Auto)"].strip(), "url": r["URL"].strip()} for r in csv.DictReader(fh)]


def reconcile(run: str) -> dict:
    db = sqlite3.connect(ROOT / "state" / LOC / "runs" / run / "checkpoint.sqlite")
    db.row_factory = sqlite3.Row
    listings = [dict(r) for r in db.execute("SELECT * FROM listings ORDER BY rowid")]
    kept_by_shelf = defaultdict(int)
    for cat, sub, n in db.execute("SELECT category, sub_category, COUNT(*) FROM items GROUP BY category, sub_category"):
        kept_by_shelf[(cat, sub)] = n
    meta = {k: json.loads(v) for k, v in db.execute("SELECT k, v FROM meta")}
    requests, shelves = [], {}
    for l in listings:
        pages = int(l.get("pages") or 0)
        seen = int(l.get("seen") or 0)
        read = round(seen / pages) if (pages > 1 and l.get("stop_reason") == "page_repeats_previous_results") else seen
        total = int(l.get("reported_total") or 0)
        q = {"category": l["category"], "sub_category": l["sub_category"], "query": l["query"], "status": l["status"],
             "stop_reason": l.get("stop_reason", ""), "reported_total": total, "reported_total_is_capped": total >= CAP,
             "pages_requested": pages, "distinct_read": read, "in_subcategory": int(l.get("matched") or 0),
             "new_rows": int(l.get("kept") or 0), "gap": max(0, total - read) if l["status"] == "done" else None,
             "complete": l["status"] == "done" and total - read <= 0 and total < CAP}
        requests.append(q)
        sh = shelves.setdefault((l["category"], l["sub_category"]), {
            "category": l["category"], "sub_category": l["sub_category"], "requests": 0, "requests_done": 0,
            "largest_reported_total": 0, "largest_total_capped": False, "rows_delivered": 0})
        sh["requests"] += 1
        sh["requests_done"] += l["status"] == "done"
        if total > sh["largest_reported_total"]:
            sh["largest_reported_total"], sh["largest_total_capped"] = total, total >= CAP
    for (cat, sub), sh in shelves.items():
        sh["rows_delivered"] = kept_by_shelf.get((cat, sub), 0)
        sh["known_minimum_gap"] = max(0, sh["largest_reported_total"] - sh["rows_delivered"]) if sh["largest_reported_total"] else None
    by_cat = defaultdict(lambda: {"shelves": 0, "requests": 0, "rows_delivered": 0, "requests_with_gap": 0})
    for sh in shelves.values():
        by_cat[sh["category"]]["shelves"] += 1
        by_cat[sh["category"]]["rows_delivered"] += sh["rows_delivered"]
    for q in requests:
        by_cat[q["category"]]["requests"] += 1
        by_cat[q["category"]]["requests_with_gap"] += bool(q["gap"])
    in_run = set(by_cat)
    return {
        "run": run, "description": RUNS[run], "scope": meta.get("scope"), "final_status": meta.get("final_status"),
        "summary": {"requests": len(requests), "requests_done": sum(1 for q in requests if q["status"] == "done"),
                    "requests_not_fetched": sum(1 for q in requests if q["status"] != "done"),
                    "requests_complete": sum(1 for q in requests if q["complete"]),
                    "requests_with_capped_total": sum(q["reported_total_is_capped"] for q in requests),
                    "rows_in_checkpoint": sum(kept_by_shelf.values())},
        "csv_categories_not_in_run": [r["category"] for r in csv_rows() if r["category"] not in in_run
                                      and r["category"] != "Coupons"],
        "by_category": dict(by_cat), "shelves": list(shelves.values()), "requests": requests,
    }


def main():
    out = Path(sys.argv[1])
    res = {"method": __doc__.strip().splitlines()[0], "derivation": __doc__.strip(), "store_id": "53100544",
           "runs": [reconcile(r) for r in RUNS]}
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in res["runs"]:
        print(r["run"], r["summary"], "not in run:", len(r["csv_categories_not_in_run"]))


if __name__ == "__main__":
    main()
