"""End-to-end behaviour on the synthetic mini-site (see conftest.py)."""
import asyncio
import json

import pytest

from wmscraper.config import load_settings
from wmscraper.models import FIELD_ORDER
from wmscraper.runner import Run
from wmscraper.storage import build_storage


def run(settings_path, **kw):
    s = load_settings(settings_path)
    return s, asyncio.run(Run(s, s.location("test-store"), **kw).execute())


def latest(s):
    return build_storage(s).get_json("test-store/latest/records.json")


def test_full_run_publishes_valid_data(site):
    s, rep = run(site)
    assert rep["validation"]["ok"], rep["validation"]
    recs = latest(s)
    titles = {r["product_title"] for r in recs}
    # kept: local Walmart offers only
    assert titles == {"Great Value Whole Milk, 1 gal", "Fairlife 2% Milk, 52 fl oz", "Horizon Organic Milk, 0.5 gal",
                      "Lay's Classic Chips, 8 oz", "Doritos Nacho, 9.25 oz", "Sponsored Oat Milk, 64 fl oz"}
    # excluded with reasons; sponsored placements are real local products -> kept once, never duplicated
    ex = rep["excluded"]
    assert "sponsored_placement" not in ex and ex["marketplace_seller"] == 1 and ex["approximate_weight"] == 1
    assert ex["not_store_assortment_online_only"] == 1  # scope = store assortment (online-only offer not collected)
    assert not any("stock" in k or "pickup" in k for k in ex)  # availability never excludes a store product
    assert rep["duplicates_prevented"] == 2 and rep["duplicate_records_in_output"] == 0
    # Departments split: Recipes excluded per CSV note, "Shop All" skipped, grandchild not crawled directly
    assert {l["sub_category"] for l in rep["listings"]} == {"Milk", "Snacks"}
    for r in recs:
        assert tuple(r) == FIELD_ORDER and all(isinstance(v, str) for v in r.values())
        assert r["gupc"] == "" and r["unit_price"] == ""
        assert r["store_name"] == "Bentonville Supercenter" and r["zipcode"] == "72712"
    by = {r["product_title"]: r for r in recs}
    gv = by["Great Value Whole Milk, 1 gal"]
    assert gv["store_brand"] == "yes" and gv["upc"] == "078742351865" and gv["ppm"] == "2.7 ¢/fl oz" and gv["weight"] == "1 gal"
    fl = by["Fairlife 2% Milk, 52 fl oz"]
    assert (fl["regular_price"], fl["sale_price"]) == ("5.48", "4.98")
    assert (fl["volume_deals_description"], fl["volume_deals_price"]) == ("2 for $9", "9.00")
    assert by["Horizon Organic Milk, 0.5 gal"]["digital_deals_description"] == "Clip Coupon: Save $1.00"
    assert by["Horizon Organic Milk, 0.5 gal"]["digital_deals_price"] == ""
    lays = by["Lay's Classic Chips, 8 oz"]
    assert lays["digital_deals_price"] == "3.50"
    assert "Shipping Only Milk 12 pack" not in by  # online-only offer: not part of the store assortment
    dor = by["Doritos Nacho, 9.25 oz"]
    assert dor["volume_deals_description"] == "Buy 1, Get 1 Free" and dor["volume_deals_price"] == ""
    assert "Walmart Cash" not in dor["digital_deals_description"]


def test_store_mismatch_blocks_publication(site):
    fx = json.loads((site.parent.parent / "fixtures" / "map.json").read_text())
    p = site.parent.parent / "fixtures" / fx["https://www.walmart.com/browse/976759_976787?stores=1234"]
    p.write_text(p.read_text().replace('"storeId": "1234"', '"storeId": "9999"'))
    s, rep = run(site)
    assert not rep["validation"]["ok"]
    assert any("store context" in e for e in rep["validation"]["errors"])
    assert latest(s) is None  # nothing published


def test_failed_run_never_replaces_good_data(site):
    s, rep = run(site)
    good = latest(s)
    assert rep["validation"]["ok"] and good
    # next run: one listing blocked (bot challenge)
    fx_dir = site.parent.parent / "fixtures"
    fx = json.loads((fx_dir / "map.json").read_text())
    (fx_dir / fx["https://www.walmart.com/browse/976759_976787?stores=1234"]).write_text(
        "<html><title>Robot or human?</title>" + "x" * 3000 + "</html>")
    s, rep2 = run(site)
    assert not rep2["validation"]["ok"]
    assert latest(s) == good  # last successful dataset untouched


def test_interruption_resumes_without_loss_or_duplicates(site, monkeypatch):
    s = load_settings(site)
    r1 = Run(s, s.location("test-store"))
    calls = {"n": 0}
    orig = r1.ck.commit_page

    def crash_after_first_page(*a, **k):
        calls["n"] += 1
        out = orig(*a, **k)
        if calls["n"] == 1:
            raise KeyboardInterrupt("simulated crash")
        return out

    monkeypatch.setattr(r1.ck, "commit_page", crash_after_first_page)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(r1.execute())
    run_id = r1.run_id
    r1.ck.close()
    # stale lock from the crash must be cleared by the operator / lease expiry; emulate expiry
    (build_storage(s).local_path("test-store/.run.lock")).unlink(missing_ok=True)
    s2 = load_settings(site)
    r2 = Run(s2, s2.location("test-store"))
    assert r2.run_id == run_id  # auto-resume of the open run
    rep = asyncio.run(r2.execute())
    assert rep["validation"]["ok"], rep["validation"]
    assert rep["total_unique_records"] == 6 and rep["duplicate_records_in_output"] == 0


def test_demo_runs_are_never_published(site):
    s, rep = run(site, limit=2, demo=True)
    assert rep["published"] is None and latest(s) is None
