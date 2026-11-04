"""v1.1.4: `selfcheck` – the zero-request deployment check run by the manual Azure job before any live test."""
import json
from pathlib import Path

from mscraper import cli
from mscraper.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path):
    s = load_settings(ROOT / "config" / "settings.yaml")
    s.raw["output"]["backend"] = "local"
    s.raw["output"]["local_dir"] = str(tmp_path / "output")
    return s


def test_selfcheck_writes_and_reads_back_and_never_prints_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCRAPER_OUTPUT_BACKEND", raising=False)
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "oxylabs_realtime")
    monkeypatch.setenv("OXYLABS_USERNAME", "user-value-not-printed")
    monkeypatch.setenv("OXYLABS_PASSWORD", "password-value-not-printed")
    res = cli.cmd_selfcheck(_settings(tmp_path))
    raw = json.dumps(res)
    assert res["ok"] is True and res["provider_requests"] == 0
    assert res["credentials_present"] == {"OXYLABS_USERNAME": True, "OXYLABS_PASSWORD": True}
    assert res["blob"]["read_back_matches"] is True and res["state_dir"]["read_back_matches"] is True
    assert "value-not-printed" not in raw


def test_selfcheck_fails_when_a_credential_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCRAPER_OUTPUT_BACKEND", raising=False)
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "oxylabs_realtime")
    monkeypatch.setenv("OXYLABS_USERNAME", "u")
    monkeypatch.delenv("OXYLABS_PASSWORD", raising=False)
    res = cli.cmd_selfcheck(_settings(tmp_path))
    assert res["ok"] is False and res["credentials_present"]["OXYLABS_PASSWORD"] is False
