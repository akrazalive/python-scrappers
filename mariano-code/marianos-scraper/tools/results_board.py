"""Render a one-page results board (PNG) from a run's report.json + records.json.

  python tools/results_board.py <run_dir> <out.png>
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

run = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2])
rep = json.loads((run / "report.json").read_text(encoding="utf-8"))
recs = json.loads((run / "records.json").read_text(encoding="utf-8"))
st = rep["store_verification"]
e = html.escape


def pct(x):
    return f"{x * 100:.1f}%"


comp = rep.get("field_completeness_scoped") or rep.get("field_completeness")
fields = ["product_title", "weight", "regular_price", "sale_price", "volume_deals_description", "image_url", "url",
          "upc", "ppm", "store_brand", "gupc", "unit_price"]
cats = rep["category_coverage"]


def ex_row(r):
    deal = r["volume_deals_description"] or r["digital_deals_description"] or ("Sale " + r["sale_price"] if r["sale_price"] else "—")
    return (f"<tr><td>{e(r['category'])} › {e(r['sub_category'])}</td><td>{e(r['product_title'][:46])}</td><td>{e(r['weight'])}</td>"
            f"<td>{e(r['regular_price'])}</td><td>{e(r['sale_price'])}</td><td><b>{e(r['ppm'])}</b></td><td>{e(deal[:44])}</td><td>{e(r['upc'])}</td></tr>")


exs, used_cats = [], set()
pools = [[r for r in recs if r["volume_deals_description"]], [r for r in recs if r["sale_price"]],
         [r for r in recs if r["store_brand"] == "yes"],
         [r for r in recs if not (r["sale_price"] or r["volume_deals_description"])], recs]
for pool in pools:  # one example per category per kind, so the board shows every category
    for r in pool:
        if r["category"] not in used_cats and r not in exs:
            exs.append(r)
            used_cats.add(r["category"])
    used_cats.clear()
    if len(exs) >= 10:
        break
coupons = rep.get("coupons", {}).get("count", 0)
cps = []
cj = run / "coupons.json"
if cj.exists():
    cps = json.loads(cj.read_text(encoding="utf-8"))[:5]
fs = rep["fetch_stats"]
v = rep["validation"]

page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;width:1800px;font-family:Segoe UI,Arial,sans-serif;background:#F6F3EE;color:#1d1d1f}}
.top{{background:#7a1e2b;color:#fff;padding:26px 40px;display:flex;justify-content:space-between;align-items:center}}
.top h1{{margin:0;font-size:34px}} .top p{{margin:6px 0 0;opacity:.85;font-size:16px}}
.badge{{background:#fff;color:#7a1e2b;border-radius:10px;padding:10px 16px;font-weight:700;font-size:15px;text-align:right}}
.grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;padding:22px 40px 0}}
.k{{background:#fff;border-radius:12px;padding:16px;border:1px solid #e6e0d6}} .k b{{display:block;font-size:30px;color:#7a1e2b}} .k span{{font-size:13px;color:#555}}
.row{{display:grid;grid-template-columns:1.05fr 1fr;gap:18px;padding:18px 40px 0}}
.card{{background:#fff;border-radius:12px;padding:16px 18px;border:1px solid #e6e0d6}}
h3{{margin:0 0 10px;font-size:17px;color:#7a1e2b}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}} th{{text-align:left;color:#666;border-bottom:1px solid #ddd;padding:5px 4px}} td{{padding:5px 4px;border-bottom:1px solid #f0ebe3;vertical-align:top}}
.ok{{color:#1a7f37;font-weight:700}} .bad{{color:#b42318;font-weight:700}}
.bar{{height:8px;background:#eee;border-radius:9px}} .bar i{{display:block;height:8px;border-radius:9px;background:#7a1e2b}}
small{{color:#777}} .foot{{padding:16px 40px 26px;font-size:12.5px;color:#555}}
</style></head><body>
<div class="top"><div><h1>Mariano's Scraper – Live Demonstration Run</h1>
<p>Run {e(rep['run_id'])} · crawl_date {e(rep['crawl_date'])} · scraper v{e(rep['scraper']['version'])} · code sha256 {e(rep['scraper']['code_sha256'][:16])}…</p>{('<p>' + e(sys.argv[3]) + '</p>') if len(sys.argv) > 3 else ''}</div>
<div class="badge">{e(st['store_name'])} · store {e(st['selected_store_id'])}<br>{e(st['store_location'])}</div></div>
<div class="grid">
<div class="k"><b>{rep['total_unique_records']}</b><span>unique valid records (UPC)</span></div>
<div class="k"><b>{rep['duplicate_records_in_output']}</b><span>duplicates in output ({rep['duplicates_prevented']} prevented)</span></div>
<div class="k"><b>{len(rep['count_by_category'])}</b><span>product categories + Coupons ({coupons} coupons)</span></div>
<div class="k"><b>{rep['runtime_seconds'] / 60:.1f} min</b><span>runtime · {fs.get('requests', 0)} requests · {fs.get('retries', 0)} retries</span></div>
<div class="k"><b>{rep['store_checks_during_run']['pages_with_store_verified']}</b><span>pages store-verified · <span class="{'ok' if not rep['store_checks_during_run']['store_mismatches'] else 'bad'}">{rep['store_checks_during_run']['store_mismatches']} mismatches</span></span></div>
<div class="k"><b>{sum(rep['excluded'].values())}</b><span>excluded: {', '.join(f'{k} {v}' for k, v in rep['excluded'].items())}</span></div>
</div>
<div class="row">
<div class="card"><h3>Count by category (CSV rows) and coverage</h3><table><tr><th>Category</th><th>Search queries done/total</th><th>Pages</th><th>Listed</th><th>In sub-category</th><th>Kept</th></tr>
{''.join(f"<tr><td>{e(n)}</td><td>{c['listings_done']}/{c['listings']}</td><td>{c['pages_read']}</td><td>{c['products_listed']}</td><td>{c['products_in_subcategory']}</td><td><b>{c.get('coupons_read', c['records_kept'])}</b>{' coupons' if c['kind'] == 'coupons' else ''}</td></tr>" for n, c in cats.items())}
</table></div>
<div class="card"><h3>Field completeness ({len(recs)} records)</h3><table>
{''.join(f"<tr><td style='width:34%'>{f}</td><td><div class='bar'><i style='width:{comp[f] * 100:.1f}%'></i></div></td><td style='width:12%'>{pct(comp[f])}</td></tr>" for f in fields)}
</table><small>gupc and unit_price are intentionally empty (downstream pipeline). sale/deal fields are filled only where Mariano's shows them.</small></div>
</div>
<div class="row" style="grid-template-columns:1fr">
<div class="card"><h3>Record examples (PPM exactly as displayed · volume deal · sale · no deal · store brand)</h3><table><tr><th>Category › sub</th><th>Product</th><th>Weight</th><th>Regular</th><th>Sale</th><th>PPM</th><th>Deal</th><th>UPC</th></tr>
{''.join(ex_row(r) for r in exs[:10])}</table></div></div>
<div class="row">
<div class="card"><h3>Store selection evidence</h3><table>
{''.join(f"<tr><td>{e(k)}</td><td class='{'ok' if val else 'bad'}'>{'PASS' if val else 'FAIL'}</td></tr>" for k, val in st['checks'].items())}
<tr><td>canary start / end</td><td class="{'ok' if rep['canary'].get('start', {}).get('ok') and rep['canary'].get('end', {}).get('ok') else 'bad'}">{'PASS' if rep['canary'].get('start', {}).get('ok') and rep['canary'].get('end', {}).get('ok') else 'FAIL'}</td></tr>
</table><small>Every price carries Mariano's own sourceLocationId; all must equal {e(st['configured_store_id'])}.</small></div>
<div class="card"><h3>Digital coupons read from the Coupons page</h3><table>{''.join(f"<tr><td>{e(c['coupon_id'])}</td><td>{e(c['description'][:80])}</td><td>{e(c['expires'])}</td></tr>" for c in cps)}</table>
<small>Validation: <span class="{'ok' if v['ok'] else 'bad'}">{'PASSED' if v['ok'] else 'FAILED'}</span>{(' · ' + e('; '.join(v['errors'][:2]))) if v['errors'] else ''} · demo scope is never published to latest/.</small></div>
</div>
<div class="foot">Python 3.12 · Oxylabs Web Scraper API (Kroger endpoint, store_id pinned) · Mariano's application state parsing · SQLite checkpoints · Azure Container Apps Job (twice weekly) + Blob + Azure Files + Key Vault + Log Analytics. Full JSON, report.json and run.log attached.</div>
</body></html>"""

tmp = run / "_board.html"
tmp.write_text(page, encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1800, "height": 1000})
    pg.goto(tmp.as_uri())
    pg.screenshot(path=str(out), full_page=True)
    b.close()
print(out)
