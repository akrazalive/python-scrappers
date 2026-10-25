from wmscraper.models import FIELD_ORDER, Record
from wmscraper.parse import deals
from wmscraper.parse.text import extract_weight, format_price, is_approximate_weight, is_private_label


def test_field_order_and_empty_strings():
    d = Record(product_title="X").to_ordered_dict()
    assert tuple(d) == FIELD_ORDER
    assert list(d)[-1] == "crawl_date"
    assert list(d)[17:19] == ["upc", "gupc"]
    assert all(isinstance(v, str) for v in d.values())
    assert d["gupc"] == "" and d["unit_price"] == ""
    assert "remarks" not in d and "gupc14" not in d


def test_pipeline_fields_forced_empty():
    r = Record(gupc="SHOULD-NOT-APPEAR", unit_price="1.00")
    d = r.to_ordered_dict()
    assert d["gupc"] == "" and d["unit_price"] == ""


def test_price_format():
    assert format_price("$3.5") == "3.50"
    assert format_price("$1,299.99") == "1299.99"
    assert format_price("Now $4.98") == "4.98"
    assert format_price("") == "" and format_price(None) == ""
    assert format_price("87 ¢") == "0.87"


def test_approx_weight():
    for t in ("Bananas, each (approx 0.4 lb)", "Approximately 2 lb", "avg wt 1.25 lb", "~1.5 lb", "Weight varies"):
        assert is_approximate_weight(t), t
    for t in ("Great Value Milk, 1 gal", "Lay's Chips, 8 oz", ""):
        assert not is_approximate_weight(t), t


def test_weight_extraction():
    assert extract_weight("Lay's Classic Potato Chips, 8 oz") == "8 oz"
    assert extract_weight("Fairlife 2% Milk, 52 fl oz") == "52 fl oz"
    assert extract_weight("Bounty Paper Towels, 12 Rolls") == "12 Rolls"


def test_private_label():
    brands = ("great value", "equate")
    assert is_private_label("Great Value", "Great Value Milk", brands)
    assert is_private_label("", "Equate Ibuprofen 200mg", brands)
    assert not is_private_label("Horizon", "Horizon Organic Milk", brands)


def test_volume_deals_preserve_wording_and_displayed_price_only():
    r = deals.classify(["2 for $5"])
    assert r.volume_description == "2 for $5" and r.volume_price == "5.00"
    r = deals.classify(["Buy 1, Get 1 Free"])
    assert r.volume_description == "Buy 1, Get 1 Free" and r.volume_price == ""  # BOGO: never calculated
    r = deals.classify(["Must buy 4 at $1.99 each"])
    assert r.volume_price == "1.99"
    r = deals.classify(["Mix or Match 5 for $10"])
    assert r.volume_price == "10.00"


def test_digital_deals():
    r = deals.classify(["Clip Coupon: Save $2"])
    assert r.digital_description == "Clip Coupon: Save $2" and r.digital_price == ""  # no final price displayed
    r = deals.classify(["$3.99 each with Digital Coupon"])
    assert r.digital_price == "3.99" and r.volume_description == ""
    r = deals.classify(["Save $5 when you buy 5 with Digital Coupon"])
    assert r.digital_description and not r.volume_description
    r = deals.classify(["20% off with clipped coupon"])
    assert r.digital_price == ""


def test_rewards_not_treated_as_digital_reduction():
    r = deals.classify(["Earn $1 Walmart Cash", "$2 cash back", "Manufacturer offer: mail-in rebate"])
    assert r.digital_description == "" and r.digital_price == "" and len(r.ignored_rewards) == 3


def test_volume_and_digital_together():
    r = deals.classify(["2 for $6", "Clip Coupon: Save $1"])
    assert r.volume_description == "2 for $6" and r.digital_description == "Clip Coupon: Save $1"


def test_pack_labels_are_not_promotions():
    for t in ("(6 pack)", "6 Pack", "12 ct, 2 Pack", "Family Size", "Value Pack", "Bulk 24 Count"):
        r = deals.classify([t])
        assert not r.volume_description and not r.digital_description, t
