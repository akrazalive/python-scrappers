"""Offline acceptance checks for the 1.1.12 Walmart handoff."""
from __future__ import annotations

import json
from pathlib import Path

from wmscraper.fetch import classic_payload
from wmscraper.validate import validate_record_contract


def test_walmart_search_route_builds_store_pinned_payload(site):
    settings = __import__("wmscraper.config", fromlist=["load_settings"]).load_settings(str(site))
    settings.raw["fetch"]["oxylabs"]["search_payload"] = {
        "source": "walmart_search",
        "query": "{query}",
        "store_id": "{store_id}",
        "delivery_zip": "{zipcode}",
        "fulfillment_type": "pickup",
    }
    location = settings.location("test-store")
    payload = classic_payload(settings, location, "https://www.walmart.com/search?q=whole%20milk&page=2")
    assert payload == {
        "source": "walmart_search",
        "query": "whole milk",
        "store_id": "1234",
        "delivery_zip": "72712",
        "fulfillment_type": "pickup",
    }


def test_500_product_fixture_is_complete_and_not_published_by_demo():
    path = Path(__file__).parents[1] / "walmart-500-demo.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == 500
    assert all(record["gupc"] == "" and record["unit_price"] == "" for record in records)
    assert all(not validate_record_contract([record]) for record in records)


def test_identity_and_offer_validation_blocks_publication():
    record = {
        "upc": "not-a-upc",
        "ppm": "computed from price",
        "regular_price": "",
        "sale_price": "4.98",
    }
    errors = validate_record_contract([record])
    assert any("UPC" in error for error in errors)
    assert any("PPM" in error for error in errors)
    assert any("regular-price offer" in error for error in errors)
