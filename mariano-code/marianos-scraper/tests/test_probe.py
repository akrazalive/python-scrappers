import asyncio
import json

from conftest import FIX, PAGES
from mscraper import cli
from mscraper.fetch import FetchError, FetchResult
from mscraper.fetch import FixtureFetcher
from mscraper.probe import run_probe


def test_probe_records_evidence_and_detects_ignored_paging_and_filters(settings, location, tmp_path):
    f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))   # replay: page 2 / slices = same page
    rep = asyncio.run(run_probe(f, settings, location, tmp_path / "probe", "Batteries"))
    fnd = rep["findings"]
    assert fnd["page2_ssr_differs_from_page1"] is False                  # the limitation the probe exists to measure
    assert fnd["brand_filter_honored_all"] is False                      # replayed page ignores the filter -> reported
    assert fnd["all_pages_store"] == ["53100544"]
    assert all(r["response_sha256"] and (tmp_path / "probe" / r["evidence_file"]).exists() for r in rep["requests"])
    assert json.loads((tmp_path / "probe" / "probe.json").read_text(encoding="utf-8"))["query"] == "Batteries"


def test_cli_probe_first_target_refusal_writes_terminal_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "fixture")
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))

    async def refused(self, url, render_js):
        return FetchResult(url, 403, "<html>denied</html>", 0.01,
                           '{"job_id":"job-123","authorization":"secret","results":[]}', 200)

    monkeypatch.setattr(FixtureFetcher, "_fetch_once", refused)
    assert cli.main(["--config", str(__import__("conftest").ROOT / "config" / "settings.yaml"),
                     "probe", "--location", "marianos-544-crystal-lake", "--max-requests", "1"]) == 2
    err = capsys.readouterr().err
    assert "target refused HTTP 403" in err and "KeyError" not in err
    reports = list((tmp_path / "state" / "marianos-544-crystal-lake" / "probes").glob("*/probe.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["failure"]["kind"] == "refused"
    assert report["requests"] == []


def test_cli_probe_first_provider_auth_failure_writes_terminal_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MSCRAPER_FETCH_PROVIDER", "fixture")
    monkeypatch.setenv("MSCRAPER_STATE_DIR", str(tmp_path / "state"))

    async def unauthorized(self, url, render_js):
        raise FetchError("provider authentication failed (HTTP 401)", "auth")

    monkeypatch.setattr(FixtureFetcher, "_fetch_once", unauthorized)
    assert cli.main(["--config", str(__import__("conftest").ROOT / "config" / "settings.yaml"),
                     "probe", "--location", "marianos-544-crystal-lake", "--max-requests", "1"]) == 2
    err = capsys.readouterr().err
    assert "provider authentication failed (HTTP 401)" in err and "KeyError" not in err
    reports = list((tmp_path / "state" / "marianos-544-crystal-lake" / "probes").glob("*/probe.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["failure"]["kind"] == "auth"
    assert report["requests"] == []
