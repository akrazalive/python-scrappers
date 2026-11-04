import asyncio
from types import SimpleNamespace

import pytest

from mscraper.runner import _has_monetary_price, _has_qualifying_store_price


@pytest.mark.parametrize("value", ["2 pack", "Only 2 left", "Save $2", "0", "-1.99", "inf", "2026-11-01"])
def test_unrelated_or_nonpositive_display_text_is_rejected(value):
    assert not _has_monetary_price({"regular": {"defaultDescription": value}})


@pytest.mark.parametrize("value", ["$3.49", "$3.49/lb"])
def test_payable_display_prices_are_accepted(value):
    assert _has_monetary_price({"regular": {"defaultDescription": value}})


@pytest.mark.parametrize("value", [0, -1.99, float("inf"), float("nan")])
def test_nonfinite_or_nonpositive_numeric_prices_are_rejected(value):
    assert not _has_monetary_price({"regular": {"price": value}})


def test_numeric_regular_and_promo_prices_are_accepted():
    assert _has_monetary_price({"regular": {"price": 3.49}})
    assert _has_monetary_price({"promo": {"amount": 2.99}})


def test_wrong_fulfillment_mode_is_rejected():
    assert not _has_monetary_price({"regular": {"price": 3.49, "fulfillmentMode": "DELIVERY"}})


def test_wrong_store_is_rejected_by_qualification_context():
    assert not _has_qualifying_store_price({"regular": {"price": 3.49}}, "53100539", "53100544", "IN_STORE")


def test_verify_store_fixture_with_only_stock_count_is_not_verified(tmp_path, monkeypatch):
    from conftest import ROOT
    from mscraper.config import Location, load_settings
    from mscraper.fetch import FetchResult
    from mscraper.parse import SearchPage, StoreInfo
    from mscraper.storage import LocalStorage
    import mscraper.runner as runner_module

    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = Location("test", "53100544", zipcode="60014", expected_address="105 Northwest Hwy")
    store = StoreInfo(location_id="53100544", zipcode="60014", banner="Mariano's",
                      address="105 Northwest Hwy", city="Crystal Lake", state="IL")
    product = {"data": {"price": {"storePrices": {"sourceLocationId": "53100544",
                                                     "regular": {"defaultDescription": "Only 2 left"}}}}}
    search = SearchPage(["A"], {"A": product}, {}, request_location="53100544", store=store)
    state = {"calypso": {"domains": {"modalityPreferences": {
        "modalities": [{"modalityType": "IN_STORE"}]}}}}

    class Page:
        async def get(self, url, validate=None):
            if validate:
                validate("<html>" + ("x" * 1000) + "</html>")
            return FetchResult(url, 200, "<html>" + ("x" * 1000) + "</html>", 0.01)

    monkeypatch.setattr(runner_module.parse, "extract_state", lambda _: state)
    monkeypatch.setattr(runner_module.parse, "search_page", lambda _: search)
    runner = __import__("mscraper.runner", fromlist=["Runner"]).Runner(
        settings, location, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=Page())
    try:
        result = asyncio.run(runner.verify_store())
    finally:
        runner.ck.close()
    assert result["verified"] is False
