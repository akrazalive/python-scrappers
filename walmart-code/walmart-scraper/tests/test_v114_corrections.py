"""1.1.14 correction from the client's static review of 1.1.13 (offline; synthetic fixtures, no provider request).

  page_location compared secondary location blocks on storeId / intent / postalCode only, so a secondary block
  naming another pickupStore was not a conflict. Every block's pickupStore is now checked against the page's
  pickup store (or its selected storeId when the first block names none).
"""
from __future__ import annotations

import pytest

import conftest as c
from test_v113_corrections import LOC, MILK, _events, _fixtures, _run
from wmscraper.config import load_settings
from wmscraper.parse.walmart import next_data, page_location
from wmscraper.runner import Run


def _location(*blocks):
    """initialData with the given location dicts at the explicit selected-location paths, in page_location order."""
    initial: dict = {}
    for path, loc in zip((("pageMetadata",), ("contentLayout", "pageMetadata"), ("searchResult", "pageMetadata")),
                         blocks):
        node = initial
        for k in path:
            node = node.setdefault(k, {})
        node["location"] = loc
    return page_location(next_data(c.page({"props": {"pageProps": {"initialData": initial}}})))


def _problems(site, location):
    s = load_settings(site)
    return Run(s, s.location("test-store")).context_problems(location)


BASE = {"storeId": c.STORE, "intent": "PICKUP", "postalCode": c.ZIP}


@pytest.mark.parametrize("primary,secondary", [
    ({**BASE, "pickupStore": c.STORE}, {**BASE, "pickupStore": "9999"}),   # the reviewer's case (100 vs 9999)
    (BASE, {**BASE, "pickupStore": "9999"}),                                # first block names no pickupStore
])
def test_contradicting_secondary_pickup_store_is_a_conflict(site, primary, secondary):
    got = _location(primary, secondary)
    assert [f["pickupStore"] for f in got["conflicts"]] == ["9999"]
    probs = _problems(site, got)
    assert any("conflicting selected location at initialData.contentLayout.pageMetadata.location" in p for p in probs)


def test_contradicting_third_block_pickup_store_is_a_conflict(site):
    got = _location({**BASE, "pickupStore": c.STORE}, {**BASE, "pickupStore": c.STORE}, {**BASE, "pickupStore": "9999"})
    assert [f["path"] for f in got["conflicts"]] == ["initialData.searchResult.pageMetadata.location"]
    assert _problems(site, got)


@pytest.mark.parametrize("blocks", [
    ({**BASE, "pickupStore": c.STORE}, {**BASE, "pickupStore": c.STORE}),  # archived real shape: both agree
    ({**BASE, "pickupStore": c.STORE}, BASE),                              # secondary names no pickupStore
    (BASE, {**BASE, "pickupStore": c.STORE}),                              # only the secondary names it, correctly
    (BASE, BASE),
])
def test_agreeing_pickup_store_blocks_pass(site, blocks):
    got = _location(*blocks)
    assert got["conflicts"] == []
    assert _problems(site, got) == []


def test_contradicting_secondary_pickup_store_fails_the_run(site):
    """Full offline collection: the listing with the contradicting block fails validation and nothing is published."""
    fx, m = _fixtures(site)
    p = fx / m[MILK]
    html = p.read_text(encoding="utf-8")
    assert LOC in html
    primary = LOC.replace('"postalCode": "72712"}', f'"postalCode": "72712", "pickupStore": "{c.STORE}"}}')
    secondary = ('"contentLayout": {"pageMetadata": {"location": {"storeId": "1234", "intent": "PICKUP", '
                 '"postalCode": "72712", "pickupStore": "9999"}}}')
    p.write_text(html.replace(LOC, f"{secondary}, {primary}"), encoding="utf-8")
    s, rep, st, _ = _run(site)
    assert not rep["validation"]["ok"] and rep["published"] is None and st.get_json("test-store/latest/records.json") is None
    assert any("store context" in e for e in rep["validation"]["errors"])
    assert any("conflicting selected location" in pr and "9999" in pr
               for e in _events(s, rep, "store_mismatch") for pr in e["problems"])


def test_unavailable_identity_kept_with_agreeing_pickup_store_blocks(site):
    """The stricter check does not drop eligible unavailable store items on a page whose blocks agree."""
    fx, m = _fixtures(site)
    p = fx / m[f"{c.BROWSE}976759_976787{c.Q}"]
    html = c.listing([c.item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz", availability="OUT_OF_STOCK"),
                      c.item(203, "Doritos Nacho, 9.25 oz", "$4.98")])
    both = LOC.replace('"postalCode": "72712"}', f'"postalCode": "72712", "pickupStore": "{c.STORE}"}}')
    assert LOC in html
    p.write_text(html.replace(LOC, f'"contentLayout": {{{both}}}, {both}'), encoding="utf-8")
    (fx / m[f"{c.BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234"]).write_text(
        c.listing([], total=1), encoding="utf-8")
    _s, rep, _st, recs = _run(site)
    assert rep["validation"]["ok"], rep["validation"]
    lays = next(r for r in recs if r["product_title"].startswith("Lay's"))
    assert lays["upc"] == "028400090858" and lays["regular_price"] == "4.28"
