"""v1.1.11 – client review of 1.1.10: a response that arrives but cannot be parsed is preserved as evidence.

The client mocked a malformed HTTP-200 body on the real verify-store / fetcher path: 1.1.10 counted one attempt and
archived nothing. Every received-but-unusable response now keeps a bounded, sanitized copy of its body plus the
SHA-256 of the exact original, in a failure receipt linked to the request, the budget ledger line and the timestamps.
Offline only: provider HTTP is mocked with httpx.MockTransport; no request leaves the machine.
"""
import asyncio
import gzip
import hashlib
import json

import httpx
import pytest
from conftest import ROOT, page

from mscraper import cli
from mscraper.config import load_settings
from mscraper.fetch import FetchError, OxylabsKrogerFetcher, OxylabsRealtimeFetcher
from mscraper.runner import Runner
from mscraper.storage import LocalStorage

CFG = str(ROOT / "config" / "settings.yaml")
VERNON = "marianos-502-vernon-hills"
SECRETS = {"OXYLABS_USERNAME": "user-qual-7781", "OXYLABS_PASSWORD": "pw-Secret-99231", "OXYLABS_WEBAPI_KEY": "key-ABCD-55120"}
NOT_JSON = ("<html><body>Upstream gateway error. Authorization: Basic dXNlcjpwYXNzd29yZA== "
            "token=tok-77aa retry later</body></html>")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("mscraper.fetch.Fetcher._pace", lambda self: asyncio.sleep(0))
    monkeypatch.setattr("mscraper.fetch.random.uniform", lambda a, b: 0)
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)


def _mock(monkeypatch, responses):
    """httpx.AsyncClient answers each provider POST with the next (status, body); every request body is recorded."""
    sent, queue = [], list(responses)

    def handler(request):
        sent.append(json.loads(request.content))
        status, body = queue.pop(0)
        return httpx.Response(status, content=body.encode("utf-8") if isinstance(body, str) else body)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    return sent


def _receipts(run_dir):
    d = run_dir / "evidence" / "failed"
    return [json.loads(x) for x in (d / "receipts.jsonl").read_text(encoding="utf-8").splitlines()] if d.exists() else []


def _stored(run_dir, rec):
    return gzip.decompress((run_dir / rec["stored_file"]).read_bytes())


def _no_secret(run_dir):
    blob = b"".join(gzip.decompress(f.read_bytes()) if f.suffix == ".gz" else f.read_bytes()
                    for f in (run_dir / "evidence" / "failed").iterdir())
    for v in SECRETS.values():
        assert v.encode() not in blob
    assert b"dXNlcjpwYXNzd29yZA==" not in blob and b"tok-77aa" not in blob


def _runner(tmp_path, provider=OxylabsRealtimeFetcher, max_bytes=None):
    settings = load_settings(CFG)
    settings.raw["fetch"]["min_page_bytes"] = 1000
    if max_bytes:
        settings.raw["evidence"]["failed_response_max_bytes"] = max_bytes
    loc = settings.location(VERNON)
    f = provider(settings, loc)
    f.client = httpx.AsyncClient()
    f.backoff = 0
    return Runner(settings, loc, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=f)


def _verify(runner, retries=0):
    runner.fetcher.retries = retries
    with pytest.raises(FetchError) as exc:
        asyncio.run(runner.verify_store())
    return exc.value


# ---------------------------------------------------------------- the reviewer's case, through the real CLI
def test_cli_verify_store_malformed_http200_body_is_preserved_with_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "oxylabs_realtime")
    sent = _mock(monkeypatch, [(200, NOT_JSON)])
    with pytest.raises(FetchError) as exc:
        cli.main(["--config", CFG, "--budget", "qual:1", "verify-store", "--location", VERNON, "--max-requests", "1"])
    assert exc.value.kind == "malformed" and len(sent) == 1           # one attempt, exactly as before
    assert sent[0]["store_id"] == "53100502" and sent[0]["fulfillment_type"] == "pickup"
    runs = list((tmp_path / "state" / "_verify" / VERNON / "runs").iterdir())
    assert len(runs) == 1
    [rec] = _receipts(runs[0])
    ledger = [json.loads(x) for x in (tmp_path / "state" / "_budgets" / "qual.jsonl").read_text("utf-8").splitlines()]
    assert len(ledger) == 1 and rec["budget"] == "qual" and rec["budget_request_n"] == ledger[0]["n"] == 1
    assert rec["url"] == ledger[0]["url"] and rec["attempt"] == 1 and rec["request_seq"] == 1
    assert rec["requested_at"] and rec["failed_at"] >= rec["requested_at"]
    assert rec["error_kind"] == "malformed" and "could not be parsed" in rec["error"]
    assert rec["provider_status"] == 200 and rec["original_format"] == "text"
    assert rec["original_sha256"] == hashlib.sha256(NOT_JSON.encode()).hexdigest()
    assert rec["original_bytes"] == len(NOT_JSON.encode()) and not rec["truncated"]
    assert rec["request_body"]["source"] == "kroger_search" and rec["request_body"]["store_id"] == "53100502"
    body = _stored(runs[0], rec)
    assert b"Upstream gateway error" in body and hashlib.sha256(body).hexdigest() == rec["stored_sha256"]
    assert json.loads((runs[0] / rec["receipt_file"]).read_text("utf-8")) == rec
    _no_secret(runs[0])


# ---------------------------------------------------------------- malformed / non-JSON / unsupported shapes
@pytest.mark.parametrize("body,fmt", [
    (NOT_JSON, "text"),                                              # not JSON at all
    ("", "text"),                                                    # empty HTTP-200 body
    ('{"results": [{"content": "<html>', "text"),                    # truncated JSON
    ("[1, 2, 3]", "json"),                                           # JSON, but a list
    ('{"results": "not-a-list"}', "json"),                           # results of the wrong type
    ('{"results": [{"content": "<html></html>", "status_code": "n/a"}]}', "json"),   # non-numeric target status
], ids=["not-json", "empty", "truncated-json", "json-list", "results-wrong-type", "non-numeric-status"])
def test_unsupported_provider_shapes_are_archived_not_discarded(tmp_path, monkeypatch, body, fmt):
    _mock(monkeypatch, [(200, body)])
    runner = _runner(tmp_path)
    assert _verify(runner).kind == "malformed"
    [rec] = _receipts(runner.dir)
    assert rec["original_sha256"] == hashlib.sha256(body.encode()).hexdigest() and rec["original_format"] == fmt
    assert (runner.dir / rec["stored_file"]).exists()
    events = [json.loads(d) for k, d in runner.ck.db.execute("SELECT kind, detail FROM events") if k == "response_failed"]
    assert [e["original_sha256"] for e in events] == [rec["original_sha256"]]
    assert events[0]["receipt_file"] == rec["receipt_file"]


def test_kroger_adapter_malformed_body_is_archived_without_the_bearer_key(tmp_path, monkeypatch):
    _mock(monkeypatch, [(200, NOT_JSON + " " + SECRETS["OXYLABS_WEBAPI_KEY"])])
    runner = _runner(tmp_path, provider=OxylabsKrogerFetcher)
    assert _verify(runner).kind == "malformed"
    [rec] = _receipts(runner.dir)
    assert rec["fetcher"] == "oxylabs_kroger" and rec["request_body"]["store_id"] == "53100502"
    _no_secret(runner.dir)


def test_valid_envelope_with_unparseable_page_is_archived(tmp_path, monkeypatch):
    """The envelope parses but the Mariano's page inside has no application state (PageError in validate)."""
    envelope = json.dumps({"job_id": "job-42", "results": [{"content": "<html>" + "x" * 2000 + "</html>", "status_code": 200}]})
    _mock(monkeypatch, [(200, envelope)])
    runner = _runner(tmp_path)
    assert _verify(runner).kind == "malformed"
    [rec] = _receipts(runner.dir)
    assert rec["error_kind"] == "malformed" and "application state" in rec["error"]
    assert rec["target_status"] == 200 and rec["request_id"] == "job-42" and rec["original_format"] == "json"
    assert rec["original_sha256"] == hashlib.sha256(envelope.encode()).hexdigest()


def test_stored_copy_is_bounded_and_the_original_hash_is_of_the_full_body(tmp_path, monkeypatch):
    big = "<html>" + "y" * 50_000 + "</html>"
    _mock(monkeypatch, [(200, big)])
    runner = _runner(tmp_path, max_bytes=4096)
    _verify(runner)
    [rec] = _receipts(runner.dir)
    assert rec["truncated"] and rec["stored_bytes"] == 4096 == len(_stored(runner.dir, rec))
    assert rec["original_bytes"] == len(big) and rec["original_sha256"] == hashlib.sha256(big.encode()).hexdigest()


def test_credentials_and_sensitive_headers_never_reach_the_archive(tmp_path, monkeypatch):
    envelope = json.dumps({"job": {"id": "job-9", "Authorization": "Basic dXNlcjpwYXNzd29yZA=="},
                           "results": [{"content": "page token=tok-77aa " + SECRETS["OXYLABS_PASSWORD"],
                                        "headers": {"Set-Cookie": "sess=abc123", "X-Api-Key": "k-1"},
                                        "url": f"https://{SECRETS['OXYLABS_USERNAME']}:{SECRETS['OXYLABS_PASSWORD']}@x.io/",
                                        "status_code": "bad"}]})
    _mock(monkeypatch, [(200, envelope)])
    runner = _runner(tmp_path)
    _verify(runner)
    [rec] = _receipts(runner.dir)
    stored = json.loads(_stored(runner.dir, rec))                   # the stored copy stays valid JSON
    headers = stored["results"][0]["headers"]
    assert headers == {"Set-Cookie": "[REDACTED]", "X-Api-Key": "[REDACTED]"}
    assert rec["request_id"] == "job-9"
    _no_secret(runner.dir)
    assert b"sess=abc123" not in _stored(runner.dir, rec)


def test_each_retried_attempt_gets_its_own_receipt_and_ledger_line(tmp_path, monkeypatch):
    _mock(monkeypatch, [(200, NOT_JSON), (200, "[]")])
    runner = _runner(tmp_path)
    _verify(runner, retries=1)
    recs = _receipts(runner.dir)
    assert [(r["attempt"], r["request_seq"]) for r in recs] == [(1, 1), (2, 2)]
    assert len({r["original_sha256"] for r in recs}) == 2 and len({r["receipt_file"] for r in recs}) == 2


@pytest.mark.parametrize("status,kind", [(400, "compat"), (503, "http")])
def test_provider_error_bodies_are_archived(tmp_path, monkeypatch, status, kind):
    _mock(monkeypatch, [(status, '{"message": "source not available for this account"}')])
    runner = _runner(tmp_path)
    assert _verify(runner).kind == kind
    [rec] = _receipts(runner.dir)
    assert rec["provider_status"] == status and rec["error_kind"] == kind


def test_usable_response_writes_no_failure_receipt(tmp_path, monkeypatch):
    envelope = json.dumps({"results": [{"content": page("search_milk_store544.html.gz"), "status_code": 200}]})
    _mock(monkeypatch, [(200, envelope)])
    runner = _runner(tmp_path)
    runner.fetcher.retries = 0
    res = asyncio.run(runner.verify_store())
    assert res["evidence_response_sha256"] and _receipts(runner.dir) == []
