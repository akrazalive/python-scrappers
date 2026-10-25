"""Builds the delivery evidence pack, with test, live-retailer and Azure results kept separate.

  python tools/make_evidence.py --location walmart-100-bentonville --kill-after-pages 6
  python tools/make_evidence.py --location walmart-100-bentonville --azure-dir evidence/azure-<ts>   (add Azure section)

Layout (evidence/<timestamp>/):
  DELIVERY.md                 index: every client requirement → the file that proves it, + SHA-256 of every file
  0-source/                   versioned source ZIP, fingerprint, checksums
  A-unit-and-simulated/       automated tests + safeguard scenarios on the offline harness (NOT retailer data)
  B-live-walmart/             real run against the configured store: dataset, logs, raw responses, store context,
                              hard kill + resume, per-category completeness, thin / yield checks, results board
  C-azure-deployed/           scheduled Container Apps Job: schedule, executions, events, published manifest
Requires provider credentials in .env and the store in config/locations.yaml.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wmscraper.config import load_settings  # noqa: E402
from wmscraper.models import FIELD_ORDER  # noqa: E402
from wmscraper.storage import build_storage  # noqa: E402
from wmscraper.version import version_info  # noqa: E402

ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
PY = sys.executable


def sh(args, log: Path, timeout=None) -> int:
    with log.open("w", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(map(str, args))}\n# started {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        fh.flush()
        p = subprocess.run(args, cwd=ROOT, env=ENV, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
        fh.write(f"\n# finished {datetime.now(timezone.utc).isoformat(timespec='seconds')} exit code {p.returncode}\n")
    return p.returncode


def committed_pages(ckpt: Path) -> int:
    try:
        return sqlite3.connect(ckpt).execute("SELECT COALESCE(SUM(next_page - 1), 0) FROM listings").fetchone()[0]
    except sqlite3.Error:
        return 0


def export_traces(log_file: Path, out_csv: Path) -> None:
    """Per product: request URL -> final URL -> returned item id / name / UPC -> decision (from the JSON log)."""
    if not log_file.exists():
        return
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id", "match", "request_url", "final_url", "response_item_id", "response_name",
                    "response_upc", "output_title", "decision", "attempts"])
        for line in log_file.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") == "product_identity":
                a = e.get("attempts") or [["", "", ""]]
                w.writerow([e["item_id"], e["match"], a[0][0], a[-1][1], e["response_item_id"], e["response_name"],
                            e["response_upc"], e["output_title"], e["decision"], len(a)])


def section_repeat(out: Path, loc, st, first: dict, max_requests: int) -> dict:
    """REAL repeat collection: a second fresh run of the same scope, validated against the first published run."""
    d = out / "B2-live-repeat-run"
    d.mkdir()
    cmd = [PY, "-m", "wmscraper", "run", "--location", loc.key, "--fresh"] + (["--max-requests", str(max_requests)] if max_requests else [])
    sh(cmd, d / "01-repeat-run.log")
    state = st.get_json(f"{loc.key}/latest/manifest.json") or {}
    runs = sorted(p.name for p in st.local_path(f"{loc.key}/runs/x").parent.iterdir() if p.is_dir() and p.name[0].isdigit())
    run_id = [r for r in runs if r > first["run_id"]][-1]
    run_dir = st.local_path(f"{loc.key}/runs/{run_id}/records.json").parent
    rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    shutil.copy(run_dir / "records.json", d / "02-repeat-dataset.json")
    shutil.copy(run_dir / "report.json", d / "03-repeat-run-report.json")
    if (run_dir / "run.log").exists():
        shutil.copy(run_dir / "run.log", d / "04-repeat-structured-log.jsonl")
    a = {r["url"].split("?")[0]: r for r in json.loads((out / "B-live-walmart" / "04-dataset.json").read_text(encoding="utf-8"))}
    b = {r["url"].split("?")[0]: r for r in json.loads((run_dir / "records.json").read_text(encoding="utf-8"))}
    with (d / "05-run1-vs-repeat-by-category.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "run1_records", "repeat_records", "in_both", "price_changed"])
        for cat in sorted({r["category"] for r in a.values()} | {r["category"] for r in b.values()}):
            ka = {k for k, r in a.items() if r["category"] == cat}
            kb = {k for k, r in b.items() if r["category"] == cat}
            both = ka & kb
            w.writerow([cat, len(ka), len(kb), len(both),
                        sum(1 for k in both if a[k]["regular_price"] != b[k]["regular_price"] or a[k]["sale_price"] != b[k]["sale_price"])])
    summary = {"run_id": run_id, "records": rep["total_unique_records"], "validation_ok": rep["validation"]["ok"],
               "published": bool(state.get("run_id") == run_id), "compared_with_run": first["run_id"],
               "overlap_with_run1": len(set(a) & set(b)), "yield_check": "real: validated against the previous published run"}
    (d / "06-repeat-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def section_blocked(out: Path, loc, st, budget: int = 40) -> dict:
    """LIVE failed run on the authoritative version: a fresh run starved of requests cannot finish, must fail
    validation and must leave latest/ untouched."""
    d = out / "D-live-failed-run-not-published"
    d.mkdir()
    before = st.get_json(f"{loc.key}/latest/manifest.json")
    (d / "01-latest-manifest-BEFORE.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
    sh([PY, "-m", "wmscraper", "run", "--location", loc.key, "--fresh", "--max-requests", str(budget)], d / "02-blocked-run.log")
    after = st.get_json(f"{loc.key}/latest/manifest.json")
    (d / "03-latest-manifest-AFTER.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
    runs = sorted(p.name for p in st.local_path(f"{loc.key}/runs/x").parent.iterdir() if p.is_dir() and p.name[0].isdigit())
    rep = json.loads(st.local_path(f"{loc.key}/runs/{runs[-1]}/report.json").read_text(encoding="utf-8"))
    shutil.copy(st.local_path(f"{loc.key}/runs/{runs[-1]}/report.json"), d / "04-blocked-run-report.json")
    # operator closes the deliberately starved run so the schedule does not resume it
    state = st.get_json(f"{loc.key}/state.json") or {}
    st.put_json(f"{loc.key}/state.json", {**state, "open_run": None, "closed_run": rep["run_id"]})
    summary = {"run_id": rep["run_id"], "request_budget": budget, "records_collected": rep["total_unique_records"],
               "validation_ok": rep["validation"]["ok"], "errors": rep["validation"]["errors"][:6],
               "latest_unchanged": before == after, "latest_run_id": (after or {}).get("run_id")}
    (d / "05-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (d / "README.md").write_text(
        "# D. Live failed run - not published\n\nA real, fresh collection on store #100 with a deliberately "
        f"insufficient request budget ({budget}). It cannot complete, fails validation and is not published: "
        "compare 01 (before) and 03 (after) manifests.\n", encoding="utf-8")
    return summary


def section_traversal(out: Path, key: str, st, max_requests: int) -> dict:
    """Production traversal (no demo caps) of one category: every listing paginated to exhaustion."""
    d = out / "E-production-traversal"
    d.mkdir()
    cmd = [PY, "-m", "wmscraper", "run", "--location", key, "--fresh"] + (["--max-requests", str(max_requests)] if max_requests else [])
    sh(cmd, d / "01-traversal-run.log")
    runs = sorted(p.name for p in st.local_path(f"{key}/runs/x").parent.iterdir() if p.is_dir() and p.name[0].isdigit())
    run_dir = st.local_path(f"{key}/runs/{runs[-1]}/records.json").parent
    rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    shutil.copy(run_dir / "report.json", d / "02-traversal-report.json")
    shutil.copy(run_dir / "records.json", d / "03-traversal-dataset.json")
    if (run_dir / "run.log").exists():
        shutil.copy(run_dir / "run.log", d / "04-traversal-structured-log.jsonl")
    with (d / "05-listing-exhaustion.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "sub_category", "listing_url", "status", "pages_fetched", "walmart_max_page",
                    "exhausted", "walmart_reported_total", "seen", "kept"])
        for l in rep["listings"]:
            pages = l["next_page"] - 1
            w.writerow([l["category"], l["sub_category"], l["url"], l["status"], pages, l["max_page"],
                        pages >= l["max_page"], l.get("reported_total"), l["seen"], l["kept"]])
    ex = sum(1 for l in rep["listings"] if l["next_page"] - 1 >= l["max_page"])
    summary = {"run_id": rep["run_id"], "listings": len(rep["listings"]), "listings_exhausted": ex,
               "price_partitioned_listings": sum(1 for l in rep["listings"] if "min_price=" in l["url"]),
               "records": rep["total_unique_records"], "validation_ok": rep["validation"]["ok"],
               "requests": rep["fetch_stats"].get("requests"), "runtime_s": rep["runtime_seconds"]}
    (d / "06-traversal-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (d / "README.md").write_text(
        "# E. Production traversal (no demonstration caps)\n\nOne full category of store #100 crawled with production "
        "settings: every discovered listing paginated until Walmart's last page; listings beyond the 25-page window are "
        "split by subcategory or by price band. Product pages are not fetched in this section (traversal only); UPC "
        "enrichment is demonstrated in B.\n", encoding="utf-8")
    return summary


def section_source(out: Path):
    d = out / "0-source"
    d.mkdir()
    sh([PY, "tools/package_source.py"], d / "package_source.log")
    for f in (ROOT / "dist").iterdir():
        if f.name.endswith("-src.zip") or f.name == "SHA256SUMS.txt":
            shutil.copy(f, d / f.name)


def section_tests(out: Path):
    d = out / "A-unit-and-simulated"
    d.mkdir()
    sh([PY, "-m", "pytest", "-v", "-p", "no:cacheprovider"], d / "test-results.txt")
    sh([PY, "tools/verification_board.py"], d / "verification_board.log")
    for name in ("02-verification-board.png", "02-verification-evidence.json"):
        if (ROOT / "entry" / name).exists():
            shutil.copy(ROOT / "entry" / name, d / name.replace("02-", ""))
    (d / "README.md").write_text(
        "# A. Unit and simulated results\n\nThese results come from the offline test harness: fixture pages that mimic "
        "Walmart's page structure, used to trigger every safeguard on demand. **They are not retailer data.** Live "
        "Walmart results are in `../B-live-walmart/`, deployed Azure results in `../C-azure-deployed/`.\n", encoding="utf-8")


def section_live(out: Path, loc, st, kill_after: int, max_requests: int = 0) -> dict:
    d = out / "B-live-walmart"
    d.mkdir()
    sh([PY, "-m", "wmscraper", "verify-store", "--location", loc.key], d / "01-store-verification.log", timeout=900)

    # main live run re-verifies every product page; the repeat run (B2) then shows UPC reuse for known items
    cmd = [PY, "-m", "wmscraper", "run", "--location", loc.key]
    if max_requests:
        cmd += ["--max-requests", str(max_requests)]
    started = time.time()
    first = cmd + ["--fresh"]  # new run; the restart after the kill uses the plain command and must resume it
    previous = (st.get_json(f"{loc.key}/state.json") or {}).get("open_run")
    with (d / "02-run-part1-hard-killed.log").open("w", encoding="utf-8") as log1:
        log1.write(f"$ {' '.join(first)}\n")
        log1.flush()
        proc = subprocess.Popen(first, cwd=ROOT, env=ENV, stdout=log1, stderr=subprocess.STDOUT)
        run_id, ckpt = None, None
        while proc.poll() is None:
            state = st.get_json(f"{loc.key}/state.json") or {}
            if state.get("open_run") and state["open_run"] != previous:
                run_id = state["open_run"]
                ckpt = st.local_path(f"{loc.key}/runs/{run_id}/checkpoint.sqlite")
                if committed_pages(ckpt) >= kill_after:
                    break
            time.sleep(2)
        killed_at = committed_pages(ckpt) if ckpt else 0
        items_at_kill = sqlite3.connect(ckpt).execute("SELECT COUNT(*) FROM items").fetchone()[0] if ckpt else 0
        if proc.poll() is None:
            proc.kill()
            proc.wait()
            log1.write(f"\n# HARD KILL pid {proc.pid} (no cleanup) after {killed_at} committed pages, "
                       f"{items_at_kill} items saved, run {run_id}\n")
    sh(cmd, d / "03-run-resumed.log")
    wall = time.time() - started

    run_dir = st.local_path(f"{loc.key}/runs/{run_id}/records.json").parent
    rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    records = json.loads((run_dir / "records.json").read_text(encoding="utf-8"))
    assert rep["run_id"] == run_id, "resumed run must continue the same run id"
    shutil.copy(run_dir / "records.json", d / "04-dataset.json")
    shutil.copy(run_dir / "report.json", d / "05-run-report.json")
    if (run_dir / "run.log").exists():
        shutil.copy(run_dir / "run.log", d / "06-structured-log.jsonl")
    if (run_dir / "raw").exists():
        shutil.copytree(run_dir / "raw", d / "07-raw-source-responses")
    (d / "08-resume-proof.json").write_text(json.dumps({
        "run_id": run_id, "killed_after_committed_pages": killed_at, "items_in_checkpoint_at_kill": items_at_kill,
        "resumed_same_run_id": rep["run_id"] == run_id, "final_unique_records": rep["total_unique_records"],
        "duplicates_in_output": rep["duplicate_records_in_output"],
        "events": [e for e in rep["events_tail"] if e["kind"] in ("run_resumed", "run_aborted")]}, indent=2), encoding="utf-8")

    with (d / "09-category-completeness.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "listings", "done", "failed", "walmart_reported", "collected", "kept_records",
                    "upc_fill", "ppm_fill", "weight_fill"])
        for cat, c in rep["category_completeness"].items():
            w.writerow([cat, c["listings"], c["listings_done"], c["listings_failed"], c["walmart_reported"],
                        c["collected"], c["kept_records"], c["fill"]["upc"], c["fill"]["ppm"], c["fill"]["weight"]])
    with (d / "10-listing-coverage.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "sub_category", "status", "pages", "walmart_reported_total", "seen", "kept", "capped", "error"])
        for l in rep["listings"]:
            w.writerow([l["category"], l["sub_category"], l["status"], l["next_page"] - 1, l.get("reported_total"),
                        l["seen"], l["kept"], l["capped"], l["error"]])

    # SIMULATED check (not a real repeat collection): the live run's data validated against an artificial baseline
    prev = dict(rep)
    prev["count_by_category"] = {k: v * 3 for k, v in rep["count_by_category"].items()}
    prev["_label"] = "SIMULATED BASELINE - artificial previous report (3x counts); not a real collection"
    (d / "11-SIMULATED-baseline-report.json").write_text(json.dumps(prev, indent=2), encoding="utf-8")
    sh([PY, "-m", "wmscraper", "validate", "--location", loc.key, "--run-id", run_id,
        "--previous", str(d / "11-SIMULATED-baseline-report.json")], d / "11-SIMULATED-yield-drop-check.log")
    latest = st.get_json(f"{loc.key}/latest/manifest.json")
    (d / "12-published-manifest.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")

    # schema + direct-scrape examples
    keys_ok = all(tuple(r) == FIELD_ORDER for r in records)
    ex = {"schema_field_order": list(FIELD_ORDER), "all_records_match_schema": keys_ok,
          "ppm_examples": [r for r in records if r["ppm"]][:5],
          "upc_examples": [r for r in records if r["upc"]][:5],
          "volume_deal_examples": [r for r in records if r["volume_deals_description"]][:5],
          "digital_deal_examples": [r for r in records if r["digital_deals_description"]][:5],
          "no_deal_examples": [r for r in records if not (r["volume_deals_description"] or r["digital_deals_description"]
                                                          or r["sale_price"])][:5]}
    (d / "13-schema-and-field-examples.json").write_text(json.dumps(ex, indent=2, ensure_ascii=False), encoding="utf-8")

    export_traces(d / "06-structured-log.jsonl", d / "15-product-identity-trace.csv")
    (d / "16-offer-census.json").write_text(json.dumps(rep["offer_census"], indent=2, ensure_ascii=False), encoding="utf-8")
    sh([PY, "tools/results_board.py", str(run_dir)], d / "14-results-board.log")
    if (ROOT / "entry" / "02-results-board.png").exists():
        shutil.copy(ROOT / "entry" / "02-results-board.png", d / "14-results-board.png")
    fs = rep["fetch_stats"]
    return {"run_id": run_id, "records": rep["total_unique_records"], "runtime_s": rep["runtime_seconds"],
            "wall_s": round(wall), "requests": fs.get("requests"), "retries": fs.get("retries"),
            "challenges": fs.get("challenges"), "ok": rep["validation"]["ok"], "published": bool(latest and latest["run_id"] == run_id),
            "store": rep["store_verification"], "killed_at": killed_at, "schema_ok": keys_ok}


def write_index(out: Path, loc, live: dict | None, azure_dir: Path | None):
    v = version_info()
    L = ["# Delivery evidence – Walmart location scraper", "",
         f"* Version **{v['version']}** · source_sha256 `{v['source_sha256']}` (same value in every report and log)",
         f"* Location `{loc.key}` · store #{loc.store_id} · ZIP {loc.zipcode} · {loc.expected_address} · fulfillment {loc.fulfillment}"]
    if live:
        s = live["store"]
        L += [f"* Live run `{live['run_id']}`: {live['records']} unique records · runtime {live['runtime_s']} s · "
              f"{live['requests']} provider requests ({live['retries']} retries, {live['challenges']} challenges) · "
              f"validation ok: {live['ok']} · published: {live['published']}",
              f"* Store verified: {s.get('store_name')} #{s.get('store_id')}, {s.get('store_location')} ({s.get('checked_at')})"]
    L += ["", "| Requirement | Evidence |", "|---|---|",
          "| Versioned source | `0-source/*-src.zip`, `0-source/SHA256SUMS.txt` |",
          "| Unit / simulated tests (not retailer data) | `A-unit-and-simulated/` |",
          "| Real dataset ≥ 500 products, exact 22-field schema | `B-live-walmart/04-dataset.json`, `13-schema-and-field-examples.json` |",
          "| Store #100 + pickup context in source responses | `B-live-walmart/01-store-verification.log`, `07-raw-source-responses/index.json` (store_context per response) |",
          "| Logs | `B-live-walmart/02…`, `03…`, `06-structured-log.jsonl` |",
          "| Hard kill + resume | `B-live-walmart/02-run-part1-hard-killed.log` → `03-run-resumed.log`, `08-resume-proof.json` |",
          "| Per-category completeness, thin detection | `B-live-walmart/09-category-completeness.csv`, `10-listing-coverage.csv` |",
          "| Failed / thin runs cannot replace output | LIVE: `D-live-failed-run-not-published/` (if present) · SIMULATED baseline: `B-live-walmart/11-SIMULATED-*` · offline: `A-…/verification-board.png` |",
          "| Real repeat collection | `B2-live-repeat-run/` (second fresh run, validated against the first published run) |",
          "| Production traversal beyond 25 pages | `E-production-traversal/05-listing-exhaustion.csv` (exhaustion + price partitioning) |",
          "| Product identity / variants | `B-live-walmart/15-product-identity-trace.csv` (request → response id/name/UPC → output) |",
          "| Offers displayed by Walmart | `B-live-walmart/16-offer-census.json` (every label, classified) |",
          "| PPM, UPC, offer terms as scraped | `B-live-walmart/13-schema-and-field-examples.json`, raw responses in `07-…` |",
          "| Azure scheduled publishing | `C-azure-deployed/` |" if azure_dir else "| Azure scheduled publishing | (pending) |",
          "| Deployment, schedule, operations, cost | source ZIP → `docs/OPERATIONS.md`, `docs/COST.md`, `deploy/azure/` |",
          "", "## File checksums", "", "| file | sha256 |", "|---|---|"]
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "DELIVERY.md"):
        L.append(f"| {f.relative_to(out).as_posix()} | `{hashlib.sha256(f.read_bytes()).hexdigest()}` |")
    (out / "DELIVERY.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", required=True)
    ap.add_argument("--kill-after-pages", type=int, default=6)
    ap.add_argument("--max-requests", type=int, default=0, help="safety cap on paid requests per run invocation")
    ap.add_argument("--azure-dir", help="folder produced by deploy/azure/collect_evidence.sh")
    ap.add_argument("--repeat", action="store_true", help="add a real repeat collection (B2)")
    ap.add_argument("--blocked", action="store_true", help="add a live run that must fail and not publish (D)")
    ap.add_argument("--traversal-location", help="location key for the production traversal section (E)")
    ap.add_argument("--out", help="existing evidence folder to extend (e.g. to add the Azure section)")
    a = ap.parse_args()
    s = load_settings()
    loc = s.location(a.location)
    st = build_storage(s)
    if a.out:
        out = Path(a.out)
        live = json.loads((out / "live-summary.json").read_text()) if (out / "live-summary.json").exists() else None
    else:
        out = ROOT / "evidence" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out.mkdir(parents=True)
        section_source(out)
        section_tests(out)
        live = section_live(out, loc, st, a.kill_after_pages, a.max_requests)
        if a.repeat:
            live["repeat"] = section_repeat(out, loc, st, live, a.max_requests)
        if a.repeat or a.blocked:
            live["blocked"] = section_blocked(out, loc, st)
        if a.traversal_location:
            live["traversal"] = section_traversal(out, a.traversal_location, st, a.max_requests)
        (out / "live-summary.json").write_text(json.dumps(live, indent=2), encoding="utf-8")
    azure = None
    if a.azure_dir:
        azure = out / "C-azure-deployed"
        shutil.copytree(a.azure_dir, azure, dirs_exist_ok=True)
    write_index(out, loc, live, azure)
    print(out / "DELIVERY.md")


if __name__ == "__main__":
    main()
