"""Test fixtures.

SYNTHETIC DATA: the pages built here imitate the *shape* of Walmart's __NEXT_DATA__ so
the pipeline logic can be tested offline. They are not real Walmart data and are never
written to any output used for the contest or production.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STORE = "1234"
BROWSE = "https://www.walmart.com/browse/"
Q = "?stores=1234"   # listing params from settings.yaml, store-scoped
ZIP = "72712"
WM_SELLER = "F55CDC31AB754BB68FE0B39041159D63"


def page(data: dict) -> str:
    body = "<p>" + ("x" * 3000) + "</p>"  # real pages are large; tiny pages are treated as suspicious
    return f'<html><head></head><body>{body}<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


def item(i, name, price, *, was="", ppm="", seller=WM_SELLER, sponsored=False, fulfil="Pickup today",
         badges=None, brand="Acme", availability="IN_STOCK"):
    """Mirrors real Walmart item JSON: fulfillmentType + fulfillmentSummary carry the store and availability."""
    shipping_only = "shipping" in fulfil.lower()
    ftype = "MARKETPLACE" if seller != WM_SELLER else ("FC" if shipping_only else "STORE")
    summary = ([{"fulfillment": "DELIVERY", "storeId": "0"}] if ftype != "STORE"
               else [] if availability != "IN_STOCK" else [{"fulfillment": "PICKUP", "storeId": STORE}])
    return {
        "fulfillmentType": ftype, "fulfillmentSummary": summary,
        "availabilityStatusV2": {"value": availability},
        "__typename": "Product", "usItemId": str(i), "name": name, "canonicalUrl": f"/ip/{name.replace(' ', '-')}/{i}",
        "imageInfo": {"thumbnailUrl": f"https://i5.walmartimages.com/asr/{i}.jpeg"}, "brand": brand,
        "priceInfo": {"linePrice": price, "wasPrice": was, "unitPrice": ppm},
        "sellerName": "Walmart.com" if seller == WM_SELLER else "Some Marketplace LLC", "sellerId": seller,
        "isSponsoredFlag": sponsored,
        "fulfillmentBadgeGroups": [{"text": fulfil}],
        "badges": {"flags": [{"text": b} for b in (badges or [])]},
    }


def listing(items, max_page=1, store=STORE, total=None, children=()):
    """Mirrors Walmart's real listing JSON: store-scoped location + Departments navigation facet."""
    return page({"props": {"pageProps": {
        "initialData": {"searchResult": {"itemStacks": [{"items": items}], "paginationV2": {"maxPage": max_page},
                                         "aggregatedCount": len(items) if total is None else total},
                        "navigation": {"name": "Departments", "values": [{"id": i, "name": n} for n, i in children]},
                        "pageMetadata": {"location": {"storeId": store, "intent": "PICKUP", "postalCode": ZIP}}}}}})


def category_page(links, store=STORE):
    return page({"props": {"pageProps": {"initialData": {"modules": [{"name": n, "url": u} for n, u in links]},
                                         "locationContext": {"storeId": store}}}})


def product(i, upc, size="16 oz", store=STORE, seller=WM_SELLER, badges=None):
    return page({"props": {"pageProps": {"initialData": {"data": {
        "product": {"usItemId": str(i), "upc": upc, "brand": "Great Value" if i == 101 else "Acme",
                    "sellerId": seller, "sellerName": "Walmart.com",
                    "priceInfo": {"currentPrice": {"priceString": "$2.98"}},
                    "fulfillmentSummary": [{"fulfillment": "PICKUP", "storeId": store}],
                    "fulfillmentType": "STORE",
                    "location": {"storeIds": [store], "intent": "PICKUP", "postalCode": ZIP,
                                 "pickupLocation": {"storeId": store}},
                    "badges": {"flags": [{"text": b} for b in (badges or [])]}},
        "idml": {"specifications": [{"name": "Size", "value": size}]}}}}}})


def store_page(store=STORE, zipcode=ZIP):
    return page({"props": {"pageProps": {"initialData": {"store": {
        "id": store, "displayName": "Bentonville Supercenter",
        "address": {"addressLineOne": "406 S Walton Blvd", "city": "Bentonville", "state": "AR", "postalCode": zipcode}}}}}})


@pytest.fixture
def site(tmp_path):
    """Writes a synthetic mini-site + config and returns the settings path."""
    fx = tmp_path / "fixtures"
    fx.mkdir()
    pages = {
        f"https://www.walmart.com/store/{STORE}": store_page(),
        # Food root: more products than the page window -> split into Departments children.
        # "Recipes" is excluded by the CSV note, "Shop All Foods" by skip patterns, the grandchild is not direct.
        f"{BROWSE}976759{Q}": listing([item(900, "Root Sample Item, 1 ct", "$1.00")], total=5000, children=[
            ("Milk", "976759_9176907"), ("Snacks", "976759_976787"), ("Recipes", "976759_1234567"),
            ("Shop All Foods", "976759_5555555"), ("Whole milk", "976759_9176907_4405816")]),
        # Walmart's available-store-assortment count for the root (pickup facet): above the store window -> split
        f"{BROWSE}976759?facet=fulfillment_method%3APickup&stores=1234": listing(
            [item(900, "Root Sample Item, 1 ct", "$1.00")], total=3000),
        # Walmart's available-store counts per listing (reconciliation floors)
        f"{BROWSE}976759_9176907?facet=fulfillment_method%3APickup&stores=1234": listing([], total=4),
        f"{BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234": listing([], total=4),
        f"{BROWSE}976759_9176907{Q}": listing([
            item(101, "Great Value Whole Milk, 1 gal", "$3.48", ppm="2.7 ¢/fl oz"),
            item(102, "Fairlife 2% Milk, 52 fl oz", "$4.98", was="$5.48", ppm="9.6 ¢/fl oz", badges=["2 for $9"]),
            item(103, "Sponsored Oat Milk, 64 fl oz", "$3.98", sponsored=True),
            item(104, "Imported Milk Powder 2 lb", "$19.99", seller="ABC123"),
            item(105, "Shipping Only Milk 12 pack", "$29.99", fulfil="Free shipping, arrives in 3+ days"),
        ], max_page=2),
        f"{BROWSE}976759_9176907?page=2&{Q[1:]}": listing([
            item(106, "Horizon Organic Milk, 0.5 gal", "$4.68", ppm="7.3 ¢/fl oz", badges=["Clip Coupon: Save $1.00"]),
            item(101, "Great Value Whole Milk, 1 gal", "$3.48", ppm="2.7 ¢/fl oz"),  # pagination overlap
        ], max_page=2),
        f"{BROWSE}976759_976787{Q}": listing([
            item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz", badges=["$3.50 each with Digital Coupon"]),
            item(202, "Bananas, each (approx 0.4 lb)", "$0.27"),
            item(203, "Doritos Nacho, 9.25 oz", "$4.98", badges=["Buy 1, Get 1 Free", "Earn $1 Walmart Cash"]),
            item(102, "Fairlife 2% Milk, 52 fl oz", "$4.98", was="$5.48", ppm="9.6 ¢/fl oz", badges=["2 for $9"]),  # repeated category appearance
        ]),
    }
    for i, upc in ((101, "078742351865"), (102, "811620021166"), (103, "000000000103"), (105, "000000000105"),
                   (106, "742365004148"), (201, "028400090858"), (203, "028400443494")):
        name = {101: "Great-Value-Whole-Milk,-1-gal", 102: "Fairlife-2%-Milk,-52-fl-oz", 103: "Sponsored-Oat-Milk,-64-fl-oz",
                105: "Shipping-Only-Milk-12-pack", 106: "Horizon-Organic-Milk,-0.5-gal", 201: "Lay's-Classic-Chips,-8-oz",
                203: "Doritos-Nacho,-9.25-oz"}[i]
        pages[f"https://www.walmart.com/ip/{name}/{i}"] = product(i, upc, size={101: "1 gal", 102: "52 fl oz"}.get(i, "8 oz"))
    pages[f"https://www.walmart.com/ip/101"] = product(101, "078742351865")
    mapping = {}
    for n, (url, html) in enumerate(pages.items()):
        (fx / f"p{n}.html").write_text(html, encoding="utf-8")
        mapping[url] = f"p{n}.html"
    (fx / "map.json").write_text(json.dumps(mapping), encoding="utf-8")

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "categories.csv").write_text(
        "Retailer,Category (Auto),URL,Scope,Notes\n"
        "Walmart,Food,https://www.walmart.com/cp/food/976759?povid=x,Category + ALL subcategories,Exclude 'Shop All Foods' and 'Recipes' subcategories\n",
        encoding="utf-8")
    (cfg / "locations.yaml").write_text(yaml.safe_dump({"locations": [
        {"key": "test-store", "store_id": STORE, "zipcode": ZIP, "canary_items": ["101"]}]}), encoding="utf-8")
    (cfg / "private_label_brands.txt").write_text("Great Value\nEquate\n", encoding="utf-8")
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    settings["fetch"].update(provider="fixture", fixture_dir=str(fx), min_delay_seconds=0, max_delay_seconds=0,
                             backoff_base_seconds=0, max_retries=0)
    settings["output"]["local_dir"] = str(tmp_path / "out")
    # these fixtures exercise the legacy store_count planner; tests/test_source_count.py covers production mode
    settings["crawl"].update(coverage="store_count", listing_params={"stores": "{store_id}"})
    settings["validation"]["thin_listing_ratio"] = 0.7
    (cfg / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    return cfg / "settings.yaml"
