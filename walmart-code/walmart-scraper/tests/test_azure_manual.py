"""Manual-only Azure deployment (1.1.6): zero-request default command, request cap on the store probe,
provider chosen at deployment, and the infrastructure template's safety defaults."""
import json
import re
from pathlib import Path

from wmscraper.cli import main

ROOT = Path(__file__).resolve().parents[1]
BICEP = (ROOT / "deploy" / "azure" / "main.bicep").read_text(encoding="utf-8")


def test_status_sends_no_request_and_never_prints_credentials(site, capsys, monkeypatch):
    monkeypatch.setenv("WMSCRAPER_FETCH_PROVIDER", "oxylabs_webapi")
    monkeypatch.setenv("OXYLABS_WEBAPI_KEY", "do-not-print-this-value")
    assert main(["--config", str(site), "status"]) == 0
    raw = capsys.readouterr().out
    out = json.loads(raw)
    assert out["provider"] == "oxylabs_webapi"            # deployment-time provider override
    assert out["credentials_present"] == {"OXYLABS_WEBAPI_KEY": True}
    assert out["provider_requests"] == 0 and out["storage_ok"] is True
    assert "do-not-print-this-value" not in raw


def test_status_reports_missing_credential_by_name_only(site, capsys, monkeypatch):
    monkeypatch.setenv("WMSCRAPER_FETCH_PROVIDER", "oxylabs")
    monkeypatch.delenv("OXYLABS_USERNAME", raising=False)
    monkeypatch.delenv("OXYLABS_PASSWORD", raising=False)
    main(["--config", str(site), "status"])
    out = json.loads(capsys.readouterr().out)
    assert out["credentials_present"] == {"OXYLABS_USERNAME": False, "OXYLABS_PASSWORD": False}


def test_verify_store_stops_at_its_request_cap(site, capsys):
    # the store page uses the one allowed request; the canary is refused by the cap, so the probe fails closed
    assert main(["--config", str(site), "verify-store", "--location", "test-store", "--max-requests", "1"]) == 1
    cap = capsys.readouterr()
    assert "request budget of 1 reached" in cap.out and "canary" in cap.err


def test_infrastructure_template_is_manual_and_needs_no_role_rights_or_credential():
    default = lambda name: re.search(rf"^param {name} \w+ = (.+)$", BICEP, re.M).group(1).strip()
    assert default("assignRoles") == "false"       # Contributor cannot assign roles: admin runs the printed commands
    assert default("deployJob") == "false"         # phase 1 = empty vault + identity + storage, no job
    assert default("scheduleEnabled") == "false"   # no recurring schedule unless the client approves one
    assert default("replicaRetryLimit") == "0"     # a request cap cannot be multiplied by automatic retries
    assert default("defaultArgs") == "'status'"    # an accidental manual start sends no provider request
    assert "Microsoft.ContainerRegistry" not in BICEP and "@secure()" not in BICEP
    for ra in re.findall(r"resource \w+ 'Microsoft.Authorization/roleAssignments@[^']+' = (.+?) \{", BICEP):
        assert ra == "if (assignRoles)"
    assert re.search(r"resource job 'Microsoft.App/jobs@[^']+' = if \(deployJob\)", BICEP)
    assert "scope: container" in BICEP             # blob role limited to the designated container


# ---- 1.1.7: persistent total request ledger -------------------------------------------------------------------
def _budget(site):
    from wmscraper.config import load_settings
    from wmscraper.storage import build_storage

    s = load_settings(str(site))
    return s, build_storage(s)


def test_probe_total_holds_across_repeated_executions(site, capsys):
    from wmscraper.budget import TotalBudget

    for _ in range(3):  # the probe started three times: still never more than 3 requests in total
        main(["--config", str(site), "--budget", "probe:3", "verify-store", "--location", "test-store", "--max-requests", "10"])
    s, st = _budget(site)
    state = st.get_json("_budgets/probe.json")
    assert state["used"] == 3 and state["total"] == 3
    ledger = st.get_bytes("_budgets/probe.jsonl").decode().splitlines()
    assert len(ledger) == 3 and [json.loads(x)["n"] for x in ledger] == [1, 2, 3]
    assert TotalBudget(st, "probe", 3).remaining == 0
    capsys.readouterr()


def test_retries_count_against_the_total_and_the_cap_cannot_be_raised(site):
    import asyncio

    import pytest

    from wmscraper.budget import TotalBudget
    from wmscraper.fetch import FetchError
    from wmscraper.fetch.base import Fetcher

    s, st = _budget(site)
    s.raw["fetch"].update(max_retries=10, backoff_base_seconds=0)

    class AlwaysFails(Fetcher):
        sent = 0

        async def _fetch_once(self, url):
            AlwaysFails.sent += 1
            raise FetchError("HTTP 500", "http")

    f = AlwaysFails(s, s.location("test-store"))
    f.total_budget = TotalBudget(st, "retrytest", 4)
    with pytest.raises(FetchError, match="total budget 'retrytest' of 4"):
        asyncio.run(f.get("https://www.walmart.com/ip/1"))
    assert AlwaysFails.sent == 4                                   # 1 attempt + 3 retries, then refused
    f2 = AlwaysFails(s, s.location("test-store"))                  # a restarted process: nothing left
    f2.total_budget = TotalBudget(st, "retrytest", 4)
    with pytest.raises(FetchError, match="used up"):
        asyncio.run(f2.get("https://www.walmart.com/ip/1"))
    assert AlwaysFails.sent == 4
    with pytest.raises(ValueError, match="never raised"):
        TotalBudget(st, "retrytest", 40)
