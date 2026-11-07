"""v1.1.12 - client review of 1.1.11: a provider body that is itself a JSON string kept its credential.

sanitize_provider_response decoded the string and returned it without redaction, so save_failed_response stored it in
its text branch while the receipt said sanitized=true. Every string in a decoded body is now redacted, and the hash of
the exact original body and the receipt linkage stay as they were.
Offline only: provider HTTP is mocked with httpx.MockTransport; the credentials below are synthetic.
"""
import gzip
import hashlib
import json

import pytest
from test_v1111_failed_response import (CFG, SECRETS, VERNON, _mock, _offline, _receipts, _runner, _stored,  # noqa: F401
                                        _verify)

from mscraper import cli
from mscraper.fetch import FetchError, OxylabsKrogerFetcher

DUMMY = "DUMMY_REVIEW_SECRET_12345"
JSON_STRING = json.dumps(f"Bearer {DUMMY}")                          # the whole body, quotes included


def _assert_absent(root, *values):
    """No file under `root` (evidence, receipts, checkpoint database, budget ledger) holds the value, plain or gzipped."""
    files = [f for f in root.rglob("*") if f.is_file()]
    assert files
    for f in files:
        data = f.read_bytes()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        for value in values:
            assert value.encode() not in data, f"{value} found in {f}"


# ---------------------------------------------------------------- the reviewer's case, through the real CLI
def test_cli_verify_store_json_string_body_is_redacted_with_its_receipt_intact(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "oxylabs_realtime")
    sent = _mock(monkeypatch, [(200, JSON_STRING)])
    with pytest.raises(FetchError) as exc:
        cli.main(["--config", CFG, "--budget", "qual:1", "verify-store", "--location", VERNON, "--max-requests", "1"])
    assert exc.value.kind == "malformed" and len(sent) == 1
    [run] = (tmp_path / "state" / "_verify" / VERNON / "runs").iterdir()
    [rec] = _receipts(run)
    ledger = [json.loads(x) for x in (tmp_path / "state" / "_budgets" / "qual.jsonl").read_text("utf-8").splitlines()]
    assert len(ledger) == 1 and rec["budget_request_n"] == ledger[0]["n"] == 1 and rec["url"] == ledger[0]["url"]
    assert rec["original_sha256"] == hashlib.sha256(JSON_STRING.encode()).hexdigest()
    assert rec["original_bytes"] == len(JSON_STRING.encode()) and rec["original_format"] == "text"
    body = _stored(run, rec)
    assert body == b"Bearer [REDACTED]" and rec["sanitized"] is True
    assert rec["stored_sha256"] == hashlib.sha256(body).hexdigest() and rec["stored_bytes"] == len(body)
    assert rec["stored_file"].endswith(f"{rec['original_sha256']}.txt.gz")
    assert json.loads((run / rec["receipt_file"]).read_text("utf-8")) == rec
    _assert_absent(tmp_path / "state", DUMMY)


# ---------------------------------------------------------------- every credential form, inside a JSON string
@pytest.mark.parametrize("text,removed,kept", [
    (f"Bearer {DUMMY}", DUMMY, "Bearer [REDACTED]"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA==", "Authorization: [REDACTED] [REDACTED]"),
    ("gateway error token=tok-77aa retry", "tok-77aa", "gateway error token=[REDACTED] retry"),
    ("see https://alice:hunter2pw@x.io/a", "hunter2pw", "see https://[REDACTED]@x.io/a"),
    (f"key was {SECRETS['OXYLABS_WEBAPI_KEY']} here", SECRETS["OXYLABS_WEBAPI_KEY"], "key was [REDACTED] here"),
    ('{"token": "tok-77aa"}', "tok-77aa", '{"token": "[REDACTED]"}'),    # JSON text inside the JSON string
], ids=["bearer", "basic", "key-value", "url-password", "configured-credential", "double-encoded"])
def test_json_string_body_loses_each_credential_form(tmp_path, monkeypatch, text, removed, kept):
    body = json.dumps(text)
    _mock(monkeypatch, [(200, body)])
    runner = _runner(tmp_path)
    assert _verify(runner).kind == "malformed"
    [rec] = _receipts(runner.dir)
    assert _stored(runner.dir, rec).decode() == kept
    assert rec["original_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    _assert_absent(tmp_path, removed)


def test_json_string_body_with_unicode_escapes_is_redacted_after_decoding(tmp_path, monkeypatch):
    body = '"\\u0042earer ' + DUMMY.replace("D", "\\u0044", 1) + '"'     # the secret never appears literally
    assert DUMMY not in body and json.loads(body) == f"Bearer {DUMMY}"
    _mock(monkeypatch, [(200, body)])
    runner = _runner(tmp_path)
    _verify(runner)
    [rec] = _receipts(runner.dir)
    assert _stored(runner.dir, rec) == b"Bearer [REDACTED]"
    assert rec["original_sha256"] == hashlib.sha256(body.encode()).hexdigest()


def test_second_adapter_redacts_a_json_string_body(tmp_path, monkeypatch):
    _mock(monkeypatch, [(200, JSON_STRING)])
    runner = _runner(tmp_path, provider=OxylabsKrogerFetcher)
    assert _verify(runner).kind == "malformed"
    [rec] = _receipts(runner.dir)
    assert rec["fetcher"] == "oxylabs_kroger" and _stored(runner.dir, rec) == b"Bearer [REDACTED]"
    _assert_absent(tmp_path, DUMMY)


def test_large_json_string_body_is_redacted_before_it_is_bounded(tmp_path, monkeypatch):
    body = json.dumps(f"Bearer {DUMMY} " + "y" * 50_000)
    _mock(monkeypatch, [(200, body)])
    runner = _runner(tmp_path, max_bytes=4096)
    _verify(runner)
    [rec] = _receipts(runner.dir)
    assert rec["truncated"] and rec["stored_bytes"] == 4096 == len(_stored(runner.dir, rec))
    assert rec["original_sha256"] == hashlib.sha256(body.encode()).hexdigest() and rec["original_bytes"] == len(body)
    _assert_absent(tmp_path, DUMMY)


# ---------------------------------------------------------------- related gaps with the same cause
@pytest.mark.parametrize("field", ["job_id", "query"])
def test_request_id_taken_from_the_body_is_redacted(tmp_path, monkeypatch, field):
    _mock(monkeypatch, [(200, json.dumps({field: f"Bearer {DUMMY}", "results": "not-a-list"}))])
    runner = _runner(tmp_path)
    _verify(runner)
    [rec] = _receipts(runner.dir)
    assert rec["request_id"] == "Bearer [REDACTED]"
    _assert_absent(tmp_path, DUMMY)


def test_credential_used_as_an_object_key_is_redacted(tmp_path, monkeypatch):
    _mock(monkeypatch, [(200, json.dumps({f"Bearer {DUMMY}": "x", "results": "not-a-list"}))])
    runner = _runner(tmp_path)
    _verify(runner)
    [rec] = _receipts(runner.dir)
    assert json.loads(_stored(runner.dir, rec)) == {"Bearer [REDACTED]": "[REDACTED]", "results": "not-a-list"}
    _assert_absent(tmp_path, DUMMY)


def test_refusal_envelope_strings_are_redacted(tmp_path, monkeypatch):
    envelope = {"job_id": "job-7", "note": f"Bearer {DUMMY}",
                "results": [{"content": "<html>denied</html>", "status_code": 403}]}
    _mock(monkeypatch, [(200, json.dumps(envelope))])
    runner = _runner(tmp_path)
    assert _verify(runner).kind == "refused"
    [saved] = (runner.dir / "evidence" / "refusals").glob("*.json")
    record = json.loads(saved.read_text("utf-8"))
    assert record["provider_envelope"]["note"] == "Bearer [REDACTED]" and record["request_id"] == "job-7"
    _assert_absent(tmp_path, DUMMY)


# ---------------------------------------------------------------- controls
def test_harmless_json_string_and_metadata_are_kept_unchanged(tmp_path, monkeypatch):
    _mock(monkeypatch, [(200, json.dumps("upstream busy, retry later")),
                        (200, json.dumps({"job_id": "job-42", "results": "x"}))])
    runner = _runner(tmp_path)
    _verify(runner, retries=1)
    first, second = _receipts(runner.dir)
    assert _stored(runner.dir, first) == b"upstream busy, retry later" and first["original_format"] == "text"
    assert second["request_id"] == "job-42" and json.loads(_stored(runner.dir, second))["job_id"] == "job-42"
