"""Provenance: code/config fingerprints recorded at run start, and per-page response evidence.

For every page the scraper uses, the run keeps
* a ledger row (checkpoint table `ledger`): time, query/URL, SHA-256 and size of the exact response, the store and
  request location ids and active modality read from that response, how many products it listed / priced and which
  `sourceLocationId` values its prices carried;
* a gzip JSON excerpt of the response (`evidence/pages/<sha256>.json.gz`): the store details, the search request
  variables and every product object with its price block exactly as Mariano's served them – the price-bearing
  source for every output row (`observations.response_sha256` links a row to its page);
* the complete raw HTML for the first pages of each category (`evidence/raw/<sha256>.html.gz`).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import platform
import sys
from pathlib import Path

from .version import __version__, code_sha256

ROOT = Path(__file__).resolve().parents[2]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha256(p: Path) -> str:
    return sha256_bytes(p.read_bytes()) if p.exists() else ""


def fingerprints(settings, argv: list[str] | None = None) -> dict:
    base = Path(settings.get("_base_dir") or ROOT)
    cfg = {name: file_sha256(base / "config" / name) for name in
           ("settings.yaml", "categories.csv", "locations.yaml", "private_label_brands.txt")}
    req = file_sha256(base / "requirements.txt")
    return {"scraper_version": __version__, "code_sha256": code_sha256(), "config_sha256": cfg,
            "requirements_sha256": req, "python": sys.version.split()[0], "platform": platform.platform(),
            "argv": argv or sys.argv[1:]}


def save_page(run_dir: Path, html: str, state: dict | None, keep_raw: bool) -> tuple[str, int, str]:
    """Store the page excerpt (and optionally the raw HTML). Returns (sha256, bytes, relative evidence path)."""
    raw = html.encode("utf-8")
    sha = sha256_bytes(raw)
    pages = run_dir / "evidence" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    rel = f"evidence/pages/{sha}.json.gz"
    target = run_dir / rel
    if state is not None and not target.exists():
        dom = ((state.get("calypso") or {}).get("domains") or {})
        sa = (state.get("search") or {}).get("searchAll") or {}
        excerpt = {"response_sha256": sha, "response_bytes": len(raw),
                   "modalityPreferences": dom.get("modalityPreferences"),
                   "search_request": sa.get("requestVars"),
                   "search_response": {k: (sa.get("response") or {}).get(k) for k in ("upcs", "productsInfo", "products")},
                   "products": dom.get("products")}
        target.write_bytes(gzip.compress(json.dumps(excerpt, ensure_ascii=False).encode("utf-8")))
    if keep_raw:
        rdir = run_dir / "evidence" / "raw"
        rdir.mkdir(parents=True, exist_ok=True)
        rp = rdir / f"{sha}.html.gz"
        if not rp.exists():
            rp.write_bytes(gzip.compress(raw))
    return sha, len(raw), rel
