"""Command line.

  python -m mscraper verify-store --location <key>
  python -m mscraper run --location <key> [--categories "Dairy,Meat"] [--limit 100] [--resume] [--max-requests N]
  python -m mscraper run-all                       # every enabled location (used by the Azure scheduled job)
  python -m mscraper summary --location <key> [--run <run_id>]
  python -m mscraper probe --location <key> [--query Batteries]   # live paging / brand-filter probe with evidence
  python -m mscraper bounded-test test1|test2      # the agreed bounded live tests, total request cap enforced
  python -m mscraper budget-status [--name test1]  # requests used / remaining per bounded test
  python -m mscraper selfcheck                     # 0 provider requests: credentials present, blob + state write/read

  --budget NAME:TOTAL (or env MSCRAPER_BUDGET) puts any command under a TOTAL request cap that persists in the state
  directory across commands, retries, resumes and job executions (see budget.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from . import logging_setup
from .budget import TotalBudget, parse_spec
from .config import load_settings
from .fetch import FetchError
from .lock import LockError, run_lock
from .runner import Runner
from .storage import build_storage


def _state_dir(settings) -> Path:
    d = Path(os.getenv("MSCRAPER_STATE_DIR") or settings.get("state_dir", "state"))
    return d if d.is_absolute() else Path(settings.get("_base_dir")) / d


def _latest_unfinished(state_dir: Path, key: str) -> str | None:
    import sqlite3

    runs = sorted((state_dir / key / "runs").glob("*/checkpoint.sqlite"), reverse=True)
    for ck in runs:
        db = sqlite3.connect(ck)
        try:
            row = db.execute("SELECT v FROM meta WHERE k='final_status'").fetchone()
        finally:
            db.close()
        if not row:
            return ck.parent.name
    return None


def _total_budget(args, settings, command: str):
    spec = getattr(args, "budget", None) or os.getenv("MSCRAPER_BUDGET")
    if not spec:
        return None
    name, total = parse_spec(spec)
    return TotalBudget(_state_dir(settings) / "_budgets", name, total, command=command)


PROVIDER_ENV = {"oxylabs_kroger": ("OXYLABS_WEBAPI_KEY",), "oxylabs_realtime": ("OXYLABS_USERNAME", "OXYLABS_PASSWORD")}


def cmd_selfcheck(settings) -> dict:
    """Deployment check without any provider request: Key Vault-backed credentials reached the process (names
    only, never values), and the managed identity can write and read back a blob in the designated container; the
    state share (persistent request budgets) is writable."""
    import secrets
    from datetime import datetime, timezone

    from .version import version_info

    provider = os.getenv("MSCRAPER_FETCH_PROVIDER") or settings.get("fetch.provider", "oxylabs_kroger")
    out = {**version_info(), "provider": provider, "provider_requests": 0,
           "credentials_present": {k: bool(os.getenv(k)) for k in PROVIDER_ENV.get(provider, ())}}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    token = secrets.token_hex(16).encode()
    try:
        st = build_storage(settings)
        key = f"_selfcheck/{ts}.txt"
        st.put_bytes(key, token)
        out["blob"] = {"backend": type(st).__name__, "key": key, "write": True, "read_back_matches": st.get_bytes(key) == token}
    except Exception as exc:  # e.g. role assignment missing or not yet propagated
        out["blob"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    try:
        f = _state_dir(settings) / "_selfcheck" / f"{ts}.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(token)
        out["state_dir"] = {"path": str(f), "write": True, "read_back_matches": f.read_bytes() == token}
    except Exception as exc:
        out["state_dir"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    out["ok"] = (all(out["credentials_present"].values()) and out["blob"].get("read_back_matches") is True
                 and out["state_dir"].get("read_back_matches") is True)
    return out


# The bounded live tests proposed to the client. Each step has its own cap; the test's total cap is enforced on top
# of them by a persistent TotalBudget, so re-running a test can never exceed its total.
BOUNDED_TESTS = {
    "test1": {"total": 19, "steps": [
        ["verify-store", "--location", "marianos-544-crystal-lake", "--max-requests", "2"],
        ["verify-store", "--location", "marianos-502-vernon-hills", "--max-requests", "2"],
        ["probe", "--location", "marianos-544-crystal-lake", "--query", "Batteries", "--max-requests", "15"]]},
    "test2": {"total": 300, "steps": [
        ["run", "--location", "marianos-544-crystal-lake", "--categories", "Batteries,Light Bulbs",
         "--max-requests", "300", "--no-publish", "--resume"]]},
}


def cmd_run(args, settings, loc_key: str) -> dict:
    loc = settings.location(loc_key)
    storage = build_storage(settings)
    state = _state_dir(settings)
    run_id = args.run or (_latest_unfinished(state, loc.key) if args.resume else None)
    if args.max_requests:
        settings.raw.setdefault("fetch", {})["max_requests_per_run"] = args.max_requests
    cats = [c.strip() for c in args.categories.split(",")] if getattr(args, "categories", None) else None
    with run_lock(storage, loc.key):
        runner = Runner(settings, loc, storage, state, run_id=run_id, categories=cats, limit_per_category=args.limit or 0)
        runner.fetcher.total_budget = _total_budget(args, settings, f"run {loc.key}")
        logging_setup.setup(args.log_level, str(runner.dir / "run.log"))
        return asyncio.run(runner.run(publish=not args.no_publish))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mscraper")
    ap.add_argument("--config", default=None)
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--budget", default=None, help="NAME:TOTAL persistent total request cap (env MSCRAPER_BUDGET)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify-store")
    v.add_argument("--location", required=True)
    v.add_argument("--max-requests", type=int, default=2, help="hard cap on provider requests (retries included)")
    r = sub.add_parser("run")
    r.add_argument("--location", required=True)
    r.add_argument("--categories", default="")
    r.add_argument("--limit", type=int, default=0, help="max records per category (demo / smoke runs)")
    r.add_argument("--resume", action="store_true", help="continue the latest unfinished run")
    r.add_argument("--run", default=None, help="continue a specific run id")
    r.add_argument("--max-requests", type=int, default=0)
    r.add_argument("--no-publish", action="store_true")
    a = sub.add_parser("run-all")
    a.add_argument("--resume", action="store_true", default=True)
    pr = sub.add_parser("probe", help="~6-12 live requests: page 2 / JS paging / brand-filter behaviour, with evidence")
    pr.add_argument("--location", required=True)
    pr.add_argument("--query", default="Batteries")
    pr.add_argument("--max-requests", type=int, default=15, help="hard cap on provider requests for this probe")
    bt = sub.add_parser("bounded-test", help="run an agreed bounded live test under its enforced total request cap")
    bt.add_argument("test", choices=sorted(BOUNDED_TESTS))
    sub.add_parser("selfcheck", help="0 provider requests: credentials present, blob + state write/read")
    bs = sub.add_parser("budget-status")
    bs.add_argument("--name", default=None)
    s = sub.add_parser("summary")
    s.add_argument("--location", required=True)
    s.add_argument("--run", default=None)
    args = ap.parse_args(argv)
    try:  # local runs: read .env; in Azure the values come from Key Vault-backed env vars
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    settings = load_settings(args.config)
    logging_setup.setup(args.log_level)

    if args.cmd == "verify-store":
        loc = settings.location(args.location)
        runner = Runner(settings, loc, build_storage(settings), _state_dir(settings) / "_verify")
        runner.fetcher.budget = args.max_requests
        runner.fetcher.retries = max(0, args.max_requests - 1)
        runner.fetcher.total_budget = _total_budget(args, settings, f"verify-store {loc.key}")

        async def go():
            await runner.fetcher.start()
            try:
                return await runner.verify_store()
            finally:
                await runner.fetcher.close()

        res = asyncio.run(go())
        print(json.dumps(res, indent=2))
        return 0 if res["verified"] else 2

    if args.cmd == "probe":
        from datetime import datetime, timezone

        from .fetch import build_fetcher
        from .probe import run_probe

        loc = settings.location(args.location)
        out = _state_dir(settings) / loc.key / "probes" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        f = build_fetcher(settings, loc)
        f.budget = args.max_requests          # retries count too: the probe can never exceed this many requests
        f.retries = 1
        f.total_budget = _total_budget(args, settings, f"probe {loc.key}")

        async def go():
            await f.start()
            try:
                return await run_probe(f, settings, loc, out, args.query, args.max_requests)
            finally:
                await f.close()

        rep = asyncio.run(go())
        print(json.dumps({"dir": str(out), "findings": rep["findings"], "requests": rep["fetch_stats"]}, indent=2))
        return 0

    if args.cmd == "run":
        try:
            res = cmd_run(args, settings, args.location)
        except LockError as exc:
            print(f"skipped: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(res, indent=2))
        return 0 if res["status"] in ("published", "valid_not_published_demo", "valid_not_published") else 1

    if args.cmd == "run-all":
        rc = 0
        for loc in settings.locations:
            if not loc.enabled:
                continue
            ns = argparse.Namespace(run=None, resume=True, max_requests=0, categories="", limit=0, no_publish=False,
                                    log_level=args.log_level)
            try:
                res = cmd_run(ns, settings, loc.key)
                print(json.dumps(res))
                rc |= 0 if res["status"] == "published" else 1
            except LockError as exc:
                print(f"{loc.key}: skipped: {exc}", file=sys.stderr)
        return rc

    if args.cmd == "bounded-test":
        plan = BOUNDED_TESTS[args.test]
        spec = f"{args.test}:{plan['total']}"
        rc = 0
        for step in plan["steps"]:
            b = _total_budget(argparse.Namespace(budget=spec), settings, "")
            if b.remaining <= 0:
                print(f"{args.test}: total of {b.total} requests used up – step not started: {' '.join(step)}")
                rc = rc or 4
                break
            print(f"{args.test}: {' '.join(step)}  (total used {b.used}/{b.total})", flush=True)
            try:
                rc = main((["--config", args.config] if args.config else []) + ["--log-level", args.log_level,
                          "--budget", spec] + step) or rc
            except FetchError as exc:   # the total cap stops a step part-way: report it, never send more
                print(f"{args.test}: step stopped: {exc}")
                rc = rc or 4
        b = _total_budget(argparse.Namespace(budget=spec), settings, "")
        print(json.dumps({"test": args.test, "exit_code": rc, "budget": b.summary()}, indent=2))
        return rc

    if args.cmd == "selfcheck":
        res = cmd_selfcheck(settings)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    if args.cmd == "budget-status":
        d = _state_dir(settings) / "_budgets"
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []
        rows = [r for r in rows if not args.name or r["name"] == args.name]
        print(json.dumps([{**r, "remaining": int(r["total"]) - int(r["used"])} for r in rows], indent=2))
        return 0

    if args.cmd == "summary":
        state = _state_dir(settings) / args.location / "runs"
        run = args.run or sorted(p.name for p in state.iterdir() if p.is_dir())[-1]
        rep = json.loads((state / run / "report.json").read_text(encoding="utf-8"))
        keys = ("run_id", "runtime_seconds", "total_unique_records", "duplicate_records_in_output", "count_by_category",
                "excluded", "store_checks_during_run", "validation")
        print(json.dumps({k: rep.get(k) for k in keys}, indent=2))
        return 0
    return 1
