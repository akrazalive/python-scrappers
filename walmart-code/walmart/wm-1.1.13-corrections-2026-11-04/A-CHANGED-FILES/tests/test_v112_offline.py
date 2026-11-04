"""Offline acceptance checks for the 1.1.12 Walmart handoff (route test corrected in 1.1.13)."""
from __future__ import annotations

import json
from pathlib import Path

from wmscraper.config import load_settings
from wmscraper.fetch import classic_payload
from wmscraper.models import WALMART_EMPTY_OFFER_FIELDS
from wmscraper.validate import validate_record_contract


def test_walmart_search_route_builds_store_pinned_payload(site):
    settings = load_settings(str(site))
    location = settings.location("test-store")
    payload = classic_payload(settings, location, "https://www.walmart.com/search?q=whole%20milk&page=2")
    # 1.1.12 dropped page=2 here; the page is now carried as start_page
    assert payload == {
        "source": "walmart_search",
        "query": "whole milk",
        "store_id": "1234",
        "delivery_zip": "72712",
        "fulfillment_type": "pickup",
        "start_page": 2,
    }


def test_500_product_fixture_passes_offline_contract():
    """walmart-500-demo.json is an existing OFFLINE fixture (records retained from the earlier v1.1.0 run data).
    It is offline evidence of record shape only - not a genuine 500-product demonstration."""
    path = Path(__file__).parents[1] / "walmart-500-demo.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == 500
    assert all(record["gupc"] == "" and record["unit_price"] == "" for record in records)
    assert all(record[f] == "" for record in records for f in WALMART_EMPTY_OFFER_FIELDS)
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
