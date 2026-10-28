"""1.1.8 – client review of 27/28 Oct: atomic exclusive budget, first-failure canary stop, fulfillment + price
verification, archive-before-validation, terminal errors, the documented --categories command (offline only)."""
import asyncio
import json
import time
from pathlib import Path

import pytest
import yaml
from conftest import STORE, ZIP, page

from wmscraper import lock
from wmscraper.budget import BudgetError, TotalBudget
from wmscraper.cli import main
from wmscraper.config import load_settings
from wmscraper.fetch import FetchError, classic_payload, provider_error
from wmscraper.fetch.base import FixtureFetcher
from wmscraper.lock import BlobLeaseLock, FileLock, LockLost, live_lock
from wmscraper.storage import build_storage


# ---------------------------------------------------------------- helpers
def _storage(site):
    return build_storage(load_settings(str(site)))


def canary_product(i, *, store=STORE, intent="PICKUP", ftype="STORE", pickup_store=None, price="$2.98", summary=None):
    pickup_store = store if pickup_store is None else pickup_store
    return page({"props": {"pageProps": {"initialData": {"data": {"product": {
        "usItemId": str(i), "upc": f"0000000{i}", "brand": "Acme", "sellerId": "F55CDC31AB754BB68FE0B39041159D63",
        "sellerName": "Walmart.com", "priceInfo": {"currentPrice": {"priceString": price}},
        "fulfillmentSummary": [{"fulfillment": "PICKUP", "storeId": store}] if summary is None else summary,
        "fulfillmentType": ftype,
        "location": {"storeIds": [store], "intent": intent, "postalCode": ZIP, "pickupLocation": {"storeId": pickup_store}}},
        "idml": {"specifications": []}}}}}})


def with_canaries(site, pages: dict):
    """Configure the test store's canary items and serve the given product pages for them."""
    cfg = Path(site).parent
    fx = Path(load_settings(str(site)).get("fetch.fixture_dir"))
    mapping = json.loads((fx / "map.json").read_text(encoding="utf-8"))
    for item_id, html in pages.items():
        (fx / f"canary{item_id}.html").write_text(html, encoding="utf-8")
        mapping[f"https://www.walmart.com/ip/{item_id}"] = f"canary{item_id}.html"
    (fx / "map.json").write_text(json.dumps(mapping), encoding="utf-8")
    locs = yaml.safe_load((cfg / "locations.yaml").read_text(encoding="utf-8"))
    locs["locations"][0]["canary_items"] = list(pages)
    (cfg / "locations.yaml").write_text(yaml.safe_dump(locs), encoding="utf-8")


def ledger_urls(site, name="probe"):
    raw = _storage(site).get_bytes(f"_budgets/{name}.jsonl")
    return [json.loads(x)["url"] for x in raw.decode().splitlines()] if raw else []


def probe(site):
    return main(["--config", str(site), "--budget", "probe:10", "verify-store", "--location", "test-store",
                 "--max-requests", "10"])


# ---------------------------------------------------------------- 2. stop at the first failed canary
def _verify_result(out: str) -> dict:
    return json.loads(out[out.index('{\n  "verified"'):])


def _canary_state(site) -> dict:
    from wmscraper.checkpoint import Checkpoint

    run = next(p for p in (_storage(site).root / "test-store" / "runs").iterdir() if p.name.startswith("verify-"))
    return Checkpoint(run / "checkpoint.sqlite").get("canary")["start"]


def test_first_wrong_store_canary_stops_before_the_second_request(site, capsys):
    with_canaries(site, {"901": canary_product(901, store="4376"), "902": canary_product(902)})
    assert probe(site) != 0
    err = capsys.readouterr().err
    assert "canary failed at start" in err and "1 canary item(s) not requested" in err
    assert ledger_urls(site) == [f"https://www.walmart.com/store/{STORE}", "https://www.walmart.com/ip/901"]
    state = _canary_state(site)
    assert state["ok"] is False and state["not_requested"] == ["902"]
    assert [c["item"] for c in state["checked"]] == ["901"] and "selected pickup store 4376" in state["detail"][0]


def test_verify_store_returns_failure_when_any_canary_fails(site, capsys):
    with_canaries(site, {"901": canary_product(901), "902": canary_product(902, pickup_store="4376")})
    rc = probe(site)
    err = capsys.readouterr().err
    assert rc != 0 and "canary failed at start" in err and "902" in err
    assert ledger_urls(site)[-1] == "https://www.walmart.com/ip/902"


# ---------------------------------------------------------------- 3. fulfillment + price, not just a store id
@pytest.mark.parametrize("kw, why", [
    ({"intent": "SHIPPING"}, "intent SHIPPING"),
    ({"ftype": "FC"}, "fulfillmentType FC"),
    ({"summary": [{"fulfillment": "DELIVERY", "storeId": STORE}]}, "no PICKUP option"),
    ({"price": ""}, "no current price"),
])
def test_configured_store_id_alone_is_not_enough(site, capsys, kw, why):
    with_canaries(site, {"901": canary_product(901, **kw)})
    assert probe(site) != 0
    assert why in capsys.readouterr().err


def test_correct_store_fulfillment_and_price_pass(site, capsys):
    with_canaries(site, {"901": canary_product(901), "902": canary_product(902)})
    assert probe(site) == 0
    res = _verify_result(capsys.readouterr().out)
    assert res["verified"] is True and res["canary"]["start"]["ok"] is True
    assert [c["ok"] for c in res["canary"]["start"]["checked"]] == [True, True]
    assert len(ledger_urls(site)) == 3


# ---------------------------------------------------------------- 4. every canary response archived before validation
def test_canary_responses_archived_with_hash_and_context_even_when_failing(site, capsys):
    with_canaries(site, {"901": canary_product(901, store="4376")})
    probe(site)
    st = _storage(site)
    runs = [p for p in (st.root / "test-store" / "runs").iterdir() if p.name.startswith("verify-")]
    index = json.loads((runs[0] / "raw" / "index.json").read_text(encoding="utf-8"))
    kinds = [e["kind"] for e in index]
    assert kinds == ["store", "canary"]
    can = index[1]
    assert can["url"] == "https://www.walmart.com/ip/901" and len(can["sha256"]) == 64
    assert (runs[0] / "raw" / can["file"]).exists()
    assert any(c.get("value") == "4376" for c in can["store_context"])           # the returned (wrong) context


# ---------------------------------------------------------------- terminal vs retryable
def test_auth_failure_is_terminal_and_not_retried(site, monkeypatch, capsys):
    calls = []

    async def unauthorized(self, url):
        calls.append(url)
        raise provider_error(401, "")
    monkeypatch.setattr(FixtureFetcher, "_fetch_once", unauthorized)
    s = load_settings(str(site))
    s.raw["fetch"]["max_retries"] = 4
    with live_lock(_storage(site)):
        f = FixtureFetcher(s, s.location("test-store"))
        with pytest.raises(FetchError) as e:
            asyncio.run(f.get(f"https://www.walmart.com/store/{STORE}"))
    assert e.value.kind == "auth" and len(calls) == 1
    assert provider_error(400, "").kind == "compat" and provider_error(429, "").kind == "http"


# ---------------------------------------------------------------- 1. budget: exclusive, atomic, fail closed
def test_two_holders_of_a_one_request_budget_cannot_both_reserve(site):
    st = _storage(site)
    with live_lock(st):
        a, b = TotalBudget(st, "one", 1), TotalBudget(st, "one", 1)
        stale_state, stale_etag = b._load()                # b read the state before a reserved
        a.take("u")
        with pytest.raises(FetchError, match="used up"):  # b re-reads: nothing left
            b.take("u")
        with pytest.raises(BudgetError, match="concurrent change"):   # even a write based on the stale read loses
            b._write({**stale_state, "used": 1}, stale_etag)
        assert TotalBudget(st, "one", 1).used == 1


def test_overlapping_execution_is_refused_before_any_request(site, capsys):
    other = FileLock(_storage(site).local_path("_live/.run.lock"))
    with other:
        assert probe(site) == 3
    assert "refused" in capsys.readouterr().err
    assert ledger_urls(site) == [] and _storage(site).get_bytes("_budgets/probe.json") is None


def test_budget_requires_the_live_lock(site):
    with pytest.raises(BudgetError, match="live lock"):
        TotalBudget(_storage(site), "probe", 10)


def test_deleted_state_with_remaining_ledger_never_resets_to_zero(site):
    st = _storage(site)
    with live_lock(st):
        b = TotalBudget(st, "probe", 10)
        b.take("u1")
        (st.root / "_budgets" / "probe.json").unlink()
        with pytest.raises(BudgetError, match="refusing to reset"):
            TotalBudget(st, "probe", 10)


@pytest.mark.parametrize("damage, msg", [("invalid", "unreadable/invalid"), ("over", "outside"),
                                         ("short_ledger", "ledger has 1 lines")])
def test_inconsistent_state_fails_closed(site, damage, msg):
    st = _storage(site)
    with live_lock(st):
        b = TotalBudget(st, "t", 5)
        b.take("u1")
        b.take("u2")
        p, lg = st.root / "_budgets" / "t.json", st.root / "_budgets" / "t.jsonl"
        if damage == "invalid":
            p.write_text("{oops", encoding="utf-8")
        elif damage == "over":
            p.write_text(json.dumps({"name": "t", "total": 5, "used": 9}), encoding="utf-8")
        else:
            lg.write_text(lg.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        with pytest.raises(BudgetError, match=msg):
            TotalBudget(st, "t", 5)


def test_existing_azure_probe_identity_keeps_its_7_remaining(site):
    """Exactly the probe budget in the walmart-scraper container since 27 Oct: used 3 of 10, 3 ledger lines."""
    st = _storage(site)
    st.put_bytes("_budgets/probe.json", json.dumps({"name": "probe", "total": 10, "used": 3,
                                                    "created_at": "2026-10-27T04:10:27+00:00",
                                                    "updated_at": "2026-10-27T04:11:36+00:00"}).encode())
    lines = [{"ts": "2026-10-27T04:10:27+00:00", "n": 1, "store": "100", "url": "https://www.walmart.com/store/100"},
             {"ts": "2026-10-27T04:11:12+00:00", "n": 2, "store": "100", "url": "https://www.walmart.com/ip/10450114"},
             {"ts": "2026-10-27T04:11:36+00:00", "n": 3, "store": "100", "url": "https://www.walmart.com/ip/43436773"}]
    st.put_bytes("_budgets/probe.jsonl", ("\n".join(json.dumps(x) for x in lines) + "\n").encode())
    with live_lock(st):
        b = TotalBudget(st, "probe", 10)
        assert (b.used, b.remaining, b.state["created_at"]) == (3, 7, "2026-10-27T04:10:27+00:00")
        b.take("next")
        assert TotalBudget(st, "probe", 10).used == 4
        assert json.loads(st.get_bytes("_budgets/probe.jsonl").decode().splitlines()[0])["n"] == 1   # history kept


def test_ledger_chunks_keep_rewrites_bounded(site):
    st = _storage(site)
    with live_lock(st):
        b = TotalBudget(st, "big", 450)
        for i in range(410):
            b.take(f"u{i}")
        assert TotalBudget(st, "big", 450).used == 410
    assert st.get_bytes("_budgets/big.jsonl.3").decode().count("\n") == 10


# ---------------------------------------------------------------- lease loss
class _Lease:
    def renew(self):
        raise RuntimeError("LeaseIdMismatchWithLeaseOperation")

    def release(self):
        pass


class _Blob:
    blob_name = "_live/.run.lock"

    def exists(self):
        return True

    def acquire_lease(self, lease_duration):
        return _Lease()


class _Container:
    def get_blob_client(self, key):
        return _Blob()


def test_lease_loss_stops_requests_checkpoint_writes_and_publication(site, tmp_path):
    from wmscraper.checkpoint import Checkpoint

    s = load_settings(str(site))
    st = _storage(site)
    ck = Checkpoint(tmp_path / "ck.sqlite")
    lk = BlobLeaseLock(_Container(), "_live/.run.lock", lease_seconds=0.15)
    calls = []
    with lk:
        deadline = time.time() + 5
        while not lk.lost and time.time() < deadline:
            time.sleep(0.02)
        with pytest.raises(LockLost):
            lock.check_active()
        f = FixtureFetcher(s, s.location("test-store"))
        with pytest.raises(FetchError) as e:
            asyncio.run(f.get(f"https://www.walmart.com/store/{STORE}"))
        assert e.value.kind == "lock"
        with pytest.raises(LockLost):
            ck.set("after", 1)
        with pytest.raises(LockLost):
            st.publish("test-store", "r1", [{"item_id": "1"}], {"ok": True})
    assert ck.get("after") is None and st.get_bytes("test-store/latest/manifest.json") is None


# ---------------------------------------------------------------- 5. documented --categories command
def test_documented_categories_command_runs(site, capsys):
    """README/cli docstring: python -m wmscraper run --location <key> --categories "Food,Pets" --limit 600 --demo
    raised "'NoneType' object is not iterable" in 1.1.7."""
    rc = main(["--config", str(site), "run", "--location", "test-store", "--categories", "Food", "--limit", "600",
               "--demo"])
    assert rc == 0
    assert '"run_id"' in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown categories"):
        main(["--config", str(site), "run", "--location", "test-store", "--categories", "Food,Pets", "--demo"])


# ---------------------------------------------------------------- proposed Classic payload (documented)
def test_classic_payload_uses_the_documented_walmart_product_source_for_product_pages(site):
    s = load_settings(str(site))
    s.raw["fetch"]["oxylabs"] = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config" / "settings.yaml").read_text(encoding="utf-8"))["fetch"]["oxylabs"]
    loc = s.location("test-store")
    body = classic_payload(s, loc, "https://www.walmart.com/ip/10450114")
    assert body == {"source": "walmart_product", "product_id": "10450114", "store_id": loc.store_id,
                    "delivery_zip": loc.zipcode, "fulfillment_type": "pickup"}
    assert classic_payload(s, loc, "https://www.walmart.com/ip/Great-Value-Milk/10450114")["product_id"] == "10450114"
    store = classic_payload(s, loc, f"https://www.walmart.com/store/{loc.store_id}")
    assert store["source"] == "universal" and "store_id" not in store


def test_exact_documented_categories_command_resolves_food_and_pets_with_the_real_config(monkeypatch):
    """README line: python -m wmscraper run --location walmart-100-bentonville --categories "Food,Pets" --limit 600
    against the delivered config/categories.csv. The run itself is replaced by a stub (no provider request)."""
    import wmscraper.cli as cli

    seen = {}

    class Captured(Exception):
        pass

    class StubRun:
        def __init__(self, s, loc, run_id=None, categories=None, limit=0, demo=False):
            seen.update(location=loc.key, categories=[c.name for c in categories], limit=limit, demo=demo)
            raise Captured()

    monkeypatch.setattr(cli, "Run", StubRun)
    with pytest.raises(Captured):
        main(["run", "--location", "walmart-100-bentonville", "--categories", "Food,Pets", "--limit", "600"])
    assert seen == {"location": "walmart-100-bentonville", "categories": ["Food", "Pets"], "limit": 600, "demo": True}
