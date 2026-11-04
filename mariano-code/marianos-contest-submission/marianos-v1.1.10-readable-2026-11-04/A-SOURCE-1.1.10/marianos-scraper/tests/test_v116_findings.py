import asyncio
import json
from types import SimpleNamespace

import pytest

from conftest import ROOT
from mscraper.config import Location, load_settings
from mscraper.fetch import FetchError, FetchResult, Fetcher, realtime_payload
from mscraper.parse import SearchPage, StoreInfo
from mscraper.runner import Runner
from mscraper.storage import LocalStorage


def test_classic_search_maps_brand_and_rejects_unsupported_filters():
    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = Location("test", "53100544")
    base = "https://www.marianos.com/search?query=milk"
    assert realtime_payload(settings, location, base)["source"] == "kroger_search"
    assert realtime_payload(settings, location, base + "&brandName=Simple%20Truth")["brand"] == "Simple Truth"
    for suffix in ("&savings=Coupons", "&page=2", "&unexpected=x"):
        with pytest.raises(FetchError, match="unsupported on Classic kroger_search"):
            realtime_payload(settings, location, base + suffix)


def test_retailer_refusal_is_terminal_and_saved(tmp_path):
    settings = load_settings(ROOT / "config" / "settings.yaml")
    settings.raw["fetch"]["min_page_bytes"] = 0
    location = Location("test", "53100544", zipcode="60014")

    class Refused(Fetcher):
        async def _fetch_once(self, url, render_js):
            return FetchResult(url, 403, "<html>denied</html>", 0.01,
                               '{"job_id":"job-123","authorization":"secret","results":[]}', 200)

    fetcher = Refused(settings, location)
    runner = Runner(settings, location, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=fetcher)
    with pytest.raises(FetchError) as exc:
        asyncio.run(fetcher.get("https://www.marianos.com/search?query=milk"))
    assert exc.value.kind == "refused"
    html_files = list((runner.dir / "evidence" / "refusals").glob("*.html.gz"))
    assert html_files
    record = json.loads(html_files[0].with_suffix("").with_suffix(".json").read_text(encoding="utf-8"))
    assert record["provider_status"] == 200 and record["target_status"] == 403
    assert record["request_id"] == "job-123"
    assert "secret" not in json.dumps(record)


def test_classic_unsupported_request_is_rejected_before_budget_reservation():
    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = Location("test", "53100544")
    fetcher = __import__("mscraper.fetch", fromlist=["OxylabsRealtimeFetcher"]).OxylabsRealtimeFetcher(settings, location)
    fetcher.budget = 1
    fetcher.total_budget = None
    with pytest.raises(FetchError, match="unsupported on Classic"):
        asyncio.run(fetcher.get("https://www.marianos.com/search?query=milk&page=2"))
    assert fetcher.stats["requests"] == 0


def test_non_marianos_banner_is_not_verified(tmp_path):
    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = Location("test", "53100544", zipcode="60014")
    store = StoreInfo(location_id="53100544", zipcode="60014", banner="Kroger")
    search = SearchPage([], {}, {}, request_location="53100544", store=store)
    html = "<html>" + ("x" * 1000) + "</html>"

    class Page:
        async def start(self):
            return None

        async def close(self):
            return None

        async def get(self, url, validate=None):
            if validate:
                validate(html)
            return FetchResult(url, 200, html, 0.01)

    import mscraper.runner as runner_module
    original_extract, original_search = runner_module.parse.extract_state, runner_module.parse.search_page
    runner_module.parse.extract_state = lambda _: {}
    runner_module.parse.search_page = lambda _: search
    try:
        runner = Runner(settings, location, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=Page())
        result = asyncio.run(runner.verify_store())
    finally:
        runner_module.parse.extract_state, runner_module.parse.search_page = original_extract, original_search
        runner.ck.close()
    assert result["checks"]["banner_matches"] is False
    assert result["verified"] is False


def _verification_page(source_ids, price=True):
    product = {"data": {"price": {"storePrices": {"sourceLocationId": source_ids}}}}
    if price:
        product["data"]["price"]["storePrices"]["regular"] = {"defaultDescription": "$3.99"}
    store = StoreInfo(location_id="53100544", zipcode="60014", banner="Mariano's",
                      address="105 Northwest Hwy", city="Crystal Lake", state="IL")
    return SearchPage(["A"], {"A": product}, {}, request_location="53100544", store=store)


def test_store_verification_requires_a_monetary_source_price(tmp_path):
    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = Location("test", "53100544", zipcode="60014", expected_address="105 Northwest Hwy")
    search = _verification_page("53100544", price=False)
    html = "<html>" + ("x" * 1000) + "</html>"
    state = {"calypso": {"domains": {"modalityPreferences": {
        "modalities": [{"modalityType": "IN_STORE"}]}}}}

    class Page:
        async def start(self):
            return None

        async def close(self):
            return None

        async def get(self, url, validate=None):
            if validate:
                validate(html)
            return FetchResult(url, 200, html, 0.01)

    import mscraper.runner as runner_module
    original_extract, original_search = runner_module.parse.extract_state, runner_module.parse.search_page
    runner_module.parse.extract_state = lambda _: state
    runner_module.parse.search_page = lambda _: search
    try:
        runner = Runner(settings, location, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=Page())
        result = asyncio.run(runner.verify_store())
    finally:
        runner_module.parse.extract_state, runner_module.parse.search_page = original_extract, original_search
        runner.ck.close()
    assert result["checks"]["prices_from_store"] is False
    assert result["verified"] is False


def test_store_verification_rejects_conflicting_price_sources(tmp_path):
    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = Location("test", "53100544", zipcode="60014", expected_address="105 Northwest Hwy")
    first = _verification_page("53100544")
    second = _verification_page("53100539")
    search = SearchPage(["A", "B"], {**first.products, "B": second.products["A"]}, {},
                        request_location="53100544", store=first.store)
    html = "<html>" + ("x" * 1000) + "</html>"
    state = {"calypso": {"domains": {"modalityPreferences": {
        "modalities": [{"modalityType": "IN_STORE"}]}}}}

    class Page:
        async def start(self):
            return None

        async def close(self):
            return None

        async def get(self, url, validate=None):
            if validate:
                validate(html)
            return FetchResult(url, 200, html, 0.01)

    import mscraper.runner as runner_module
    original_extract, original_search = runner_module.parse.extract_state, runner_module.parse.search_page
    runner_module.parse.extract_state = lambda _: state
    runner_module.parse.search_page = lambda _: search
    try:
        runner = Runner(settings, location, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=Page())
        result = asyncio.run(runner.verify_store())
    finally:
        runner_module.parse.extract_state, runner_module.parse.search_page = original_extract, original_search
        runner.ck.close()
    assert result["checks"]["prices_from_store"] is True
    assert result["checks"]["price_source_locations_match"] is False
    assert result["verified"] is False
