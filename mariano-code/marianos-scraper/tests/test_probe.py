import asyncio
import json

from conftest import FIX, PAGES

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
