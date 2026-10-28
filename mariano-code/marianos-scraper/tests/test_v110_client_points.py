"""v1.1.0 – tests for the client's corrections (#69 review): retention, weight rule, coverage reconciliation,
offer terms, provenance. All offline, on real saved marianos.com responses (see conftest.PAGES)."""
import asyncio
import copy
import gzip
import json

from conftest import FIX, PAGES, page

from mscraper import coverage, deals, parse, retention
from mscraper.fetch import FixtureFetcher
from mscraper.models import FIELD_ORDER
from mscraper.runner import Runner

CTX = dict(store_id="53100544", zipcode="60014", store_name="Marianos Crystal Lake", store_location="x", store_logo="",
           brands=("kroger", "simple truth", "private selection"), category="Meat", sub_category="Beef",
           base_url="https://www.marianos.com", crawl_date="2026-10-24", approx_price_wording=True)


def _beef():
    return parse.search_page(parse.extract_state(page("search_beef_store544.html.gz")))


def _weight_product(sp):
    return next(sp.products[u] for u in sp.upcs if sp.products[u]["data"]["price"].get("sellBy") == "Weight")


def _unit_product(sp):
    return next(sp.products[u] for u in sp.upcs if sp.products[u]["data"]["price"].get("sellBy") == "Unit")


# ------------------------------------------------------------------ 1. retention
def test_product_without_store_price_is_kept_with_empty_price_fields():
    p = copy.deepcopy(_unit_product(_beef()))
    p["data"]["price"]["storePrices"].pop("regular")
    p["data"]["price"]["storePrices"].pop("promo", None)
    m = parse.map_product(p, CTX)
    assert m.reason == "kept" and m.availability == "no_store_price"
    r = m.record
    assert tuple(r) == FIELD_ORDER and r["regular_price"] == "" and r["sale_price"] == "" and r["ppm"] == ""
    assert r["upc"] and r["product_title"]


def test_product_without_upc_keeps_product_id_out_of_the_upc_field():
    p = copy.deepcopy(_unit_product(_beef()))
    pid = p["data"]["id"]
    p["data"]["item"].pop("upc")
    m = parse.map_product(p, CTX)
    assert m.reason == "kept" and m.record["upc"] == ""                      # never filled with an item id
    assert m.identity == f"product:{pid}" and m.identity_source == "data.id" and m.source_product_id == pid
    assert pid in m.record["url"]                                             # source-backed identity kept in the URL


def test_upc_only_from_item_upc_and_equals_product_key_in_real_data():
    sp = _beef()
    for u in sp.upcs:
        p = sp.products[u]
        assert p["data"]["item"]["upc"] == u == p["data"]["id"]                # evidence: item.upc = key = data.id
        assert "id" not in p                                                   # top-level prod.id does not exist
        m = parse.map_product(p, CTX)
        assert m.identity_source == "item.upc"


def test_carry_forward_keeps_missing_products_with_their_own_dates():
    prev = {"A": {"upc": "A", "crawl_date": "2026-10-21"}, "B": {"upc": "B", "crawl_date": "2026-10-21"}}
    prev_obs = {"A": {"status": "fresh", "last_observed": "2026-10-21", "first_observed": "2026-10-14", "last_observed_run": "r1"},
                "B": {"status": "fresh", "last_observed": "2026-10-21", "last_observed_run": "r1"}}
    fresh = {"A": {"upc": "A", "crawl_date": "2026-10-24"}}
    recs, obs = retention.carry_forward(fresh, {"A": {}}, prev, prev_obs, "r2", "2026-10-24")
    assert set(recs) == {"A", "B"} and recs["B"]["crawl_date"] == "2026-10-21"   # carried row keeps its observation date
    assert obs["A"]["status"] == "fresh" and obs["A"]["first_observed"] == "2026-10-14"
    assert obs["B"]["status"] == "carried" and obs["B"]["last_observed"] == "2026-10-21" and obs["B"]["carried_since"] == "2026-10-24"
    _, obs3 = retention.carry_forward({}, {}, recs, obs, "r3", "2026-10-27")
    assert obs3["B"]["carried_since"] == "2026-10-24"                          # kept indefinitely, first carry date kept


# ------------------------------------------------------------------ 2. weight rule
def test_sold_by_weight_alone_never_excludes():
    p = copy.deepcopy(_weight_product(_beef()))
    reg = p["data"]["price"]["storePrices"]["regular"]
    reg["defaultDescription"] = "$12.99"                                       # exact price, no estimate wording
    m = parse.map_product(p, CTX)
    assert m.reason == "kept" and m.sell_by == "Weight" and m.record["weight"] == "1 lb"


def test_estimated_weight_wording_excludes_with_trigger_recorded():
    m = parse.map_product(_weight_product(_beef()), CTX)
    assert m.reason == "approximate_weight"
    assert m.trigger[0] == "storePrices.regular.defaultDescription" and m.trigger[1].lower().startswith("about $")


def test_title_count_phrase_is_not_an_approximate_weight():
    p = copy.deepcopy(_unit_product(_beef()))
    p["data"]["item"]["description"] = "Beef Sirloin Tip Steak Thin (About 3 Steaks per Pack) Family Pack"
    assert parse.map_product(p, CTX).reason == "kept"


def test_family_pack_label_is_not_a_volume_deal():
    p = copy.deepcopy(_unit_product(_beef()))
    p["data"]["item"]["description"] = "Kroger Ground Beef Family Pack"
    p["data"]["item"]["customerFacingSize"] = "3 lb Value Pack"
    r = parse.map_product(p, CTX).record
    assert r["volume_deals_description"] == "" and r["weight"] == "3 lb Value Pack"   # source size preserved


# ------------------------------------------------------------------ 4. offers
def test_volume_offer_keeps_wording_and_complete_terms_and_digital_stays_separate():
    sp = parse.search_page(parse.extract_state(page("search_cereal_coupons_store544.html.gz")))
    u = next(u for u in sp.upcs if (sp.products[u]["data"].get("offers") or []))
    m = parse.map_product(sp.products[u], {**CTX, "category": "Breakfast", "sub_category": "Cereal"})
    d = m.record["volume_deals_description"]
    assert d.startswith("Save $1 each when you buy 5 or more (valid 2026-")
    assert "applies to: in-store" in d and m.record["volume_deals_price"] == ""         # never calculated
    assert m.record["digital_deals_description"] == ""
    off = m.offers[0]
    assert off["kind"] == "volume" and off["template"] == "MEGA_EVENT" and off["valid_from"] and off["valid_to"]


def test_digital_and_volume_never_merge():
    r = deals.classify([deals.Offer("2 for $5.00", "PROMO_NFOR", "5.00", valid_to="2026-10-28T03:59:59Z"),
                        deals.Offer("$3.99 each with Digital Coupon", "DIGITAL_COUPON", valid_to="2026-11-14")])
    assert r.volume_description == "2 for $5.00 (valid until 2026-10-28T03:59:59Z)" and r.volume_price == "5.00"
    assert r.digital_description == "$3.99 each with Digital Coupon (valid until 2026-11-14)" and r.digital_price == "3.99"


# ------------------------------------------------------------------ 3. coverage reconciliation
def test_coverage_reconciliation_complete_and_gap():
    L = lambda url, total, status="done", parent="": {"category": "Batteries", "sub_category": "Batteries", "query": url,
                                                       "url": url, "status": status, "reported_total": total, "parent": parent}
    I = lambda url, prefix, n: [{"url": url, "upc": f"{prefix}{i}"} for i in range(n)]
    listings = [L("q", 30), L("q&b=A", 20, parent="q"), L("q&b=B", 10, parent="q"), L("r", 50), L("c", 1000)]
    items = (I("q", "A", 14) + I("q", "B", 10) + I("q&b=A", "A", 20) + I("q&b=B", "B", 10) + I("r", "R", 24)
             + I("c", "C", 24))
    rep = coverage.reconcile(listings, items)
    q = {x["query"]: x for x in rep["queries"]}
    assert q["q"]["complete"] and q["q"]["gap"] == 0 and q["q"]["unexplained_gap"] == 0          # proven via slices
    assert not q["r"]["complete"] and q["r"]["gap"] == 26 and q["r"]["unexplained_gap"] == 0
    assert [g["reason"] for g in q["r"]["gap_items"]] == ["brands_not_discovered"]                 # explained, not hidden
    assert not q["c"]["complete"] and q["c"]["reported_total_is_capped"]
    assert any(g["reason"] == "reported_total_capped" for g in q["c"]["gap_items"]) and q["c"]["unexplained_gap"] == 0
    assert rep["summary"]["unexplained_gap"] == 0 and rep["summary"]["queries_complete"] == 1


def test_coverage_keeps_changing_counts_and_detects_unexplained_gaps():
    L = lambda url, total, parent="": {"category": "X", "sub_category": "Y", "query": url, "url": url, "status": "done",
                                       "reported_total": total, "parent": parent}
    ledger = [{"kind": "search_query", "url": "q", "reported_total": 30, "response_sha256": "s1"},
              {"kind": "search_query", "url": "q", "reported_total": 32, "response_sha256": "s2"}]
    rep = coverage.reconcile([L("q", 30)], [{"url": "q", "upc": str(i)} for i in range(24)], ledger)
    q = rep["queries"][0]
    assert [o["reported_total"] for o in q["observed_totals"]] == [30, 32] and q["reported_total"] == 32   # both kept
    assert any(g["reason"] == "site_count_inconsistent" for g in q["gap_items"]) and not q["complete"]
    # slices that claim full reads but overlap each other leave products unaccounted for -> unexplained, must surface
    bad = coverage.reconcile([L("p", 20), L("p&b=A", 10, "p"), L("p&b=B", 10, "p")],
                             [{"url": "p&b=A", "upc": str(i)} for i in range(10)] + [{"url": "p&b=B", "upc": str(i)} for i in range(10)])
    assert bad["summary"]["unexplained_gap"] == 10 and not bad["queries"][0]["complete"]


# ------------------------------------------------------------------ 5. provenance + pipeline
def test_run_writes_ledger_evidence_hashes_and_sidecars(settings, location, storage, tmp_path, fetcher):
    r = Runner(settings, location, storage, tmp_path / "state", fetcher=fetcher)
    res = asyncio.run(r.run())
    assert res["status"] == "published", res["errors"]
    ledger = r.ck.table("ledger")
    assert ledger and all(row["response_sha256"] and row["store_location_id"] == "53100544" for row in ledger)
    first = next(x for x in ledger if x["kind"].startswith("search"))
    ev = json.loads(gzip.decompress((r.dir / first["evidence_file"]).read_bytes()))
    assert ev["response_sha256"] == first["response_sha256"] and ev["products"]          # price-bearing source kept
    rep = json.loads((r.dir / "report.json").read_text(encoding="utf-8"))
    assert rep["provenance"]["start"]["code_sha256"] == rep["provenance"]["finish"]["code_sha256"]
    assert set(rep["provenance"]["start"]["config_sha256"]) == {"settings.yaml", "categories.csv", "locations.yaml",
                                                                 "private_label_brands.txt"}
    for name in ("observations.json", "coverage.json", "exclusions.json", "ledger.json"):
        assert (r.dir / name).exists() and (storage.root / "test-544" / "runs" / r.run_id / name).exists()
    assert (storage.root / "test-544/latest/observations.json").exists()
    obs = json.loads((r.dir / "observations.json").read_text(encoding="utf-8"))
    assert all(o["response_sha256"] in {x["response_sha256"] for x in ledger} for o in obs.values() if o["status"] == "fresh")


def test_second_run_carries_products_it_did_not_see(settings, location, storage, tmp_path):
    f1 = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    r1 = Runner(settings, location, storage, tmp_path / "state", fetcher=f1)
    assert asyncio.run(r1.run())["status"] == "published"
    n1 = len(json.loads((storage.root / "test-544/latest/records.json").read_text(encoding="utf-8")))
    # a later run where the beef shelf only shows milk products (nothing of the shelf) -> beef rows must be carried
    pages = dict(PAGES)
    pages["/search?"] = "search_milk_store544.html.gz"
    f2 = FixtureFetcher(settings, location, fixtures=pages, root=str(FIX))
    settings.raw["validation"]["yield_drop_threshold"] = 0.0
    r2 = Runner(settings, location, storage, tmp_path / "state", fetcher=f2)
    res2 = asyncio.run(r2.run())
    obs = json.loads((r2.dir / "observations.json").read_text(encoding="utf-8"))
    recs = json.loads((r2.dir / "records.json").read_text(encoding="utf-8"))
    carried = [k for k, o in obs.items() if o["status"] == "carried"]
    assert carried and len(recs) >= n1                                        # nothing disappeared
    assert all(o["last_observed_run"] == r1.run_id for k, o in obs.items() if o["status"] == "carried")
    assert res2["status"] in ("published", "validation_failed")


def test_resume_records_provenance_of_each_session(settings, location, storage, tmp_path):
    f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    f.budget = 6
    r = Runner(settings, location, storage, tmp_path / "state", fetcher=f)
    try:
        asyncio.run(r.run())
    except Exception:
        pass
    f2 = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    r2 = Runner(settings, location, storage, tmp_path / "state", run_id=r.run_id, fetcher=f2)
    r2.ck.db.execute("DELETE FROM meta WHERE k='final_status'")
    r2.ck.db.commit()
    res = asyncio.run(r2.run())
    rep = json.loads((r2.dir / "report.json").read_text(encoding="utf-8"))
    assert res["status"] == "published" and rep["resumes"] == 1 and len(rep["provenance"]["resumes"]) == 1
    kinds = [e["kind"] for e in rep["events_tail"]]
    assert "resumed" in kinds


def test_ignored_brand_filter_is_never_counted_as_coverage(settings, location, storage, tmp_path):
    settings.raw["crawl"]["brand_slices"] = True     # every brand slice gets the unfiltered saved beef page back
    f = FixtureFetcher(settings, location, fixtures=dict(PAGES), root=str(FIX))
    r = Runner(settings, location, storage, tmp_path / "state", fetcher=f)
    res = asyncio.run(r.run())
    slices = [l for l in r.ck.listings() if l["mode"] == "brand_slice"]
    assert slices and all(l["status"] == "failed" and "brand filter not honored" in l["error"] for l in slices)
    assert res["status"] == "validation_failed"                       # never published as complete
    assert not (storage.root / "test-544/latest/records.json").exists()
    cov = json.loads((r.dir / "coverage.json").read_text(encoding="utf-8"))
    assert all(not q["complete"] for q in cov["queries"] if q["brand_slices"])


def test_coupon_search_filter_flags_products_without_inventing_terms(settings, location, storage, tmp_path):
    pages = dict(PAGES)
    pages["savings=Coupons"] = "search_beef_store544.html.gz"     # replay of the filter response for the Beef shelf
    f = FixtureFetcher(settings, location, fixtures=pages, root=str(FIX))
    r = Runner(settings, location, storage, tmp_path / "state", fetcher=f)
    asyncio.run(r.run())
    assert any("savings=Coupons" in u for u in f.calls)
    obs = json.loads((r.dir / "observations.json").read_text(encoding="utf-8"))
    recs = json.loads((r.dir / "records.json").read_text(encoding="utf-8"))
    flagged = [o for o in obs.values() if o.get("digital_coupon_available")]
    assert flagged and all(o["digital_coupon_available"]["evidence_response_sha256"] for o in flagged)
    assert all(r_["digital_deals_description"] == "" for r_ in recs)      # no coupon terms -> nothing invented


def test_store_results_are_never_relabelled(settings, storage, tmp_path):
    """Vernon Hills settings against Crystal Lake responses: verification fails, nothing is collected or published."""
    from mscraper.config import Location
    vh = Location(key="vh-502", store_id="53100502", zipcode="60061", expected_address="1720 N Milwaukee", canary_query="milk")
    f = FixtureFetcher(settings, vh, fixtures=dict(PAGES), root=str(FIX))
    r = Runner(settings, vh, storage, tmp_path / "state", fetcher=f)
    import pytest

    with pytest.raises(RuntimeError, match="store verification failed"):
        asyncio.run(r.run())
    v = r.ck.get("store_verification")
    assert v["selected_store_id"] == "53100544" and not v["checks"]["location_id_matches"]
    assert not v["checks"]["zipcode_matches"] and not v["checks"]["address_matches"]
    assert r.ck.db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    assert not (storage.root / "vh-502" / "latest").exists()


def test_store_verification_records_fulfillment_and_response(settings, location, storage, tmp_path, fetcher):
    r = Runner(settings, location, storage, tmp_path / "state", fetcher=fetcher)

    async def go():
        await fetcher.start()
        return await r.verify_store()

    v = asyncio.run(go())
    assert v["verified"] and v["fulfillment_modality"] == "IN_STORE" and v["checks"]["fulfillment_modality_matches"]
    assert v["evidence_response_sha256"] in {x["response_sha256"] for x in r.ck.table("ledger")}


def test_realtime_adapter_builds_store_pinned_payload_from_config(settings, location):
    # 1.1.5: the 1.1.0 body {"source": "kroger", "url": …, "store_id": …} is not a documented Classic request and is
    # withdrawn; search pages use the documented kroger_search source with store localisation (see test_v115_safety)
    from mscraper.fetch import OxylabsRealtimeFetcher, realtime_payload
    f = OxylabsRealtimeFetcher(settings, location)
    body = realtime_payload(settings, location, "https://www.marianos.com/search?query=x")
    assert body == {"source": "kroger_search", "query": "x", "store_id": "53100544", "fulfillment_type": "in_store"}
    assert f.name == "oxylabs_realtime"
