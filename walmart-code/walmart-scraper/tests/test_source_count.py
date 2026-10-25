"""Production coverage mode (crawl.coverage: source_count) on synthetic pages.

Listings are store-pinned and Walmart-sold (retailer facet). Every planned listing fits the page window and is
paginated to Walmart's last page; the products seen must reconcile with Walmart's own reported total.
"""
import asyncio
import json

import yaml

import conftest as c
from wmscraper.config import load_settings
from wmscraper.runner import Run

Q2 = "?stores=1234&facet=retailer_type%3AWalmart"


def _setup(site, pages, csv_rows, tolerance=2, **crawl):
    fx = site.parent.parent / "fixtures"
    m = json.loads((fx / "map.json").read_text())
    for n, (url, html) in enumerate(pages.items()):
        (fx / f"s{n}.html").write_text(html, encoding="utf-8")
        m[url] = f"s{n}.html"
    (fx / "map.json").write_text(json.dumps(m))
    if csv_rows:
        (site.parent / "categories.csv").write_text("Retailer,Category (Auto),URL,Scope,Notes\n" + csv_rows, encoding="utf-8")
    cfg = yaml.safe_load(site.read_text())
    cfg["crawl"].update(coverage="source_count", listing_params={"stores": "{store_id}", "facet": "retailer_type:Walmart"},
                        max_pages_per_listing=2, page_size=2, **{"full_page_min_items": 1, **crawl})
    cfg["validation"].update(thin_listing_ratio=0.95, source_count_tolerance=tolerance)
    site.write_text(yaml.safe_dump(cfg, sort_keys=False))
    s = load_settings(site)
    return asyncio.run(Run(s, s.location("test-store")).execute())


def _food(snacks_total=2):
    return {
        f"{c.BROWSE}976759{Q2}": c.listing([c.item(900, "Root Sample Item, 1 ct", "$1.00")], total=50, max_page=2, children=[
            ("Milk", "976759_9176907"), ("Snacks", "976759_976787"), ("Recipes", "976759_1234567"),
            ("Milk (alias path)", "976759_555_9176907")]),
        f"{c.BROWSE}976759_9176907{Q2}": c.listing([
            c.item(101, "Great Value Whole Milk, 1 gal", "$3.48", ppm="2.7 ¢/fl oz"),
            c.item(105, "Shipping Only Milk 12 pack", "$29.99", fulfil="Free shipping, arrives in 3+ days"),
        ], max_page=2, total=3),
        f"{c.BROWSE}976759_9176907?page=2&{Q2[1:]}": c.listing([
            c.item(106, "Horizon Organic Milk, 0.5 gal", "$4.68", availability="OUT_OF_STOCK"),
        ], max_page=2, total=3),
        f"{c.BROWSE}976759_976787{Q2}": c.listing([
            c.item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz"),
            c.item(203, "Doritos Nacho, 9.25 oz", "$4.98"),
        ], total=snacks_total),
    }


def test_source_count_traversal_reconciles_and_keeps_out_of_stock(site):
    rep = _setup(site, _food(), "")
    assert rep["validation"]["ok"], rep["validation"]
    rec = {r["url"]: r for r in rep["count_reconciliation"]}
    milk = rec[f"{c.BROWSE}976759_9176907"]
    assert (milk["reported_total"], milk["seen"], milk["stop_reason"]) == (3, 3, "walmart_last_page")
    assert milk["store_available"] == 1 and milk["store_oos"] == 1
    titles = {r["product_title"] for r in json.load(open(site.parent.parent / "out" / "test-store" / "latest" / "records.json"))}
    assert "Horizon Organic Milk, 0.5 gal" in titles          # out-of-stock store product retained
    assert "Shipping Only Milk 12 pack" not in titles          # online-only offer never stands in for the store
    assert not any("976759_555_9176907" in r["url"] for r in rep["count_reconciliation"])  # alias planned once
    assert not any("1234567" in r["url"] for r in rep["count_reconciliation"])           # CSV exclusion


def test_source_count_shortfall_blocks_publication(site):
    rep = _setup(site, _food(snacks_total=5), "", tolerance=0)   # fixture window is 4 products
    assert not rep["validation"]["ok"] and rep["published"] is None
    assert any("source-count reconciliation failed" in e and "Snacks" in e for e in rep["validation"]["errors"])


def _balloons(children=(), band_totals=(2, 2)):
    base = f"{c.BROWSE}2637_1042319"
    band = lambda lo, hi: f"{base}?min_price={lo}&max_price={hi}&{Q2[1:]}"
    return base, {
        f"{base}{Q2}": c.listing([c.item(401, "Latex Balloons, 12 in, 72 ct", "$4.97")], total=6, max_page=2,
                                 children=children),
        band(0, 5): c.listing([c.item(401, "Latex Balloons, 12 in, 72 ct", "$4.97"),
                               c.item(402, "Party Balloons, 10 ct", "$2.97")], total=band_totals[0],
                              max_page=1 if band_totals[0] <= 4 else 2),
        band(5, 100000): c.listing([c.item(403, "Helium Balloon Kit, 30 ct", "$24.97"),
                                    c.item(401, "Latex Balloons, 12 in, 72 ct", "$4.97")], total=band_totals[1]),
        **{f"https://www.walmart.com/ip/{n}/{i}": c.product(i, f"00000000{i}") for i, n in (
            (401, "Latex-Balloons,-12-in,-72-ct"), (402, "Party-Balloons,-10-ct"), (403, "Helium-Balloon-Kit,-30-ct"))},
    }


def test_merchandising_fan_out_is_price_partitioned(site):
    base, pages = _balloons(children=[("Shelf A", "2637_1042319_1"), ("Shelf B", "2637_1042319_2")])
    rep = _setup(site, pages, f"Walmart,Balloons,{base}?povid=x,Category + ALL subcategories,\n",
                 max_split_children=1, price_band_edges=[0, 5, 100000])
    assert rep["validation"]["ok"], rep["validation"]
    urls = [l["url"] for l in rep["listings"]]
    assert any("min_price=0&max_price=5" in u for u in urls) and not any("2637_1042319_1" in u for u in urls)
    assert rep["total_unique_records"] == 3 and rep["duplicate_records_in_output"] == 0


def test_price_filter_ignored_is_an_unresolved_route(site):
    """Walmart returning the full listing for a narrower price band must stop partitioning, not loop over bands."""
    base, pages = _balloons(band_totals=(6, 6))
    rep = _setup(site, pages, f"Walmart,Balloons,{base}?povid=x,Category + ALL subcategories,\n",
                 price_band_edges=[0, 5, 100000])
    assert not rep["validation"]["ok"] and rep["published"] is None
    assert any("unresolved route: Walmart ignores the price filter" in e for e in rep["validation"]["errors"])
    assert rep["fetch_stats"].get("requests", 0) < 12


def test_walmart_quirks_are_reported_not_hidden(site):
    """Walmart's own count drift (1 short), an empty price band and a count that Walmart never backs with products
    are reported as warnings; real shortfalls still fail (see test_source_count_shortfall_blocks_publication)."""
    pages = _food(snacks_total=3)                                             # 2 served of 3: within tolerance
    pages[f"{c.BROWSE}976759{Q2}"] = c.listing([c.item(900, "Root Sample Item, 1 ct", "$1.00")], total=50, max_page=2,
                                               children=[("Milk", "976759_9176907"), ("Snacks", "976759_976787"),
                                                         ("Empty", "976759_777"), ("Phantom", "976759_888")])
    pages[f"{c.BROWSE}976759_777{Q2}"] = c.listing([], total=0)
    pages[f"{c.BROWSE}976759_888{Q2}"] = c.listing([], total=2400, max_page=25)   # served 0, also on re-fetch
    rep = _setup(site, pages, "")
    assert rep["validation"]["ok"], rep["validation"]
    w = " | ".join(rep["validation"]["warnings"])
    assert "empty at source" in w and "Walmart count not backed by products" in w and "Phantom" in w
    assert rep["fetch_stats"]["requests"] < 20


def test_category_root_with_short_first_page_is_still_split(site):
    """A category root may show a short first page; with subcategories it is split, never treated as one listing."""
    pages = _food()
    pages[f"{c.BROWSE}976759{Q2}"] = c.listing([], total=50000, max_page=25, children=[
        ("Milk", "976759_9176907"), ("Snacks", "976759_976787")])
    rep = _setup(site, pages, "", full_page_min_items=20)
    assert rep["validation"]["ok"], rep["validation"]
    urls = {l["url"] for l in rep["listings"]}
    assert f"{c.BROWSE}976759" not in urls and f"{c.BROWSE}976759_9176907" in urls


def test_product_urls_are_clean():
    from wmscraper.parse.walmart import product_url
    u = "https://www.walmart.com/ip/Jordan-s-Syrup-375-mL/2897549699?filters=%5B%7B%22intent%22%5D&classType=REGULAR"
    assert product_url(u) == "https://www.walmart.com/ip/Jordan-s-Syrup-375-mL/2897549699"
    assert product_url("https://www.walmart.com/browse/976759?stores=100") == "https://www.walmart.com/browse/976759?stores=100"
