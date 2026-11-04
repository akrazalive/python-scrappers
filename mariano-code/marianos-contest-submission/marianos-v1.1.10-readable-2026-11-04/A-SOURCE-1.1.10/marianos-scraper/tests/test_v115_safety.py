"""v1.1.5 – client review of 27 Oct: stop rule, exclusive ownership, lease loss, checkpoint integrity (offline)."""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import FIX, PAGES, ROOT

from mscraper import cli, lock
from mscraper.budget import BudgetError, TotalBudget
from mscraper.checkpoint import Checkpoint, CheckpointError
from mscraper.config import Category, Location, load_settings
from mscraper.fetch import FetchError, FixtureFetcher
from mscraper.lock import BlobLeaseLock, FileLock, LockLost
from mscraper.runner import Runner
from mscraper.storage import LocalStorage

CFG = str(ROOT / "config" / "settings.yaml")
TESTS = Path(__file__).resolve().parent


# ---------------------------------------------------------------- helpers
def _fast(monkeypatch):
    monkeypatch.setattr("mscraper.fetch.Fetcher._pace", lambda self: asyncio.sleep(0))
    monkeypatch.setattr("mscraper.fetch.random.uniform", lambda a, b: 0)


def _serve(monkeypatch, mapping):
    """CLI runs with the fixture provider serving `mapping` (url substring -> saved page)."""
    calls = []
    orig = FixtureFetcher.__init__

    def init(self, settings, location, fixtures=None, root=None):
        orig(self, settings, location, fixtures=dict(mapping), root=str(FIX))
        self.calls = calls
    monkeypatch.setattr(FixtureFetcher, "__init__", init)
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "fixture")
    return calls


def _budget_file(tmp_path, name="test1"):
    return json.loads((tmp_path / "state" / "_budgets" / f"{name}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 1. stop rule
def test_failed_first_store_check_stops_bounded_test_before_any_other_step(tmp_path, monkeypatch, capsys):
    """Crystal Lake verify-store gets a response for store 53100539 (wrong store): step 1 fails, steps 2 and 3
    (Vernon Hills verify-store, probe) are never started and no further provider request is made."""
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    _fast(monkeypatch)
    calls = _serve(monkeypatch, {"/search?query=milk": "search_milk_store539.html.gz"})
    rc = cli.main(["--config", CFG, "bounded-test", "test1"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "step 1 failed (exit 2) – later steps NOT started" in out
    assert "step 2" not in out and "step 3" not in out
    assert len(calls) == 1                                   # the one wrong-store response, nothing after it
    assert _budget_file(tmp_path)["used"] == 1
    ledger = (tmp_path / "state" / "_budgets" / "test1.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["store"] for x in ledger] == ["53100544"]


def test_terminal_provider_errors_are_not_retried_and_stop_the_test(tmp_path, monkeypatch, capsys):
    """A rejected credential (HTTP 401) is terminal: one request, no retry, later steps not started."""
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    _fast(monkeypatch)
    calls = _serve(monkeypatch, {})

    async def unauthorized(self, url, render_js):
        self.calls.append(url)
        raise FetchError("provider authentication failed (HTTP 401)", "auth")
    monkeypatch.setattr(FixtureFetcher, "_fetch_once", unauthorized)
    rc = cli.main(["--config", CFG, "bounded-test", "test1"])
    out = capsys.readouterr().out
    assert rc == 4 and "step 1 stopped (auth)" in out and "step 2" not in out
    assert len(calls) == 1 and _budget_file(tmp_path)["used"] == 1


# ---------------------------------------------------------------- 2. exclusive ownership, overlap, persistence
def test_overlapping_execution_is_refused_and_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    _fast(monkeypatch)
    calls = _serve(monkeypatch, {"/search?query=milk": "search_milk_store544.html.gz"})
    settings = load_settings(CFG)
    from mscraper.storage import build_storage
    other = FileLock(build_storage(settings).local_path("_live/.run.lock"))    # another execution holds the lease
    with other:
        for cmd in (["bounded-test", "test1"], ["verify-store", "--location", "marianos-502-vernon-hills"],
                    ["probe", "--location", "marianos-544-crystal-lake"]):
            assert cli.main(["--config", CFG] + cmd) == 3
    assert "refused" in capsys.readouterr().err
    assert calls == [] and not (tmp_path / "state" / "_budgets" / "test1.json").exists()


def test_budget_needs_the_live_lock_and_survives_restart(tmp_path):
    with pytest.raises(BudgetError, match="live lock"):
        TotalBudget(tmp_path, "test1", 19)                    # no exclusive ownership -> refused
    with lock.live_lock(LocalStorage(tmp_path / "locks")):
        b = TotalBudget(tmp_path, "test1", 19)
        b.take("u1")
        b.take("u2")
    with lock.live_lock(LocalStorage(tmp_path / "locks")):     # a restarted execution: same identity, same count
        again = TotalBudget(tmp_path, "test1", 19)
        assert (again.used, again.remaining) == (2, 17)


def test_existing_test1_identity_from_azure_is_kept_with_19_remaining(tmp_path, live):
    """The exact state file that is on the Azure share since 27 Oct (used 0/19, no ledger) opens unchanged."""
    (tmp_path / "test1.json").write_text(json.dumps({"name": "test1", "total": 19, "used": 0,
                                                     "created_at": "2026-10-27T04:09:54+00:00",
                                                     "updated_at": "2026-10-27T04:09:54+00:00"}), encoding="utf-8")
    b = TotalBudget(tmp_path, "test1", 19)
    assert (b.used, b.remaining, b.state["created_at"]) == (0, 19, "2026-10-27T04:09:54+00:00")
    with pytest.raises(ValueError, match="never raised"):
        TotalBudget(tmp_path, "test1", 20)


def test_budget_state_is_never_cached_between_two_holders(tmp_path, live):
    a, b = TotalBudget(tmp_path, "one", 1), TotalBudget(tmp_path, "one", 1)
    a.take("u")
    with pytest.raises(FetchError, match="used up"):           # b re-reads the file: no second reservation
        b.take("u")
    assert TotalBudget(tmp_path, "one", 1).used == 1


@pytest.mark.parametrize("damage, msg", [
    ("delete_state", "state file is missing"),
    ("truncate_ledger", "ledger has 1 lines but state says used=2"),
    ("invalid_state", "unreadable/invalid"),
    ("used_over_total", "outside"),
])
def test_inconsistent_budget_fails_closed(tmp_path, live, damage, msg):
    b = TotalBudget(tmp_path, "t", 3)
    b.take("u1")
    b.take("u2")
    st, lg = tmp_path / "t.json", tmp_path / "t.jsonl"
    if damage == "delete_state":
        st.unlink()
    elif damage == "truncate_ledger":
        lg.write_text(lg.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    elif damage == "invalid_state":
        st.write_text("{not json", encoding="utf-8")
    else:
        st.write_text(json.dumps({"name": "t", "total": 3, "used": 9}), encoding="utf-8")
    with pytest.raises(BudgetError, match=msg):
        TotalBudget(tmp_path, "t", 3)


def test_crash_between_ledger_and_state_counts_the_request_as_used(tmp_path, live):
    b = TotalBudget(tmp_path, "t", 3)
    b.take("u1")
    with (tmp_path / "t.jsonl").open("a", encoding="utf-8") as f:   # ledger line written, then the process died
        f.write(json.dumps({"n": 2, "url": "u2"}) + "\n")
    again = TotalBudget(tmp_path, "t", 3)
    assert again.used == 2 and again.state.get("repaired_at")


# ---------------------------------------------------------------- 3. lease loss
class _Lease:
    def __init__(self):
        self.renewals = 0

    def renew(self):
        self.renewals += 1
        raise RuntimeError("LeaseIdMismatchWithLeaseOperation")

    def release(self):
        pass


class _Blob:
    blob_name = "_live/.run.lock"

    def exists(self):
        return True

    def acquire_lease(self, lease_duration):
        self.lease = _Lease()
        return self.lease


class _Container:
    def get_blob_client(self, key):
        return _Blob()


def test_lease_loss_stops_requests_checkpoint_writes_and_publication(settings, location, tmp_path):
    lk = BlobLeaseLock(_Container(), "_live/.run.lock", lease_seconds=0.15)
    ck = Checkpoint(tmp_path / "run" / "checkpoint.sqlite")
    store = LocalStorage(tmp_path / "out")
    f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    with lk:
        ck.set("before", 1)                                   # works while the lease is held
        deadline = time.time() + 5
        while not lk.lost and time.time() < deadline:         # renewal fails -> lease marked lost
            time.sleep(0.02)
        assert lk.lost
        with pytest.raises(LockLost):
            lock.check_active()
        with pytest.raises(FetchError) as e:                  # no further provider request
            asyncio.run(f.get("https://www.marianos.com/search?query=milk"))
        assert e.value.kind == "lock" and f.calls == []
        with pytest.raises(LockLost):                         # no checkpoint write (rolled back)
            ck.set("after", 2)
        with pytest.raises(LockLost):                         # nothing published
            store.publish("test-544", "r1", [{"upc": "1"}], {"ok": True})
    assert ck.get("before") == 1 and ck.get("after") is None
    assert not (tmp_path / "out" / "test-544" / "latest").exists()


# ---------------------------------------------------------------- 4. checkpoint integrity / hard-kill restart
def make_settings():
    s = load_settings(ROOT / "config" / "settings.yaml")
    s.raw["crawl"]["max_pages_per_query"] = 3
    s.raw["crawl"]["skip_shelf_patterns"] = [r"^(?!Beef$|Steaks$|Frozen Meat$|Organic Meat$).*"]
    s.raw["fetch"]["min_page_bytes"] = 1000
    s.raw["crawl"]["brand_slices"] = False
    s.categories = [Category("Meat", "https://www.marianos.com/d/meat", "Category + ALL subcategories"),
                    Category("Coupons", "https://www.marianos.com/savings/cl/coupons/", "Category + ALL subcategories")]
    return s


def make_location():
    return Location(key="test-544", store_id="53100544", zipcode="60014", expected_address="105 Northwest Hwy",
                    canary_query="milk", canary_upcs=("0001111050438",))


class KillingFetcher(FixtureFetcher):
    """Hard kill (no finally blocks, no flush) on the N-th provider response – like SIGKILL / a lost replica."""

    def __init__(self, *a, kill_after=0, **kw):
        super().__init__(*a, **kw)
        self.kill_after = kill_after

    async def _fetch_once(self, url, render_js):
        if self.kill_after and len(self.calls) >= self.kill_after:
            os._exit(137)
        return await super()._fetch_once(url, render_js)


def crash_child(state_dir: str, out_dir: str, run_id: str, kill_after: int):
    s, loc = make_settings(), make_location()
    f = KillingFetcher(s, loc, fixtures=dict(PAGES), root=str(FIX), kill_after=kill_after)
    asyncio.run(Runner(s, loc, LocalStorage(Path(out_dir)), Path(state_dir), run_id=run_id, fetcher=f).run())


def _ids(storage_root):
    recs = json.loads((Path(storage_root) / "test-544" / "latest" / "records.json").read_text(encoding="utf-8"))
    return [r["upc"] for r in recs]


def test_snapshot_checkpoint_survives_hard_kill_and_resumes_without_loss_or_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCRAPER_CHECKPOINT_MODE", "snapshot")
    monkeypatch.setenv("MSCRAPER_SNAPSHOT_SECONDS", "0")
    # reference: the same run without interruption
    monkeypatch.setenv("MSCRAPER_LOCAL_WORK", str(tmp_path / "work-ref"))
    s, loc = make_settings(), make_location()
    ref = FixtureFetcher(s, loc, fixtures=dict(PAGES), root=str(FIX))
    res_ref = asyncio.run(Runner(s, loc, LocalStorage(tmp_path / "out-ref"), tmp_path / "state-ref",
                                 run_id="20261028T000000Z-ref000", fetcher=ref).run())
    assert res_ref["status"] == "published"
    # interrupted: a separate process is hard-killed on its 6th provider response
    run_id, state = "20261028T000000Z-kill00", tmp_path / "state"
    env = {**os.environ, "MSCRAPER_LOCAL_WORK": str(tmp_path / "work-container1"),
           "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(TESTS)])}
    code = ("import sys, test_v115_safety as t; "
            f"t.crash_child({str(state)!r}, {str(tmp_path / 'out')!r}, {run_id!r}, 6)")
    p = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(TESTS), capture_output=True, text=True)
    assert p.returncode == 137, p.stderr[-2000:]
    run_dir = state / "test-544" / "runs" / run_id
    m = json.loads((run_dir / "checkpoint.manifest.json").read_text(encoding="utf-8"))
    assert m["seq"] >= 1 and m["integrity"] == "ok"
    assert not (run_dir / "checkpoint.sqlite").exists()       # SQLite never ran on the (SMB) state directory
    # resume in a NEW container: empty local working directory, everything comes from the share
    monkeypatch.setenv("MSCRAPER_LOCAL_WORK", str(tmp_path / "work-container2"))
    f2 = FixtureFetcher(s, loc, fixtures=dict(PAGES), root=str(FIX))
    r2 = Runner(s, loc, LocalStorage(tmp_path / "out"), state, run_id=run_id, fetcher=f2)
    assert r2.ck.get("started_at")                            # restored state, not a fresh run
    res = asyncio.run(r2.run())
    assert res["status"] == "published", res["errors"]
    ids = _ids(tmp_path / "out")
    assert len(ids) == len(set(ids)) and sorted(ids) == sorted(_ids(tmp_path / "out-ref"))
    assert r2.ck.get("resumes") == 1
    assert len(f2.calls) < len(ref.calls)                    # committed work before the kill was not refetched


def test_corrupt_or_inconsistent_snapshot_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCRAPER_LOCAL_WORK", str(tmp_path / "work"))
    path = tmp_path / "run" / "checkpoint.sqlite"
    ck = Checkpoint(path, mode="snapshot", snapshot_seconds=0)
    ck.set("k", 1)
    ck.close()
    m = json.loads((path.parent / "checkpoint.manifest.json").read_text(encoding="utf-8"))
    snap = path.parent / m["file"]
    good = snap.read_bytes()
    # a crash after writing a NEWER snapshot but before the manifest switch: the committed snapshot is still used
    (path.parent / f"checkpoint.snap-{m['seq'] + 1:06d}.sqlite").write_bytes(b"partial")
    again = Checkpoint(path, mode="snapshot")
    assert again.get("k") == 1
    again.close()
    mid = len(good) // 2
    snap.write_bytes(good[:mid] + bytes(b ^ 0xFF for b in good[mid:mid + 64]) + good[mid + 64:])  # damaged bytes
    with pytest.raises(CheckpointError, match="SHA-256"):
        Checkpoint(path, mode="snapshot")
    snap.unlink()                                             # snapshot missing
    with pytest.raises(CheckpointError, match="missing"):
        Checkpoint(path, mode="snapshot")
    (path.parent / "checkpoint.manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(CheckpointError, match="unreadable"):
        Checkpoint(path, mode="snapshot")


def test_snapshot_mode_refuses_an_unmanifested_direct_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCRAPER_LOCAL_WORK", str(tmp_path / "work"))
    path = tmp_path / "run" / "checkpoint.sqlite"
    Checkpoint(path, mode="direct").set("k", 1)
    with pytest.raises(CheckpointError, match="no snapshot manifest"):
        Checkpoint(path, mode="snapshot")


def test_provider_errors_are_classified_terminal_or_retryable():
    from mscraper.fetch import provider_error

    assert provider_error(401, "").kind == "auth" and provider_error(401, "").terminal
    assert provider_error(403, "").kind == "auth"
    assert provider_error(400, "unsupported source").kind == "compat" and provider_error(422, "").terminal
    assert provider_error(429, "").kind == "http" and not provider_error(429, "").terminal
    assert not provider_error(503, "").terminal


def test_real_provider_adapter_refuses_to_start_without_the_live_lock(settings, location, monkeypatch):
    from mscraper.fetch import OxylabsRealtimeFetcher

    monkeypatch.setenv("OXYLABS_USERNAME", "u")
    monkeypatch.setenv("OXYLABS_PASSWORD", "p")
    with pytest.raises(FetchError) as e:
        asyncio.run(OxylabsRealtimeFetcher(settings, location).start())
    assert e.value.kind == "lock"


def test_classic_payloads_are_the_documented_routes():
    """Classic API: search pages -> documented kroger_search with store localisation; other pages -> url alone."""
    from mscraper.fetch import realtime_payload

    s, loc = load_settings(ROOT / "config" / "settings.yaml"), make_location()
    assert realtime_payload(s, loc, "https://www.marianos.com/search?query=Light%20Bulbs&searchType=default_search") == {
        "source": "kroger_search", "query": "Light Bulbs", "store_id": "53100544", "fulfillment_type": "in_store"}
    assert realtime_payload(s, loc, "https://www.marianos.com/d/meat") == {"url": "https://www.marianos.com/d/meat"}
