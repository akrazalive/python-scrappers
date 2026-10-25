import asyncio
import json

from conftest import FIX, PAGES

from mscraper.config import Location
from mscraper.fetch import FixtureFetcher
from mscraper.runner import Runner


def _run(settings, location, storage, tmp_path, fetcher, run_id=None):
    r = Runner(settings, location, storage, tmp_path / "state", run_id=run_id, fetcher=fetcher)
    return r, asyncio.run(r.run())


def test_full_run_publishes_valid_data(settings, location, storage, tmp_path, fetcher):
    r, res = _run(settings, location, storage, tmp_path, fetcher)
    assert res["status"] == "published", res["errors"]
    recs = json.loads((storage.root / "test-544/latest/records.json").read_text(encoding="utf-8"))
    assert recs and len({x["upc"] for x in recs}) == len(recs)
    assert all(x["zipcode"] == "60014" and x["store_name"] == "Marianos Crystal Lake" for x in recs)
    rep = json.loads((storage.root / "test-544/latest/report.json").read_text(encoding="utf-8"))
    assert rep["store_verification"]["verified"] and rep["store_checks_during_run"]["store_mismatches"] == 0
    assert rep["coupons"]["count"] > 0 and rep["excluded"].get("approximate_weight", 0) > 0


def test_wrong_store_is_never_published(settings, storage, tmp_path):
    other = Location(key="test-539", store_id="53100539", zipcode="", canary_query="milk")
    f = FixtureFetcher(settings, other, fixtures=dict(PAGES), root=str(FIX))
    import pytest

    with pytest.raises(RuntimeError, match="store verification failed"):
        asyncio.run(Runner(settings, other, storage, tmp_path / "state", fetcher=f).run())
    assert not (storage.root / "test-539/latest/records.json").exists()


def test_failed_run_keeps_last_good_data_and_resume_completes(settings, location, storage, tmp_path):
    good_f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    _, first = _run(settings, location, storage, tmp_path, good_f)
    assert first["status"] == "published"
    manifest = (storage.root / "test-544/latest/manifest.json").read_text()

    # second run: one shelf keeps failing (provider down) -> listing failed -> run not publishable
    bad = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    bad.retries = 1
    bad.fixtures["query=Beef"] = "search_upstream_failure.html.gz"
    r2, second = _run(settings, location, storage, tmp_path, bad)
    assert second["status"] == "validation_failed"
    assert any("Beef" in e for e in second["errors"])
    assert (storage.root / "test-544/latest/manifest.json").read_text() == manifest   # last good data untouched

    # resume the same run once the provider recovers: only the failed shelf is fetched again
    r2.ck.db.execute("DELETE FROM meta WHERE k='final_status'")
    r2.ck.db.commit()
    healed = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    r3, third = _run(settings, location, storage, tmp_path, healed, run_id=r2.run_id)
    assert third["status"] == "published"
    shelf_calls = [u for u in healed.calls if "query=" in u and "query=milk" not in u]
    assert shelf_calls and all("query=Beef" in u for u in shelf_calls)


def test_interruption_resume_does_not_duplicate(settings, location, storage, tmp_path):
    f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    r = Runner(settings, location, storage, tmp_path / "state", fetcher=f)
    settings.raw["fetch"]["max_requests_per_run"] = 8           # simulate a crash part-way (budget exhausted)
    f.budget = 8
    try:
        asyncio.run(r.run())
    except Exception:
        pass
    partial = r.ck.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    settings.raw["fetch"]["max_requests_per_run"] = 0
    f2 = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    r2 = Runner(settings, location, storage, tmp_path / "state", run_id=r.run_id, fetcher=f2)
    r2.ck.db.execute("DELETE FROM meta WHERE k='final_status'")
    r2.ck.db.commit()
    res = asyncio.run(r2.run())
    recs = r2.ck.records()
    assert res["status"] == "published" and len(recs) >= partial
    assert len({x["upc"] for x in recs}) == len(recs)


def test_department_page_down_uses_site_menu(settings, location, storage, tmp_path):
    pages = dict(PAGES)
    pages.pop("/d/meat")                                      # department page unavailable (404 from fixture)
    f = FixtureFetcher(settings, location, fixtures=pages, root=str(FIX))
    f.retries = 0
    r, res = _run(settings, location, storage, tmp_path, f)
    assert res["status"] == "published", res["errors"]
    disc = r.ck.get("discovered:Meat")
    assert disc["shelves"] >= 1 and "Beef" in disc["subcategories"]
    kinds = [k for (k,) in r.ck.db.execute("SELECT kind FROM events")]
    assert "department_page_unavailable" in kinds
