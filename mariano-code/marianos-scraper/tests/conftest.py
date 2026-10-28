import gzip
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mscraper.config import Category, Location, load_settings  # noqa: E402
from mscraper.fetch import FixtureFetcher  # noqa: E402
from mscraper.storage import LocalStorage  # noqa: E402

FIX = ROOT / "tests" / "fixtures"

# Real marianos.com responses (Oxylabs, store pinned) saved during development.
PAGES = {
    "/search?query=milk": "search_milk_store544.html.gz",
    "/d/meat": "department_meat_store544.html.gz",
    "/search?": "search_beef_store544.html.gz",          # every Meat shelf search
    "/savings/cl/coupons": "coupons_page_store544.html.gz",
}


def page(name: str) -> str:
    return gzip.decompress((FIX / name).read_bytes()).decode("utf-8")


@pytest.fixture
def settings():
    s = load_settings(ROOT / "config" / "settings.yaml")
    s.raw["crawl"]["max_pages_per_query"] = 3
    # the saved shelf page is a beef search, so only shelves that page really represents are crawled in tests
    s.raw["crawl"]["skip_shelf_patterns"] = [r"^(?!Beef$|Steaks$|Frozen Meat$|Organic Meat$).*"]
    s.raw["fetch"]["min_page_bytes"] = 1000
    # saved pages cannot answer brand-filtered requests (every URL returns the same saved page), so brand slicing is
    # tested separately in test_v110_client_points.test_ignored_brand_filter_is_never_counted_as_coverage
    s.raw["crawl"]["brand_slices"] = False
    s.categories = [Category("Meat", "https://www.marianos.com/d/meat", "Category + ALL subcategories"),
                    Category("Coupons", "https://www.marianos.com/savings/cl/coupons/", "Category + ALL subcategories")]
    return s


@pytest.fixture
def location():
    return Location(key="test-544", store_id="53100544", zipcode="60014", expected_address="105 Northwest Hwy",
                    canary_query="milk", canary_upcs=("0001111050438",))


@pytest.fixture
def fetcher(settings, location):
    return FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "output")


@pytest.fixture
def live(tmp_path):
    """Hold the process-wide live lock (as every CLI command that sends requests does)."""
    from mscraper.lock import live_lock

    with live_lock(LocalStorage(tmp_path / "lockstore")) as lk:
        yield lk
