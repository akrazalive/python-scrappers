import math
from types import SimpleNamespace

import pytest

from wmscraper.runner import Run


def checker(price_text, numeric=None):
    run = Run.__new__(Run)
    run.loc = SimpleNamespace(store_id="1234", fulfillment="pickup", zipcode="72712")
    product = SimpleNamespace(
        item_id="901", location={"pickupStoreId": "1234", "storeIds": ["1234"], "intent": "PICKUP",
        "postalCode": "72712"}, fulfillment_options=[("PICKUP", "1234")],
        fulfillment_type="STORE", current_price=price_text, price_value=numeric)
    return run.canary_problems(product, "901")


@pytest.mark.parametrize("value", ["2 pack", "Only 2 left", "Save $2", "0", "-1.99", "2026-11-01"])
def test_unrelated_or_nonpositive_display_prices_fail(value):
    assert "no current price on the store offer" in checker(value)


def test_finite_positive_numeric_price_passes():
    assert "no current price on the store offer" not in checker("not a price", 3.49)


@pytest.mark.parametrize("value", [0, -1.99, math.inf, math.nan])
def test_nonfinite_or_nonpositive_numeric_price_fails(value):
    assert "no current price on the store offer" in checker("not a price", value)


def test_anchored_display_price_passes():
    assert "no current price on the store offer" not in checker("$3.49")
