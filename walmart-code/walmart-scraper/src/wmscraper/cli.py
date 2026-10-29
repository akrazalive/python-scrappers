"""Command line entry point.

  python -m wmscraper run --location walmart-100-bentonville              # full production run (resumes automatically)
  python -m wmscraper run --location walmart-100-bentonville --categories "Food,Pets" --limit 600 --demo
  python -m wmscraper run-all                                 # every enabled location (used by the Azure job)
  python -m wmscraper verify-store --location walmart-100-bentonville --max-requests 10   # store + canary check only
  python -m wmscraper status                                  # version, provider, credentials present, storage (0 requests)
  python -m wmscraper selfcheck                               # status + test-blob write/read in the container (0 requests)
  python -m wmscraper budget-status [--name probe]            # persistent request totals: used / remaining

  --budget NAME:TOTAL (or env WMSCRAPER_BUDGET) puts a command under a TOTAL request cap that persists in the run
  storage across retries, resumes, restarts and repeated job executions (see budget.py).
  python -m wmscraper summary --location walmart-100-bentonville [--run-id ID]
  python -m wmscraper retry-failed --location walmart-100-bentonville --run-id ID
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from . import logging_setup
from .checkpoint import Checkpoint
from .config import load_settings
from .runner import Run
from .storage import build_storage


def _load_env():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def cmd_run(args, s):
    cats = None  # None -> the location's configured scope (or all categories)
    if args.categories:
        wanted = {c.strip().lower() for c in args.categories.split(",")}
        cats = [c for c in s.categories if c.name.lower() in wanted]
        missing = wanted - {c.name.lower() for c in cats}
        if missing:
            sys.exit(f"unknown categories: {sorted(missing)}")
    demo = args.demo or bool(args.categories) or bool(args.limit)
    if args.fresh:  # operator decision: close an open (aborted) run instead of resuming it; it stays in runs/ for audit
        st = build_storage(s)
        state = st.get_json(f"{args.location}/state.json") or {}
        if state.get("open_run"):
            print(f"closing open run {state['open_run']} (kept for audit), starting a new run")
            st.put_json(f"{args.location}/state.json", {**state, "open_run": None, "closed_run": state["open_run"]})
    if args.refresh_product_pages:
        s.raw["_refresh_product_pages"] = True
    if args.max_requests:
        s.raw.setdefault("fetch", {})["max_requests_per_run"] = args.max_requests
    run = Run(s, s.location(args.location), run_id=args.run_id, categories=cats, limit=args.limit, demo=demo)
    log_file = Path(tempfile.gettempdir()) / f"wmscraper-{run.run_id}.log"
    logging_setup.setup(args.log_level, str(log_file))
    report = asyncio.run(run.execute())
    run.storage.put_bytes(f"{run.prefix}/run.log", log_file.read_bytes())
    print(json.dumps({k: report[k] for k in ("run_id", "total_unique_records", "runtime_seconds", "count_by_category", "validation", "published")}, indent=2))
    return 0 if report["validation"]["ok"] or demo else 2


def cmd_run_all(args, s):
    logging_setup.setup(args.log_level)
    status = 0
    for loc in s.locations:
        if not loc.enabled:
            continue
        try:
            report = asyncio.run(Run(s, loc).execute())
            status |= 0 if report["validation"]["ok"] else 2
        except Exception as exc:  # one location failing must not stop the others
            print(json.dumps({"location": loc.key, "error": str(exc)}))
            status |= 1
    return status


def cmd_verify_store(args, s):
    logging_setup.setup(args.log_level)
    if args.max_requests:
        s.raw.setdefault("fetch", {})["max_requests_per_run"] = args.max_requests
    loc = s.location(args.location)
    run = Run(s, loc, run_id="verify-" + os.urandom(3).hex(), demo=True)

    async def go():
        from .fetch import build_fetcher

        run.fetcher = build_fetcher(s, loc)
        run.fetcher.on_refusal = lambda res: run._archive("refused", res, "target access denial", always=True)
        await run.fetcher.start()
        try:
            await run.verify_store()
            await run.canary("start")
        finally:
            await run.fetcher.close()

    try:
        asyncio.run(go())
    finally:
        run._sync_checkpoint()
    canary = (run.ck.get("canary") or {}).get("start") or {}
    ok = bool(run.store.get("verified")) and (canary.get("ok") or not run.loc.canary_items)
    print(json.dumps({"verified": ok, "store": run.store, "canary": run.ck.get("canary")}, indent=2))
    return 0 if ok else 2


PROVIDER_ENV = {"oxylabs_webapi": ("OXYLABS_WEBAPI_KEY",), "oxylabs": ("OXYLABS_USERNAME", "OXYLABS_PASSWORD"),
                "zyte": ("ZYTE_API_KEY",), "playwright": ()}


def cmd_status(args, s):
    """Deployment check without any provider request: the default command of the manual Azure job."""
    from .version import version_info

    provider = s.get("fetch.provider", "oxylabs")
    out = {**version_info(), "provider": provider,
           # names only: whether each credential variable is present, never its value
           "credentials_present": {k: bool(os.getenv(k)) for k in PROVIDER_ENV.get(provider, ())},
           "max_requests_per_run": s.get("fetch.max_requests_per_run", 0),
           "output_backend": os.getenv("WMSCRAPER_OUTPUT_BACKEND") or s.get("output.backend", "local"),
           "enabled_locations": [loc.key for loc in s.locations if loc.enabled], "provider_requests": 0}
    try:
        st = build_storage(s)
        out["storage"] = {loc: bool(st.get_json(f"{loc}/latest/report.json")) for loc in out["enabled_locations"]}
        out["storage_ok"] = True
    except Exception as exc:  # e.g. role assignment not applied yet
        out["storage_ok"], out["storage_error"] = False, f"{type(exc).__name__}: {exc}"[:300]
    print(json.dumps(out, indent=2))
    return 0 if out["storage_ok"] else 1


def cmd_selfcheck(args, s):
    """`status` plus a test-blob write and read-back with the job's identity. 0 provider requests."""
    import secrets
    from datetime import datetime, timezone

    from .version import version_info

    provider = s.get("fetch.provider", "oxylabs")
    out = {**version_info(), "provider": provider, "provider_requests": 0,
           "credentials_present": {k: bool(os.getenv(k)) for k in PROVIDER_ENV.get(provider, ())}}
    key = f"_selfcheck/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.txt"
    token = secrets.token_hex(16).encode()
    try:
        st = build_storage(s)
        st.put_bytes(key, token)
        out["blob"] = {"backend": type(st).__name__, "key": key, "write": True, "read_back_matches": st.get_bytes(key) == token}
    except Exception as exc:  # e.g. role assignment missing or not yet propagated
        out["blob"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    out["ok"] = all(out["credentials_present"].values()) and out["blob"].get("read_back_matches") is True
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def cmd_budget_status(args, s):
    st = build_storage(s)
    rows = []
    for name in ([args.name] if args.name else []):
        state = st.get_json(f"_budgets/{name}.json")
        if state:
            rows.append({**state, "remaining": int(state["total"]) - int(state["used"])})
    print(json.dumps(rows, indent=2))
    return 0


def cmd_summary(args, s):
    st = build_storage(s)
    key = f"{args.location}/runs/{args.run_id}/report.json" if args.run_id else f"{args.location}/latest/report.json"
    rep = st.get_json(key)
    if not rep:
        sys.exit(f"no report at {key}")
    print(json.dumps({k: rep[k] for k in ("run_id", "store_verification", "total_unique_records", "duplicate_records_in_output",
                                           "duplicates_prevented", "excluded", "count_by_category", "field_completeness",
                                           "runtime_seconds", "validation")}, indent=2))
    return 0


def cmd_validate(args, s):
    """Re-run validation for a finished run, optionally against a given 'previous successful' report."""
    from .validate import validate_run

    st = build_storage(s)
    p = st.local_path(f"{args.location}/runs/{args.run_id}/checkpoint.sqlite")
    ck = Checkpoint(p)
    records = ck.records()
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else         st.get_json(f"{args.location}/latest/report.json")
    res = validate_run(s, ck, records, s.categories if not args.categories else
                       [c for c in s.categories if c.name in {x.strip() for x in args.categories.split(",")}], previous)
    print(json.dumps({"run_id": args.run_id, "records": len(records), "compared_with": args.previous or "latest/report.json",
                      **res.as_dict()}, indent=2))
    return 0 if res.ok else 2


def cmd_retry_failed(args, s):
    st = build_storage(s)
    p = st.local_path(f"{args.location}/runs/{args.run_id}/checkpoint.sqlite")
    ck = Checkpoint(p)
    n = ck.retry_failed()
    st.put_json(f"{args.location}/state.json", {"open_run": args.run_id})
    print(f"{n} failed listing(s) re-queued; next 'run' resumes run {args.run_id}")
    return 0


LIVE_COMMANDS = {"run", "run-all", "verify-store"}


def main(argv=None):
    _load_env()
    ap = argparse.ArgumentParser(prog="wmscraper", description="Walmart location-specific scraper")
    ap.add_argument("--config", default=os.getenv("WMSCRAPER_CONFIG"))
    ap.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    ap.add_argument("--budget", default=os.getenv("WMSCRAPER_BUDGET"), help="NAME:TOTAL persistent total request cap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--location", required=True)
    r.add_argument("--run-id")
    r.add_argument("--categories", help="comma-separated subset (demo)")
    r.add_argument("--limit", type=int, default=0, help="stop after N unique records (demo)")
    r.add_argument("--demo", action="store_true")
    r.add_argument("--max-requests", type=int, default=0, help="safety cap on paid provider requests for this run")
    r.add_argument("--fresh", action="store_true", help="start a new run instead of resuming an open (aborted) run")
    r.add_argument("--refresh-product-pages", action="store_true", help="re-fetch every product page (no UPC reuse)")
    sub.add_parser("run-all")
    v = sub.add_parser("verify-store")
    v.add_argument("--location", required=True)
    v.add_argument("--max-requests", type=int, default=0, help="safety cap on paid provider requests, retries included")
    sub.add_parser("status")
    sub.add_parser("selfcheck")
    bs = sub.add_parser("budget-status")
    bs.add_argument("--name", required=True)
    sm = sub.add_parser("summary")
    sm.add_argument("--location", required=True)
    sm.add_argument("--run-id")
    va = sub.add_parser("validate")
    va.add_argument("--location", required=True)
    va.add_argument("--run-id", required=True)
    va.add_argument("--previous", help="report.json to treat as the last successful run")
    va.add_argument("--categories", help="comma-separated categories the run covered")
    rf = sub.add_parser("retry-failed")
    rf.add_argument("--location", required=True)
    rf.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    s = load_settings(args.config)
    from . import lock
    if args.cmd in LIVE_COMMANDS and not lock.live_held():
        # Exclusive ownership: one requester at a time for every command that can send provider requests
        try:
            with lock.live_lock(build_storage(s)):
                return main(argv)
        except lock.LockError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 3
    if os.getenv("WMSCRAPER_FETCH_PROVIDER"):  # chosen at deployment (Key Vault holds the matching credential)
        s.raw.setdefault("fetch", {})["provider"] = os.environ["WMSCRAPER_FETCH_PROVIDER"]
    if args.budget:
        from .budget import parse_spec

        parse_spec(args.budget)  # validate early
        s.raw.setdefault("fetch", {})["total_budget"] = args.budget
    from .fetch import FetchError
    from .lock import LockError

    handlers = {"run": cmd_run, "run-all": cmd_run_all, "verify-store": cmd_verify_store,
            "summary": cmd_summary, "status": cmd_status, "selfcheck": cmd_selfcheck,
            "budget-status": cmd_budget_status, "retry-failed": cmd_retry_failed, "validate": cmd_validate}
    try:
        return handlers[args.cmd](args, s)
    except (FetchError, LockError, KeyError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
