"""Store / fulfillment evidence from saved raw marianos.com responses (no network).

    python tools/store_evidence.py <out.json> <response.html[.gz]> [...]

For every response: SHA-256 of the exact bytes, the store Mariano's says is selected (location id, name, address,
ZIP), the fulfillment modality of that selection, the store the search request was pinned to, and for every product
on the page the store its price came from (price.storePrices.sourceLocationId) and its IN_STORE availability at that
store. Three price-bearing product excerpts per response are copied verbatim from the page state.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mscraper import parse  # noqa: E402


def one(path: Path) -> dict:
    raw = path.read_bytes()
    html = (gzip.decompress(raw) if path.suffix == ".gz" else raw).decode("utf-8")
    state = parse.extract_state(html)
    mp = ((state.get("calypso") or {}).get("domains") or {}).get("modalityPreferences") or {}
    modalities = [{"modalityType": m.get("modalityType"), "destination_locationId": (m.get("destination") or {}).get("locationId")}
                  for m in mp.get("modalities") or []]
    st = parse.store_info(state)
    out = {"file": path.name, "sha256_of_file": hashlib.sha256(raw).hexdigest(),
           "selected_store": {"location_id": st.location_id, "name": st.name, "address": st.full_address,
                              "zipcode": st.zipcode, "banner": st.banner},
           "fulfillment_modalities": modalities}
    try:
        sp = parse.search_page(state)
    except Exception:  # department / coupons pages carry the store but no search grid
        return out
    src, instore, excerpts = Counter(), Counter(), []
    for u in sp.upcs:
        data = (sp.products.get(u) or {}).get("data") or {}
        price = (data.get("price") or {}).get("storePrices") or {}
        src[str(price.get("sourceLocationId") or "")] += 1
        for loc in data.get("sourceLocations") or []:
            if str(loc.get("id")) == st.location_id:
                for m in loc.get("modalityAvailabilities") or []:
                    if m.get("modalityType") == "IN_STORE":
                        instore[str(m.get("availability"))] += 1
        if price.get("regular") and len(excerpts) < 3:
            excerpts.append({"upc": u, "title": ((data.get("item") or {}).get("description") or ""),
                             "price.storePrices": {k: price.get(k) for k in ("sourceLocationId", "regular", "promo")},
                             "sourceLocations": [loc for loc in data.get("sourceLocations") or [] if str(loc.get("id")) == st.location_id]})
    out.update({"search_request_location": sp.request_location, "products_on_page": len(sp.upcs),
                "price_source_location_ids": dict(src), "in_store_availability_at_selected_store": dict(instore),
                "price_bearing_excerpts": excerpts})
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    res = [one(Path(p)) for p in argv[2:]]
    Path(argv[1]).write_text(json.dumps({"responses": res}, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in res:
        s = r["selected_store"]
        print(f'{r["file"]}: store {s["location_id"]} {s["zipcode"]} modality={[m["modalityType"] for m in r["fulfillment_modalities"]]} '
              f'pinned={r.get("search_request_location", "-")} price_sources={r.get("price_source_location_ids", "-")} '
              f'in_store={r.get("in_store_availability_at_selected_store", "-")}')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
