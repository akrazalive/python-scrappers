"""v1.1.10 acceptance scope: Vernon Hills pickup, Crystal Lake diagnostic only."""
from pathlib import Path

from mscraper.config import load_settings
from mscraper.fetch import realtime_payload


ROOT = Path(__file__).resolve().parents[1]


def test_enabled_acceptance_location_and_disabled_diagnostic_are_explicit():
    settings = load_settings(ROOT / "config" / "settings.yaml")
    vernon = settings.location("marianos-502-vernon-hills")
    crystal = settings.location("marianos-544-crystal-lake")
    assert (vernon.enabled, vernon.store_id, vernon.zipcode, vernon.expected_address,
            vernon.expected_modality) == (True, "53100502", "60061", "1720 N Milwaukee", "PICKUP")
    assert (crystal.enabled, crystal.store_id, crystal.expected_modality) == (False, "53100544", "IN_STORE")


def test_realtime_payload_is_pinned_to_location_store_and_pickup():
    settings = load_settings(ROOT / "config" / "settings.yaml")
    location = settings.location("marianos-502-vernon-hills")
    payload = realtime_payload(settings, location, "https://www.marianos.com/search?query=milk")
    assert payload["store_id"] == "53100502"
    assert payload["fulfillment_type"] == "pickup"
    assert payload["query"] == "milk"


def test_bounded_scope_keeps_test1_cap_stop_rule_and_uses_vernon_for_test2():
    from mscraper import cli

    test1 = cli.BOUNDED_TESTS["test1"]
    test2 = cli.BOUNDED_TESTS["test2"]
    assert test1["total"] == 19
    assert sum(int(s[s.index("--max-requests") + 1]) for s in test1["steps"]) == 19
    assert test1["steps"][0][test1["steps"][0].index("--location") + 1] == "marianos-544-crystal-lake"
    assert test2["steps"][0][test2["steps"][0].index("--location") + 1] == "marianos-502-vernon-hills"
    assert "--no-publish" in test2["steps"][0]
