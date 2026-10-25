"""Thin-result detection, yield-drop detection and crash recovery with a real process kill."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

from wmscraper.config import load_settings
from wmscraper.lock import FileLock, LockError
from wmscraper.runner import Run
from wmscraper.storage import build_storage

ROOT = Path(__file__).resolve().parents[1]


def _fixtures(site):
    fx = site.parent.parent / "fixtures"
    return fx, json.loads((fx / "map.json").read_text())


def test_thin_listing_fails_validation(site):
    fx, m = _fixtures(site)
    p = fx / m["https://www.walmart.com/browse/976759_976787?facet=fulfillment_method%3APickup&stores=1234"]
    # Walmart counts 40 available store products, but the listing only served 4 → thin / truncated response
    p.write_text(p.read_text().replace('"aggregatedCount": 4', '"aggregatedCount": 40'))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert not rep["validation"]["ok"]
    assert any(("thin listing" in e or "count reconciliation failed" in e) and "Snacks" in e for e in rep["validation"]["errors"])
    assert build_storage(s).get_json("test-store/latest/records.json") is None


def test_yield_drop_against_previous_run_blocks_publication(site):
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["validation"]["ok"]
    # previous good run had 3x more Food products → current run must be rejected
    st = build_storage(s)
    prev = st.get_json("test-store/latest/report.json")
    prev["count_by_category"]["Food"] = rep["count_by_category"]["Food"] * 3
    st.put_json("test-store/latest/report.json", prev)
    rep2 = asyncio.run(Run(s, s.location("test-store")).execute())
    assert not rep2["validation"]["ok"]
    assert any("yield drop in Food" in e for e in rep2["validation"]["errors"])


def test_category_minimum(site):
    cfg = yaml.safe_load(site.read_text())
    cfg["validation"]["category_minimums"] = {"Food": 500}
    site.write_text(yaml.safe_dump(cfg))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert any("below configured minimum: Food" in e for e in rep["validation"]["errors"])


def test_lock_left_by_dead_process_is_taken_over(tmp_path):
    lock = tmp_path / ".run.lock"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    import socket
    lock.write_text(f"{socket.gethostname()} pid={dead.pid} crashed")
    with FileLock(lock):
        assert lock.exists()
    # a live holder is respected
    lock.write_text(f"{socket.gethostname()} pid={os.getpid()} alive")
    try:
        with FileLock(lock):
            raise AssertionError("must not acquire a lock held by a live process")
    except LockError:
        pass


def test_hard_kill_then_resume(site, tmp_path):
    """Starts a real run in a separate process, kills it mid-run, resumes, checks no loss / duplicates."""
    cfg = yaml.safe_load(site.read_text())
    cfg["fetch"]["min_delay_seconds"] = 0.4  # slow enough to kill mid-run
    cfg["fetch"]["max_delay_seconds"] = 0.4
    site.write_text(yaml.safe_dump(cfg))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    cmd = [sys.executable, "-m", "wmscraper", "--config", str(site), "run", "--location", "test-store"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = load_settings(site)
    st = build_storage(s)
    deadline = time.time() + 60
    ckpt = None
    while time.time() < deadline:
        state = st.get_json("test-store/state.json") or {}
        if state.get("open_run"):
            ckpt = st.local_path(f"test-store/runs/{state['open_run']}/checkpoint.sqlite")
            import sqlite3
            try:
                pages = sqlite3.connect(ckpt).execute("SELECT COUNT(*) FROM listings WHERE next_page > 1").fetchone()[0]
            except sqlite3.OperationalError:
                pages = 0
            if pages >= 1:
                break
        time.sleep(0.1)
    proc.kill()  # hard kill – no cleanup code runs
    proc.wait()
    run_id = st.get_json("test-store/state.json")["open_run"]
    assert st.local_path("test-store/.run.lock").exists()  # stale lock left behind by the killed process
    out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    rep = json.loads((st.local_path(f"test-store/runs/{run_id}/report.json")).read_text())
    assert rep["run_id"] == run_id  # same run continued, not restarted
    assert rep["validation"]["ok"], rep["validation"]
    assert rep["total_unique_records"] == 6 and rep["duplicate_records_in_output"] == 0
    assert any(e["kind"] == "run_resumed" for e in rep["events_tail"])


def test_location_scope_runs_and_publishes(site):
    loc = yaml.safe_load((site.parent / "locations.yaml").read_text())
    loc["locations"][0]["only_subcategories"] = ["Milk"]
    (site.parent / "locations.yaml").write_text(yaml.safe_dump(loc))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["validation"]["ok"], rep["validation"]
    assert {l["sub_category"] for l in rep["listings"]} == {"Milk"}
    assert rep["published"] and rep["published"]["record_count"] == rep["total_unique_records"]


def test_wrong_store_address_fails_before_collection(site):
    loc = yaml.safe_load((site.parent / "locations.yaml").read_text())
    loc["locations"][0]["expected_address"] = "702 SW 8th St"
    (site.parent / "locations.yaml").write_text(yaml.safe_dump(loc))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert not rep["validation"]["ok"]
    assert any("address" in e for e in rep["validation"]["errors"])
    assert rep["total_unique_records"] == 0


def test_raw_responses_archived_with_store_context(site):
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    st = build_storage(s)
    idx = st.get_json(f"test-store/runs/{rep['run_id']}/raw/index.json")
    kinds = {e["kind"] for e in idx}
    assert {"store", "listing", "product"} <= kinds
    listing = next(e for e in idx if e["kind"] == "listing")
    assert any(c.get("value") == "1234" for c in listing["store_context"])
    assert any(c.get("value") == "PICKUP" for c in listing["store_context"])
    assert "category_completeness" in rep and rep["category_completeness"]["Food"]["kept_records"] == 6


def test_cp_landing_root_and_landing_node_split(site):
    """Live patterns: /cp/feeding/133283 (real category path 5427_133283) and a node served as a landing page."""
    import conftest as c
    fx, m = _fixtures(site)
    pages = {
        "https://www.walmart.com/cp/feeding/133283": c.category_page([
            ("Baby Formula", "/browse/baby/formula/5427_133283_111"), ("Baby Food", "/browse/baby/food/5427_133283_222")]),
        # root opened as listing -> Walmart serves a landing page (no searchResult) -> split via its links
        f"{c.BROWSE}5427_133283{c.Q}": c.category_page([
            ("Baby Formula", "/browse/baby/formula/5427_133283_111"), ("Baby Food", "/browse/baby/food/5427_133283_222"),
            ("View all", "/browse/baby/all/5427_133283_999")]),
        f"{c.BROWSE}5427_133283_111{c.Q}": c.listing([c.item(301, "Similac Pro-Advance Infant Formula, 30.8 oz", "$41.98")]),
        f"{c.BROWSE}5427_133283_111?facet=fulfillment_method%3APickup&stores=1234": c.listing([], total=1),
        f"{c.BROWSE}5427_133283_222?facet=fulfillment_method%3APickup&stores=1234": c.listing([], total=1),
        f"{c.BROWSE}5427_133283_222{c.Q}": c.listing([c.item(302, "Gerber Banana Baby Food, 4 oz", "$1.28")]),
        "https://www.walmart.com/ip/Similac-Pro-Advance-Infant-Formula,-30.8-oz/301": c.product(301, "070074640709"),
        "https://www.walmart.com/ip/Gerber-Banana-Baby-Food,-4-oz/302": c.product(302, "015000075002"),
    }
    for n, (url, html) in enumerate(pages.items()):
        (fx / f"q{n}.html").write_text(html, encoding="utf-8")
        m[url] = f"q{n}.html"
    (fx / "map.json").write_text(json.dumps(m))
    (site.parent / "categories.csv").write_text(
        "Retailer,Category (Auto),URL,Scope,Notes\n"
        "Walmart,Feeding,https://www.walmart.com/cp/feeding/133283?povid=x,Category + ALL subcategories,\n", encoding="utf-8")
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["validation"]["ok"], rep["validation"]
    assert {l["sub_category"] for l in rep["listings"]} == {"Baby Formula", "Baby Food"}  # "View all" ignored
    assert rep["count_by_category"] == {"Feeding": 2}


def test_variant_mismatch_is_never_attributed(site):
    """Product page for item 102 returns another variant (id 999): its UPC must not be used."""
    import conftest as c
    fx, m = _fixtures(site)
    url = "https://www.walmart.com/ip/Fairlife-2%-Milk,-52-fl-oz/102"
    (fx / m[url]).write_text(c.product(999, "999999999999"), encoding="utf-8")
    m["https://www.walmart.com/ip/102"] = m[url]  # canonical retry returns the same wrong variant
    (fx / "map.json").write_text(json.dumps(m))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    st = build_storage(s)
    recs = st.get_json(f"test-store/runs/{rep['run_id']}/records.json")
    fl = next(r for r in recs if r["product_title"].startswith("Fairlife"))
    assert fl["upc"] == ""  # never the other variant's UPC
    assert rep["product_identity"]["variant_mismatches"] == 1


def test_offer_census_reports_displayed_labels(site):
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    labels = {r["label"]: r["classified_as"] for r in rep["offer_census"]["labels"]}
    assert labels["2 for $9"] == "volume_deal"
    assert labels["Clip Coupon: Save $1.00"] == "digital_deal"
    assert labels["Earn $1 Walmart Cash"] == "reward_not_a_price_reduction"


def test_oversize_listing_without_subcategories_is_price_partitioned(site):
    """A listing beyond the 25-page window with no child categories is split into price bands, each paginated."""
    import conftest as c
    fx, m = _fixtures(site)
    base = f"{c.BROWSE}2637_1042319"
    band = lambda lo, hi: f"{base}?min_price={lo}&max_price={hi}&stores=1234"
    pages = {
        f"{base}{c.Q}": c.listing([c.item(401, "Latex Balloons, 12 in, 72 ct", "$4.97")], total=3000),
        band(0, 5): c.listing([c.item(401, "Latex Balloons, 12 in, 72 ct", "$4.97"),
                               c.item(402, "Party Balloons, 10 ct", "$2.97")], total=2),
        band(5, 100000): c.listing([c.item(403, "Helium Balloon Kit, 30 ct", "$24.97"),
                                    c.item(401, "Latex Balloons, 12 in, 72 ct", "$4.97")], total=2),  # boundary overlap
        # Walmart's available-store counts (pickup facet) used to plan and reconcile
        f"{base}?facet=fulfillment_method%3APickup&stores=1234": c.listing([], total=3000),
        f"{base}?min_price=0&max_price=5&facet=fulfillment_method%3APickup&stores=1234": c.listing([], total=2),
        f"{base}?min_price=5&max_price=100000&facet=fulfillment_method%3APickup&stores=1234": c.listing([], total=2),
    }
    for i, upc in ((401, "000000000401"), (402, "000000000402"), (403, "000000000403")):
        name = {401: "Latex-Balloons,-12-in,-72-ct", 402: "Party-Balloons,-10-ct", 403: "Helium-Balloon-Kit,-30-ct"}[i]
        pages[f"https://www.walmart.com/ip/{name}/{i}"] = c.product(i, upc)
    for n, (url, html) in enumerate(pages.items()):
        (fx / f"b{n}.html").write_text(html, encoding="utf-8")
        m[url] = f"b{n}.html"
    (fx / "map.json").write_text(json.dumps(m))
    (site.parent / "categories.csv").write_text(
        "Retailer,Category (Auto),URL,Scope,Notes\n"
        f"Walmart,Balloons,{base}?povid=x,Category + ALL subcategories,\n", encoding="utf-8")
    cfg = yaml.safe_load(site.read_text())
    cfg["crawl"]["price_band_edges"] = [0, 5, 100000]
    site.write_text(yaml.safe_dump(cfg))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["validation"]["ok"], rep["validation"]
    urls = [l["url"] for l in rep["listings"]]
    assert any("min_price=0&max_price=5" in u for u in urls) and any("min_price=5&max_price=100000" in u for u in urls)
    assert rep["total_unique_records"] == 3 and rep["duplicate_records_in_output"] == 0


def test_out_of_stock_product_is_retained(site):
    import conftest as c
    fx, m = _fixtures(site)
    url = f"{c.BROWSE}976759_976787{c.Q}"
    p = fx / m[url]
    p.write_text(c.listing([c.item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz", availability="OUT_OF_STOCK"),
                            c.item(203, "Doritos Nacho, 9.25 oz", "$4.98")]), encoding="utf-8")
    # Walmart's available-store count no longer includes the out-of-stock item
    (fx / m[f"{c.BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234"]).write_text(
        c.listing([], total=1), encoding="utf-8")
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["validation"]["ok"], rep["validation"]
    recs = build_storage(s).get_json("test-store/latest/records.json")
    lays = next(r for r in recs if r["product_title"].startswith("Lay's"))
    assert lays["regular_price"] == "4.28" and lays["upc"] == "028400090858"  # identity + source price kept
    avail = {a["item_id"]: a for a in build_storage(s).get_json("test-store/latest/availability.json")}
    assert avail["201"]["status"] == "out_of_stock" and avail["201"]["price_source"] == "fresh_store_offer"


def test_unavailable_product_carried_forward_with_original_crawl_date(site):
    import conftest as c
    s = load_settings(site)
    asyncio.run(Run(s, s.location("test-store")).execute())
    st = build_storage(s)
    first = {r["product_title"]: r for r in st.get_json("test-store/latest/records.json")}
    # next run: Walmart no longer returns Doritos (e.g. became unavailable) and the run happens on a later date
    first_recs = st.get_json("test-store/latest/records.json")
    for r in first_recs:
        r["crawl_date"] = "2026-10-15"
    st.put_json("test-store/latest/records.json", first_recs)
    fx, m = _fixtures(site)
    url = f"{c.BROWSE}976759_976787{c.Q}"
    (fx / m[url]).write_text(c.listing([c.item(201, "Lay's Classic Chips, 8 oz", "$4.28", ppm="53.5 ¢/oz",
                                               badges=["$3.50 each with Digital Coupon"]),
                                        c.item(102, "Fairlife 2% Milk, 52 fl oz", "$4.98", was="$5.48")]), encoding="utf-8")
    (fx / m[f"{c.BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234"]).write_text(
        c.listing([], total=2), encoding="utf-8")
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["validation"]["ok"], rep["validation"]
    recs = {r["product_title"]: r for r in st.get_json("test-store/latest/records.json")}
    dor = recs["Doritos Nacho, 9.25 oz"]
    assert dor["upc"] == first["Doritos Nacho, 9.25 oz"]["upc"]  # identity preserved
    assert dor["crawl_date"] == "2026-10-15"  # last observed date, not presented as newly verified
    assert recs["Lay's Classic Chips, 8 oz"]["crawl_date"] != "2026-10-15"
    avail = {a["item_id"]: a for a in st.get_json("test-store/latest/availability.json")}
    assert avail["203"]["status"] == "not_returned_this_run" and avail["203"]["price_source"] == "last_observed"
    assert rep["availability"]["carried_forward"] == 1


def test_second_run_reuses_known_upcs_and_fetches_only_new_product_pages(site):
    s = load_settings(site)
    rep1 = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep1["validation"]["ok"]
    s2 = load_settings(site)
    rep2 = asyncio.run(Run(s2, s2.location("test-store")).execute())
    assert rep2["validation"]["ok"], rep2["validation"]
    assert rep2["product_identity"]["upc_reused_from_last_verified_run"] >= 5
    assert rep2["fetch_stats"]["requests"] < rep1["fetch_stats"]["requests"]
    recs = {r["product_title"]: r for r in build_storage(s2).get_json("test-store/latest/records.json")}
    assert recs["Great Value Whole Milk, 1 gal"]["upc"] == "078742351865"


# ---------------------------------------------------------------- client review 20 Oct: issues 1-4
def test_capped_listing_blocks_publication(site):
    """(1) A listing that reaches the page window without exhausting it is incomplete coverage -> not published."""
    cfg = yaml.safe_load(site.read_text())
    cfg["crawl"]["max_pages_per_listing"] = 1  # Milk has 2 pages: page window reached before Walmart's last page
    site.write_text(yaml.safe_dump(cfg))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert not rep["validation"]["ok"]
    assert any("incomplete coverage" in e and "Milk" in e for e in rep["validation"]["errors"])
    assert rep["published"] is None


def test_price_ppm_promotions_only_from_store_offer(site):
    """(2) Product pages never supply price, PPM or promotions; online-only offers are not in the dataset."""
    import conftest as c
    fx, m = _fixtures(site)
    url = "https://www.walmart.com/ip/Doritos-Nacho,-9.25-oz/203"
    html = c.product(203, "028400443494", badges=["2 for $7"])  # product page shows a deal + PPM
    html = html.replace('"priceInfo": {"currentPrice": {"priceString": "$2.98"}}',
                        '"priceInfo": {"currentPrice": {"priceString": "$2.98"}, "unitPrice": {"priceString": "32.2 ¢/oz"}}')
    (fx / m[url]).write_text(html, encoding="utf-8")
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    recs = {r["product_title"]: r for r in build_storage(s).get_json("test-store/latest/records.json")}
    dor = recs["Doritos Nacho, 9.25 oz"]
    assert dor["ppm"] == "" and dor["regular_price"] == "4.98"      # listing store offer had no PPM -> stays empty
    assert dor["volume_deals_description"] == "Buy 1, Get 1 Free"  # listing offer terms, not the product page's
    assert "Shipping Only Milk 12 pack" not in recs
    assert rep["excluded"]["not_store_assortment_online_only"] == 1


def test_selected_store_context_checked_explicitly(site):
    """(3) A page whose SELECTED location is another store fails, even if store 1234 appears elsewhere in it."""
    import conftest as c
    fx, m = _fixtures(site)
    p = fx / m[f"{c.BROWSE}976759_976787{c.Q}"]
    p.write_text(p.read_text().replace('"pageMetadata": {"location": {"storeId": "1234"',
                                       '"pageMetadata": {"location": {"storeId": "5260"'), encoding="utf-8")
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert not rep["validation"]["ok"]
    assert any("selected store context" in e for e in rep["validation"]["errors"])


def test_repeat_run_refreshes_prices_while_reusing_identity(site):
    """(4) Cached identity (UPC) never freezes price-sensitive fields: the repeat run reports the new store price."""
    import conftest as c
    s = load_settings(site)
    asyncio.run(Run(s, s.location("test-store")).execute())
    fx, m = _fixtures(site)
    for url in (f"{c.BROWSE}976759_9176907{c.Q}",):
        p = fx / m[url]
        p.write_text(p.read_text().replace('"linePrice": "$3.48"', '"linePrice": "$3.78"')
                     .replace('"unitPrice": "2.7 \\u00a2/fl oz"', '"unitPrice": "2.9 \\u00a2/fl oz"'), encoding="utf-8")
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert rep["product_identity"]["upc_reused_from_last_verified_run"] >= 1
    gv = {r["product_title"]: r for r in build_storage(s).get_json("test-store/latest/records.json")}["Great Value Whole Milk, 1 gal"]
    assert gv["regular_price"] == "3.78" and gv["upc"] == "078742351865" and gv["ppm"] == "2.9 ¢/fl oz"


def test_count_reconciliation_failure_blocks_publication(site):
    """Split listing must reach Walmart's own available-store count; a shortfall is incomplete coverage."""
    import conftest as c
    fx, m = _fixtures(site)
    # Snacks becomes a large node: Walmart reports 900 available store products, the crawl finds only a few
    big = f"{c.BROWSE}976759_976787{c.Q}"
    p = fx / m[big]
    p.write_text(p.read_text().replace('"aggregatedCount": 4', '"aggregatedCount": 5000'), encoding="utf-8")
    pick = f"{c.BROWSE}976759_976787?facet=fulfillment_method%3APickup&stores=1234"
    (fx / "rec.html").write_text(c.listing([], total=700), encoding="utf-8")
    m[pick] = "rec.html"
    (fx / "map.json").write_text(json.dumps(m))
    s = load_settings(site)
    rep = asyncio.run(Run(s, s.location("test-store")).execute())
    assert not rep["validation"]["ok"]
    assert any("count reconciliation failed" in e and "Snacks" in e for e in rep["validation"]["errors"])
    rows = {r["sub_category"]: r for r in rep["count_reconciliation"]}
    assert rows["Snacks"]["expected_store_total"] == 700
