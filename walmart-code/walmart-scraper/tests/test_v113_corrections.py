"""1.1.13 corrections from the client's static review of 1.1.12 (offline; synthetic fixtures, no provider request).

  1. search route keeps page / filter parameters, refuses what it cannot express; repeated page one is not traversal
  2. the four Walmart volume / digital offer fields are "" on every export path and validation enforces it
  3. listing price fields are whole-token validated before normalisation (collection, not only canaries)
  4. listing pages need the selected store + PICKUP + ZIP context; listing items need a store-bound offer chain
"""
from __future__ import annotations

import asyncio
import json

import pytest

import conftest as c
from wmscraper.config import load_settings
from wmscraper.fetch import FetchError, classic_payload
from wmscraper.models import WALMART_EMPTY_OFFER_FIELDS, Record, enforce_empty_fields
from wmscraper.parse.text import listing_price
from wmscraper.parse.walmart import page_location, next_data, parse_listing
from wmscraper.runner import Run
from wmscraper.storage import build_storage
from wmscraper.validate import validate_record_contract

SEARCH = "https://www.walmart.com/search?q=whole%20milk"
MILK = f"{c.BROWSE}976759_9176907{c.Q}"
MILK_P2 = f"{c.BROWSE}976759_9176907?page=2&{c.Q[1:]}"


def _fixtures(site):
    fx = site.parent.parent / "fixtures"
    return fx, json.loads((fx / "map.json").read_text())


def _run(site):
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    st = build_storage(s)
    return s, rep, st, st.get_json(f"test-store/runs/{rep['run_id']}/records.json")


def _events(s, rep, kind):
    run = Run(s, s.location("test-store"), run_id=rep["run_id"])
    return [json.loads(d) for k, d in run.ck.db.execute("SELECT kind, detail FROM events") if k == kind]


# ---------------------------------------------------------------- 1. search route: pagination / filter contract
def _payload(site, url):
    s = load_settings(site)
    return classic_payload(s, s.location("test-store"), url)


def test_search_pages_build_distinct_requests(site):
    p1, p2 = _payload(site, f"{SEARCH}&page=1"), _payload(site, f"{SEARCH}&page=2")
    assert p1 != p2
    assert (p1["start_page"], p2["start_page"]) == (1, 2) and "pages" not in p1  # no "pages" in the provider table
    assert _payload(site, SEARCH).get("start_page") is None  # no page parameter -> provider default (page 1)


def test_search_price_filters_are_carried(site):
    p = _payload(site, f"{SEARCH}&min_price=5&max_price=10&page=3&stores=1234")
    assert (p["min_price"], p["max_price"], p["start_page"]) == (5, 10, 3)
    assert p["store_id"] == "1234" and p["delivery_zip"] == "72712" and p["fulfillment_type"] == "pickup"


@pytest.mark.parametrize("extra", ["&facet=fulfillment_method%3APickup", "&sort=price_low", "&cat_id=976759",
                                   "&stores=9999", "&page=0", "&page=two", "&page=1&page=2", "&min_price=-1",
                                   "&min_price=5.5", "&page=2.0"])
def test_search_unsupported_or_invalid_parameters_are_refused(site, extra):
    with pytest.raises(FetchError) as exc:
        _payload(site, SEARCH + extra)
    assert exc.value.kind == "compat"  # terminal: refused, never retried, never silently dropped


def test_category_browse_does_not_use_search_route(site):
    p = _payload(site, f"{c.BROWSE}976759_9176907?page=2&stores=1234")
    assert p.get("source") != "walmart_search" and "page=2" in p.get("url", "")


def test_repeated_page_one_is_not_traversal(site):
    fx, m = _fixtures(site)
    (fx / m[MILK_P2]).write_text((fx / m[MILK]).read_text(encoding="utf-8"), encoding="utf-8")  # page 2 == page 1
    _s, rep, _st, _recs = _run(site)
    assert not rep["validation"]["ok"] and rep["published"] is None
    assert any("pagination not honoured" in e for e in rep["validation"]["errors"])


# ---------------------------------------------------------------- 2. Walmart volume / digital offer fields
def test_offer_fields_empty_on_fresh_records_despite_displayed_offers(site):
    _s, rep, st, recs = _run(site)   # fixtures show "2 for $9", "Clip Coupon", "$3.50 each with Digital Coupon"
    assert rep["validation"]["ok"], rep["validation"]
    for r in recs + st.get_json("test-store/latest/records.json"):
        assert all(r[f] == "" for f in WALMART_EMPTY_OFFER_FIELDS), r


def test_offer_fields_empty_on_carried_forward_records(site):
    s, rep, st, _ = _run(site)
    old = st.get_json("test-store/latest/records.json")
    for r in old:   # a previous dataset written by an older version that filled offer fields
        r.update(volume_deals_description="2 for $9", volume_deals_price="9.00",
                 digital_deals_description="Clip Coupon", digital_deals_price="1.00")
    st.put_json("test-store/latest/records.json", old)
    fx, m = _fixtures(site)
    (fx / m[f"{c.BROWSE}976759_976787{c.Q}"]).write_text(c.listing([
        c.item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz"),
        c.item(102, "Fairlife 2% Milk, 52 fl oz", "$4.98", was="$5.48")]), encoding="utf-8")
    (fx / m[f"{c.BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234"]).write_text(
        c.listing([], total=2), encoding="utf-8")
    _s, rep2, _st, recs = _run(site)
    assert rep2["availability"]["carried_forward"] == 1   # Doritos carried from the old dataset
    assert all(r[f] == "" for r in recs for f in WALMART_EMPTY_OFFER_FIELDS)


def test_offer_fields_contract_in_model_and_validation():
    rec = Record(volume_deals_description="2 for $5", digital_deals_price="1.00").to_ordered_dict()
    assert all(rec[f] == "" for f in WALMART_EMPTY_OFFER_FIELDS)
    for f in WALMART_EMPTY_OFFER_FIELDS:
        errors = validate_record_contract([{f: "x"}])
        assert any(f in e and "must be empty" in e for e in errors)
    assert all(r[f] == "" for r in enforce_empty_fields([{f: "x" for f in WALMART_EMPTY_OFFER_FIELDS}])
               for f in WALMART_EMPTY_OFFER_FIELDS)


# ---------------------------------------------------------------- 3. whole-token listing prices
@pytest.mark.parametrize("raw", ["Only 2 left", "Save $2", "2 for $5", "$3.48 - $5.00", "Now $4.98", "from $1.99",
                                 "$0.00", "0", "-1.00", "1.999", "$", "", None, True, float("nan"), float("inf"), 0, -3])
def test_listing_price_rejects_non_prices(raw):
    assert listing_price(raw) == ""


@pytest.mark.parametrize("raw,out", [("$4.98", "4.98"), ("4.98", "4.98"), ("$1,299.5", "1299.50"), (" $ 12 ", "12.00"),
                                     (8.96, "8.96"), (3, "3.00"), ("27 ¢", "0.27")])
def test_listing_price_accepts_whole_price_tokens(raw, out):
    assert listing_price(raw) == out


def test_collection_rejects_text_in_listing_price_fields(site):
    fx, m = _fixtures(site)
    (fx / m[MILK]).write_text(c.listing([
        c.item(101, "Great Value Whole Milk, 1 gal", "Only 2 left", ppm="2.7 ¢/fl oz"),
        c.item(102, "Fairlife 2% Milk, 52 fl oz", "$4.98", was="Save $2"),
        c.item(107, "Lactaid Milk, 64 fl oz", "2 for $5"),
        c.item(108, "Silk Almond Milk, 64 fl oz", "$3.48", was="$3.98"),
    ], max_page=2), encoding="utf-8")
    s, rep, _st, recs = _run(site)
    by = {r["product_title"]: r for r in recs}
    assert by["Great Value Whole Milk, 1 gal"]["regular_price"] == ""          # identity kept, no invented price
    assert (by["Fairlife 2% Milk, 52 fl oz"]["regular_price"], by["Fairlife 2% Milk, 52 fl oz"]["sale_price"]) == ("4.98", "")
    assert by["Lactaid Milk, 64 fl oz"]["regular_price"] == ""
    assert (by["Silk Almond Milk, 64 fl oz"]["regular_price"], by["Silk Almond Milk, 64 fl oz"]["sale_price"]) == ("3.98", "3.48")
    rejected = {(e["item_id"], e["value"]) for e in _events(s, rep, "price_rejected")}
    assert {("101", "Only 2 left"), ("102", "Save $2"), ("107", "2 for $5")} <= rejected


# ---------------------------------------------------------------- 4. listing context + store-bound offer chain
LOC = '"pageMetadata": {"location": {"storeId": "1234", "intent": "PICKUP", "postalCode": "72712"}}'


@pytest.mark.parametrize("replacement,problem", [
    ('"pageMetadata": {"location": {"storeId": "1234", "postalCode": "72712"}}', "intent -"),
    ('"pageMetadata": {"location": {"storeId": "1234", "intent": "SHIPPING", "postalCode": "72712"}}', "intent SHIPPING"),
    ('"pageMetadata": {"location": {"storeId": "1234", "intent": "PICKUP"}}', "postalCode -"),
    ('"pageMetadata": {"location": {"storeId": "1234", "intent": "PICKUP", "postalCode": "10001"}}', "postalCode 10001"),
    ('"pageMetadata": {"location": {"intent": "PICKUP", "postalCode": "72712"}}', "storeId -"),
    ('"contentLayout": {"pageMetadata": {"location": {"storeId": "9999", "intent": "PICKUP", "postalCode": "72712"}}}, '
     + LOC, "conflicting selected location"),
])
def test_listing_context_requires_store_pickup_and_zip(site, replacement, problem):
    fx, m = _fixtures(site)
    p = fx / m[MILK]
    html = p.read_text(encoding="utf-8")
    assert LOC in html
    p.write_text(html.replace(LOC, replacement), encoding="utf-8")
    s, rep, st, _ = _run(site)
    assert not rep["validation"]["ok"] and rep["published"] is None and st.get_json("test-store/latest/records.json") is None
    assert any("store context" in e for e in rep["validation"]["errors"])
    assert any(problem in pr for e in _events(s, rep, "store_mismatch") for pr in e["problems"])


def test_real_listing_location_shape_passes(site):
    """Shape of the selected location on archived real store-#100 listings (two agreeing blocks)."""
    loc = {"pickupStore": "1234", "deliveryStore": "1234", "intent": "PICKUP", "postalCode": "72712", "storeId": "1234"}
    data = {"props": {"pageProps": {"initialData": {"pageMetadata": {"location": loc},
                                                    "contentLayout": {"pageMetadata": {"location": loc}}}}}}
    got = page_location(next_data(c.page(data)))
    assert got["conflicts"] == []
    s = load_settings(site)
    assert Run(s, s.location("test-store")).context_problems(got) == []


def _items(site, stacks):
    s = load_settings(site)
    run = Run(s, s.location("test-store"))
    data = {"props": {"pageProps": {"initialData": {"searchResult": {"itemStacks": stacks, "paginationV2": {"maxPage": 1}},
                                                    "pageMetadata": {"location": {"storeId": c.STORE, "intent": "PICKUP",
                                                                                  "postalCode": c.ZIP}}}}}}
    return run, {it.item_id: it for it in parse_listing(c.page(data)).items}


def test_listing_items_need_store_bound_offer_chain(site):
    bound = c.item(1, "Bound Milk, 1 gal", "$3.48")
    conflicting = c.item(2, "Conflict Milk, 1 gal", "$3.48")
    conflicting["fulfillmentSummary"] = [{"fulfillment": "PICKUP", "storeId": c.STORE}, {"fulfillment": "PICKUP", "storeId": "5555"}]
    unbound = c.item(3, "Unbound Milk, 1 gal", "$3.48")
    unbound["fulfillmentSummary"] = []                                   # in stock, but no entry for any store
    unavailable = c.item(4, "Unavailable Milk, 1 gal", "$3.48", availability="OUT_OF_STOCK")
    shipped = c.item(5, "Shipping Stack Milk, 1 gal", "$3.48")           # STORE-typed, but in the shipping stack
    run, items = _items(site, [{"items": [bound, conflicting, unbound, unavailable]},
                               {"meta": {"fulfillmentIntent": "SHIPPING"}, "items": [shipped]}])
    reasons = {i: run._reject_reason(it) for i, it in items.items()}
    assert reasons == {"1": "", "2": "conflicting_store_offer", "3": "store_offer_unbound", "4": "",
                       "5": "shipping_context_not_store_offer"}
    assert items["4"].availability(c.STORE) == "out_of_stock"           # eligible unavailable identity preserved


def test_unavailable_store_item_identity_preserved_in_run(site):
    fx, m = _fixtures(site)
    (fx / m[f"{c.BROWSE}976759_976787{c.Q}"]).write_text(c.listing([
        c.item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz", availability="OUT_OF_STOCK"),
        c.item(203, "Doritos Nacho, 9.25 oz", "$4.98")]), encoding="utf-8")
    (fx / m[f"{c.BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234"]).write_text(
        c.listing([], total=1), encoding="utf-8")
    _s, rep, _st, recs = _run(site)
    assert rep["validation"]["ok"], rep["validation"]
    lays = next(r for r in recs if r["product_title"].startswith("Lay's"))
    assert lays["upc"] == "028400090858" and lays["regular_price"] == "4.28"
