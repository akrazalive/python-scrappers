"""Live probe (about 6-12 requests): settles, with saved evidence, how Mariano's search can be read completely.

  python -m mscraper probe --location <key> [--query Batteries]

Checks and records (state/<location>/probes/<ts>/probe.json + evidence/):
1. server-rendered page 1 vs page 2 of the same query (are page-2 UPCs different?)
2. page 2 rendered with JavaScript (does the client app load the real page 2?)
3. brand slices of the query: for every brand on page 1, the query + &brandName=<brand>; is the filter honored
   (share of products of that brand) and do the slice totals add up to the query total?
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import evidence, parse
from .fetch import FetchError

_DOM_UPC = re.compile(r'href="/p/[^"/]+/(\d{13})"')


async def run_probe(fetcher, settings, loc, out_dir: Path, query: str, max_requests: int = 15) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = settings.get("base_url", "https://www.marianos.com").rstrip("/")
    q_url = f"{base}/search?query={quote(query)}&searchType=default_search"
    rows = []

    def validate_probe_page(html, sp):
        state = parse.extract_state(html)
        store = sp.store
        modalities = (((state.get("calypso") or {}).get("domains") or {}).get("modalityPreferences") or {}).get("modalities") or []
        modality = next((m.get("modalityType") for m in modalities if m.get("modalityType")), "")
        sources = {
            str((((sp.products.get(u) or {}).get("data") or {}).get("price") or {}).get("storePrices", {}).get("sourceLocationId"))
            for u in sp.upcs
            if u in sp.products
        } - {""}
        checks = {
            "store_matches": store.location_id == loc.store_id,
            "request_store_matches": sp.request_location == loc.store_id,
            "banner_matches": "mariano" in store.banner.lower(),
            "fulfillment_modality_matches": modality == settings.get("store.expected_modality", "IN_STORE"),
            "prices_from_store": bool(sources) and sources == {loc.store_id},
        }
        if not all(checks.values()):
            exc = FetchError(f"probe qualification failed: {checks}", "store")
            raise exc

    async def get(kind, url, js=False):
        box = {}

        def check(html):
            st = parse.extract_state(html)
            box["state"], box["sp"] = st, parse.search_page(st)

        res = await fetcher.get(url, render_js=js, validate=check)
        sha, size, rel = evidence.save_page(out_dir, res.html, box["state"], keep_raw=True)
        sp = box["sp"]
        dom = list(dict.fromkeys(_DOM_UPC.findall(res.html)))
        brands = [((sp.products.get(u) or {}).get("data") or {}).get("item", {}).get("brand", {}).get("name", "") for u in sp.upcs]
        row = {"kind": kind, "url": url, "render_js": js, "response_sha256": sha, "evidence_file": rel,
               "store_location_id": sp.store.location_id, "request_location_id": sp.request_location,
               "reported_total": sp.total, "state_upcs": sp.upcs, "dom_upcs": dom, "brands": brands}
        rows.append(row)
        validate_probe_page(res.html, box["sp"])
        return row

    failure = None
    stopped = ""
    try:
        p1 = await get("page1_ssr", q_url)
        p2 = await get("page2_ssr", f"{q_url}&page=2")
        p2js = await get("page2_js", f"{q_url}&page=2", js=True)
    except FetchError as exc:
        failure = exc
        stopped = f"stopped before paging completed: {exc}"
        p1 = rows[0] if rows else {"brands": [], "state_upcs": [], "dom_upcs": [], "reported_total": 0}
        p2 = p2js = p1
    slices = []
    budget_left = max(0, max_requests - 3)            # hard bound for the first test: 3 paging requests + slices
    for b in ([] if failure else sorted({x for x in p1["brands"] if x})[:budget_left]):
        try:
            r = await get("brand_slice", f"{q_url}&brandName={quote(b)}")
        except FetchError as exc:
            failure = exc
            stopped = f"stopped before brand '{b}': {exc}"
            break
        share = (sum(1 for x in r["brands"] if x.lower() == b.lower()) / len(r["brands"])) if r["brands"] else 0
        slices.append({"brand": b, "reported_total": r["reported_total"], "returned": len(r["state_upcs"]),
                       "brand_share": round(share, 3), "honored": share >= 0.9})
    findings = {
        "page2_ssr_differs_from_page1": set(p2["state_upcs"]) != set(p1["state_upcs"]),
        "page2_js_dom_differs_from_page1": bool(p2js["dom_upcs"]) and set(p2js["dom_upcs"]) != set(p1["state_upcs"]),
        "brand_filter_honored_all": bool(slices) and all(s["honored"] for s in slices),
        "query_reported_total": p1["reported_total"],
        "sum_of_page1_brand_slice_totals": sum(s["reported_total"] for s in slices),
        "slices_needing_further_partition": [s for s in slices if s["reported_total"] > s["returned"]],
        "all_pages_store": sorted({r["store_location_id"] for r in rows}),
        "stopped": stopped,
    }
    rep = {"max_requests": max_requests, "brands_on_page1": sorted({x for x in p1["brands"] if x}),
           "probe_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "query": query,
           "store_id": loc.store_id, "fingerprints": evidence.fingerprints(settings), "findings": findings,
           "brand_slices": slices, "requests": rows, "fetch_stats": fetcher.stats}
    if failure:
        rep["failure"] = {"kind": failure.kind, "error": str(failure)}
    (out_dir / "probe.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    if failure:
        raise failure
    return rep
