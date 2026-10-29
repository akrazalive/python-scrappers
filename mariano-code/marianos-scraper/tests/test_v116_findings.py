import asyncio
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
            return FetchResult(url, 403, "<html>denied</html>", 0.01)

    fetcher = Refused(settings, location)
    runner = Runner(settings, location, LocalStorage(tmp_path / "output"), tmp_path / "state", fetcher=fetcher)
    with pytest.raises(FetchError) as exc:
        asyncio.run(fetcher.get("https://www.marianos.com/search?query=milk"))
    assert exc.value.kind == "refused"
    assert list((runner.dir / "evidence" / "refusals").glob("*.html.gz"))


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
