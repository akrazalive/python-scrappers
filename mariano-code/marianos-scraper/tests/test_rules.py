from conftest import page

from mscraper import deals, parse
from mscraper.models import FIELD_ORDER, Record
from mscraper.text import format_price, is_approximate, is_store_brand


def test_field_order_and_empty_pipeline_fields():
    d = Record(gupc="x", unit_price="y").to_ordered_dict()
    assert tuple(d) == FIELD_ORDER and d["gupc"] == "" and d["unit_price"] == "" and list(d)[-1] == "crawl_date"


def test_price_format():
    assert format_price("USD 4.99") == "4.99"
    assert format_price("$1,299.5") == "1299.50"
    assert format_price("") == "" and format_price(None) == ""


def test_approximate_weight():
    assert is_approximate("approx 1.5 lb") and is_approximate("Approximately 2 lb") and is_approximate("about $10.39 each")
    assert not is_approximate("16 oz") and not is_approximate("1/2 gal")


def test_store_brand():
    brands = ("kroger", "simple truth", "roundy's")
    assert is_store_brand("Roundy's", "Roundy's® Select 2% Milk", brands)
    assert is_store_brand("Simple Truth", "x", brands)
    assert not is_store_brand("Horizon Organic", "Horizon milk", brands)


def test_deal_classification_and_prices_never_calculated():
    d = deals.classify([deals.Offer("Save $1 each when you buy 5 or more", "MEGA_EVENT")])
    assert d.volume_description == "Save $1 each when you buy 5 or more" and d.volume_price == ""
    assert deals.classify([deals.Offer("2 for $5.00")]).volume_price == "5.00"
    assert deals.classify([deals.Offer("Buy 1, Get 1 Free")]).volume_price == ""          # BOGO: no invented price
    assert deals.classify([deals.Offer("Must buy 4 at $1.99 each")]).volume_price == "1.99"
    dg = deals.classify([deals.Offer("$3.99 each with Digital Coupon")])
    assert dg.digital_description and dg.digital_price == "3.99" and not dg.volume_description
    assert deals.classify([deals.Offer("Clip Coupon: Save $2")]).digital_price == ""      # "Save $2" -> no final price
    assert deals.classify([deals.Offer("Save $5 when you buy 5 with Digital Coupon")]).digital_description  # digital wins
    assert deals.classify([deals.Offer("Get 4x POINTS")]).ignored                          # points are not a price


def test_state_store_and_department_shelves():
    st = parse.extract_state(page("department_meat_store544.html.gz"))
    s = parse.store_info(st)
    assert (s.location_id, s.zipcode) == ("53100544", "60014") and "105 Northwest Hwy" in s.full_address
    shelves = parse.department_shelves(st, "meat")
    names = [x.name for x in shelves]
    assert "Chicken" in names and "Pork & Ham" in names and parse.department_code(shelves) == "05"


def test_product_mapping_ppm_sale_and_weight_exclusion():
    sp = parse.search_page(parse.extract_state(page("search_beef_store544.html.gz")))
    ctx = dict(store_id="53100544", zipcode="60014", store_name="Marianos Crystal Lake", store_location="x", store_logo="",
               brands=("kroger", "simple truth", "private selection"), category="Meat", sub_category="Beef",
               base_url="https://www.marianos.com", crawl_date="2026-10-21")
    mapped = [parse.map_product(sp.products[u], ctx) for u in sp.upcs]
    reasons = {m.reason for m in mapped}
    assert "approximate_weight" in reasons                     # sold-by-weight "about $X each" items excluded
    for m in mapped:
        if m.record:
            r = m.record
            assert tuple(r) == FIELD_ORDER and r["upc"] and r["regular_price"] and r["ppm"].startswith("$")
            assert r["gupc"] == "" and r["unit_price"] == "" and r["url"].startswith("https://www.marianos.com/p/")


def test_sale_price_uses_displayed_promo_ppm():
    sp = parse.search_page(parse.extract_state(page("search_milk_store544.html.gz")))
    ctx = dict(store_id="53100544", zipcode="", store_name="", store_location="", store_logo="", brands=(),
               category="Dairy", sub_category="Milk", base_url="https://www.marianos.com", crawl_date="2026-10-21")
    r = parse.map_product(sp.products["0001111050438"], ctx).record
    assert (r["regular_price"], r["sale_price"], r["ppm"]) == ("4.99", "3.99", "$0.06/fl oz")


def test_upstream_failure_is_not_an_empty_page():
    import pytest

    with pytest.raises(parse.PageError) as e:
        parse.search_page(parse.extract_state(page("search_upstream_failure.html.gz")))
    assert e.value.kind == "upstream"


def test_challenge_page_detected():
    import pytest

    with pytest.raises(parse.PageError):
        parse.extract_state("<html><title>Access Denied</title>Reference #18.1</html>")


def test_coupons_page():
    cps = parse.coupons(page("coupons_page_store544.html.gz"))
    assert len(cps) >= 10 and all(c["coupon_id"] and c["description"] for c in cps)


def test_query_expansion_terms_stay_in_shelf():
    sp = parse.search_page(parse.extract_state(page("search_beef_store544.html.gz")))
    terms = set()
    for u in sp.upcs:
        terms.update(parse.expansion_terms(sp.products[u], "05001", "Beef"))
    assert terms and any(t.endswith(" Beef") for t in terms)          # brand + shelf noun, e.g. "Kroger Beef"
    assert not any("Chicken" in t for t in terms)                    # only names inside the shelf's taxonomy
