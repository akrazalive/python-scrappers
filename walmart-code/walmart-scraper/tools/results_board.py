"""Renders the contest results board (PNG) directly from a run's report.json + records.json.

Because every number, example and store detail on the board is read from the scraper's
own output files, the image itself is evidence of what the scraper produced.

  python tools/results_board.py output/<location>/runs/<run_id>  [--preview]

--preview stamps a large watermark (used when checking layout with test fixtures).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
from pathlib import Path

CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
ROOT = Path(__file__).resolve().parents[1]


def esc(x) -> str:
    return html.escape(str(x))


def pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def ex_rows(records, fields, n=3):
    out = []
    for r in records[:n]:
        cells = "".join(f"<td>{esc(r.get(f, '')) or '<i>—</i>'}</td>" for f in fields)
        out.append(f"<tr>{cells}</tr>")
    return "".join(out) or f"<tr><td colspan='{len(fields)}'><i>none displayed by Walmart in this run</i></td></tr>"


def build(run_dir: Path, preview: bool) -> Path:
    rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    recs = json.loads((run_dir / "records.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256((run_dir / "records.json").read_bytes()).hexdigest()
    st = rep.get("store_verification", {})
    cats = rep.get("count_by_category", {})
    maxc = max(cats.values() or [1])
    bars = "".join(
        f"<div class='bar'><span>{esc(k)}</span><div><i style='width:{v / maxc * 100:.1f}%'></i></div><b>{v}</b></div>"
        for k, v in sorted(cats.items(), key=lambda kv: -kv[1]))
    comp = rep.get("field_completeness", {})
    comp_cells = "".join(
        f"<div class='cf'><small>{esc(k)}</small><b class='{'hi' if v >= .95 else 'mid' if v >= .5 else 'lo'}'>{pct(v)}</b></div>"
        for k, v in comp.items())
    exc = rep.get("excluded", {})
    exc_rows = "".join(f"<div class='kv'><span>{esc(k.replace('_', ' '))}</span><b>{v}</b></div>" for k, v in sorted(exc.items()))
    ex = rep.get("examples", {})
    val = rep.get("validation", {})
    sample = json.dumps(recs[0] if recs else {}, ensure_ascii=False, indent=1)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Results Board</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0b1220;--panel:#111b2e;--panel2:#16233b;--line:#22324f;--teal:#19e3c1;--amber:#ffb547;--rose:#ff6b8a;--ink:#e8eefc;--muted:#8fa0bf}}
*{{box-sizing:border-box;margin:0;padding:0}} html{{background:var(--bg)}}
body{{width:1600px;background:var(--bg);color:var(--ink);font-family:Inter,sans-serif;padding:56px 64px;position:relative;
background-image:radial-gradient(900px 500px at 100% 0,rgba(25,227,193,.10),transparent 60%)}}
h1,h2{{font-family:'Space Grotesk'}} .mono,td,pre{{font-family:'JetBrains Mono',monospace}}
.tag{{font-family:'JetBrains Mono';font-size:14px;color:var(--teal);letter-spacing:.16em;text-transform:uppercase}}
h1{{font-size:46px;letter-spacing:-1.2px;margin-top:8px}} h1 span{{color:var(--teal)}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-top:26px}}
.k{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px}}
.k small{{color:var(--muted);font-size:13px}} .k b{{display:block;font-family:'Space Grotesk';font-size:36px;margin-top:4px}}
.k b.t{{color:var(--teal)}}
.g{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:22px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px 24px}}
.card h2{{font-size:20px;margin-bottom:14px;display:flex;gap:10px;align-items:center}}
.card h2 i{{font-style:normal;font-family:'JetBrains Mono';font-size:12px;color:var(--bg);background:var(--teal);border-radius:6px;padding:3px 8px}}
.store{{display:grid;grid-template-columns:150px 1fr;gap:8px 14px;font-size:15px}} .store span{{color:var(--muted)}}
.ok{{color:var(--teal);font-family:'JetBrains Mono'}} .bad{{color:var(--rose);font-family:'JetBrains Mono'}}
.bar{{display:grid;grid-template-columns:200px 1fr 60px;gap:12px;align-items:center;margin:7px 0;font-size:14.5px}}
.bar div{{height:12px;background:var(--panel2);border-radius:6px;overflow:hidden}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--teal),#2aa8ff)}}
.bar b{{font-family:'JetBrains Mono';text-align:right}}
.cfs{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}} .cf{{background:var(--panel2);border-radius:8px;padding:7px 9px}}
.cf small{{display:block;color:var(--muted);font-size:11px;font-family:'JetBrains Mono'}} .cf b{{font-family:'JetBrains Mono';font-size:15px}}
.hi{{color:var(--teal)}} .mid{{color:var(--amber)}} .lo{{color:var(--muted)}}
.kv{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line);font-size:15px}} .kv b{{font-family:'JetBrains Mono';color:var(--amber)}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}} td,th{{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:500;font-family:Inter;font-size:12px}} td i{{color:var(--muted)}}
pre{{font-size:11.5px;line-height:1.5;color:#c9d6f2;background:#0a1322;border:1px solid var(--line);border-radius:10px;padding:12px;white-space:pre-wrap;word-break:break-all}}
.foot{{margin-top:22px;color:var(--muted);font-size:13px;font-family:'JetBrains Mono';display:flex;justify-content:space-between}}
.wm{{position:absolute;inset:0;display:grid;place-items:center;pointer-events:none}}
.wm span{{transform:rotate(-24deg);font-family:'Space Grotesk';font-size:110px;font-weight:700;color:rgba(255,107,138,.22);border:8px solid rgba(255,107,138,.22);padding:10px 40px;border-radius:20px}}
</style></head><body>
<div class="tag">Contest entry · Board 2 of 2 · Results generated by the scraper · run {esc(rep['run_id'])}</div>
<h1>{rep['total_unique_records']} unique local records <span>from {esc(st.get('store_name', ''))}</span></h1>
<div class="kpis">
 <div class="k"><small>Unique records</small><b class="t">{rep['total_unique_records']}</b></div>
 <div class="k"><small>Duplicates in output</small><b class="t">{rep['duplicate_records_in_output']}</b></div>
 <div class="k"><small>Duplicates prevented</small><b>{rep['duplicates_prevented']}</b></div>
 <div class="k"><small>Categories</small><b>{len(cats)}</b></div>
 <div class="k"><small>Runtime</small><b>{rep['runtime_seconds'] / 60:.1f} min</b></div>
</div>
<div class="g">
 <div class="card"><h2><i>STORE</i> Location &amp; fulfillment proof</h2><div class="store">
  <span>Store</span><b>{esc(st.get('store_name', ''))} · #{esc(st.get('store_id', ''))}</b>
  <span>Address</span><b>{esc(st.get('store_location', ''))}</b>
  <span>ZIP</span><b>{esc(st.get('zipcode', ''))}</b>
  <span>Verified</span><b class="{'ok' if st.get('verified') else 'bad'}">{'YES' if st.get('verified') else 'NO'} · {esc(st.get('checked_at', ''))}</b>
  <span>Fulfillment</span><b>{esc(rep['location']['fulfillment'])} · listing filter {esc(json.dumps(rep['fulfillment_context']['listing_filter']))}</b>
  <span>Store on pages</span><b class="ok">{rep['fulfillment_context']['pages_with_store_verified']} verified · {rep['fulfillment_context']['store_mismatch_pages']} mismatches</b>
 </div></div>
 <div class="card"><h2><i>COUNT</i> Records by category</h2>{bars}</div>
 <div class="card"><h2><i>EXCLUDED</i> Kept out of the dataset</h2>{exc_rows or '<i>none</i>'}
  <div class="kv"><span>validation</span><b class="{'ok' if val.get('ok') else 'bad'}">{'PASSED' if val.get('ok') else 'see report'}</b></div></div>
 <div class="card"><h2><i>FIELDS</i> Field completeness</h2><div class="cfs">{comp_cells}</div></div>
</div>
<div class="g">
 <div class="card"><h2><i>PPM</i> Price per measure (as displayed)</h2><table><tr><th>product_title</th><th>regular_price</th><th>ppm</th></tr>{ex_rows(ex.get('ppm', []), ['product_title', 'regular_price', 'ppm'])}</table></div>
 <div class="card"><h2><i>VOLUME</i> Volume deals</h2><table><tr><th>product_title</th><th>volume_deals_description</th><th>volume_deals_price</th></tr>{ex_rows(ex.get('volume_deals', []), ['product_title', 'volume_deals_description', 'volume_deals_price'])}</table></div>
 <div class="card"><h2><i>DIGITAL</i> Digital deals</h2><table><tr><th>product_title</th><th>digital_deals_description</th><th>digital_deals_price</th></tr>{ex_rows(ex.get('digital_deals', []), ['product_title', 'digital_deals_description', 'digital_deals_price'])}</table></div>
 <div class="card"><h2><i>PLAIN</i> Sale price &amp; no-deal products</h2><table><tr><th>product_title</th><th>regular_price</th><th>sale_price</th></tr>{ex_rows(ex.get('sale_price', [])[:2] + ex.get('no_deals', [])[:2], ['product_title', 'regular_price', 'sale_price'], 4)}</table></div>
</div>
<div class="g"><div class="card" style="grid-column:1/-1"><h2><i>JSON</i> First record, exact field order</h2><pre>{esc(sample)}</pre></div></div>
<div class="foot"><span>records.json sha256 {sha[:32]}…</span><span>requests {rep['fetch_stats'].get('requests')} · retries {rep['fetch_stats'].get('retries')} · challenges {rep['fetch_stats'].get('challenges')}</span></div>
{'<div class="wm"><span>SYNTHETIC TEST DATA · LAYOUT PREVIEW</span></div>' if preview else ''}
</body></html>"""
    out_html = run_dir / "results_board.html"
    out_html.write_text(page, encoding="utf-8")
    out_png = (ROOT / "entry" / ("preview-results-board.png" if preview else "02-results-board.png"))
    out_png.parent.mkdir(exist_ok=True)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=9000",
                    "--force-device-scale-factor=1.5", "--window-size=1600,2600", f"--screenshot={out_png}",
                    out_html.resolve().as_uri()], check=True, capture_output=True)
    _crop(out_png)
    return out_png


def _crop(p: Path):
    from PIL import Image

    im = Image.open(p).convert("RGB")
    w, h = im.size
    bg = im.getpixel((w // 2, h - 3))
    y = h - 1
    while y > 0 and all(abs(a - b) < 6 for a, b in zip(im.getpixel((w // 2, y)), bg)) \
            and all(abs(a - b) < 6 for a, b in zip(im.getpixel((w // 4, y)), bg)):
        y -= 1
    im.crop((0, 0, w, min(h, y + 70))).save(p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    print(build(Path(a.run_dir), a.preview))
