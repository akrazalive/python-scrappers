"""Provenance: code/config fingerprints recorded at run start, and per-page response evidence.

For every page the scraper uses, the run keeps
* a ledger row (checkpoint table `ledger`): time, query/URL, SHA-256 and size of the exact response, the store and
  request location ids and active modality read from that response, how many products it listed / priced and which
  `sourceLocationId` values its prices carried;
* a gzip JSON excerpt of the response (`evidence/pages/<sha256>.json.gz`): the store details, the search request
  variables and every product object with its price block exactly as Mariano's served them – the price-bearing
  source for every output row (`observations.response_sha256` links a row to its page);
* the complete raw HTML for the first pages of each category (`evidence/raw/<sha256>.html.gz`);
* every response that arrived but could not be used (unparseable provider envelope, page that does not parse, too
  small, HTTP error): a bounded, sanitized copy of the original body and a failure receipt linking its SHA-256 to the
  request, the budget ledger line and the timestamps (`evidence/failed/`, see `save_failed_response`).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
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
    from .version import deploy_sha256, release_sha256

    return {"scraper_version": __version__, "code_sha256": code_sha256(), "release_sha256": release_sha256(),
            "deploy_sha256": deploy_sha256(), "config_sha256": cfg,
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


_SECRET_KEYS = re.compile(r"(authorization|password|passwd|secret|token|api[_-]?key|credential|cookie|session)", re.I)
_ID_KEYS = re.compile(r"(job|request|query|task|id)", re.I)
_SECRET_ENV = ("OXYLABS_WEBAPI_KEY", "OXYLABS_USERNAME", "OXYLABS_PASSWORD", "AZURE_STORAGE_CONNECTION_STRING")


def redact_text(text: str) -> str:
    """Remove credentials from free text: key=value / key: value pairs, Bearer and Basic values, user:password@ in
    URLs, and the literal values of the configured credential environment variables."""
    text = re.sub(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)((?:proxy-)?authorization|password|passwd|secret|token|api[_-]?key|set-cookie|cookie)"
                  r"(\"?\s*[:=]\s*\"?)[^\s\",;}]+", r"\1\2[REDACTED]", text)
    text = re.sub(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@", text)
    for name in _SECRET_ENV:
        value = os.getenv(name) or ""
        if len(value) >= 4:
            text = text.replace(value, "[REDACTED]")
    return text


def sanitize_provider_response(raw: str) -> tuple[object, str]:
    """Keep provider metadata while removing credentials from refusal and failure evidence. Every string in the body
    is redacted, whatever its position: the whole body (a JSON string), a nested value, or an object key."""
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return redact_text(raw), ""

    def clean(item):
        if isinstance(item, dict):
            return {redact_text(k): ("[REDACTED]" if _SECRET_KEYS.search(k) else clean(v)) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return redact_text(item) if isinstance(item, str) else item

    def find_id(item):
        if isinstance(item, dict):
            for k, v in item.items():
                if _ID_KEYS.search(k) and isinstance(v, (str, int)):
                    return str(v)
                found = find_id(v)
                if found:
                    return found
        elif isinstance(item, list):
            for v in item:
                found = find_id(v)
                if found:
                    return found
        return ""

    cleaned = clean(value)
    return cleaned, find_id(cleaned)


def save_refusal(run_dir: Path, result) -> dict:
    """Archive target HTML and a sanitized provider envelope for a terminal target refusal."""
    raw = result.html.encode("utf-8")
    sha = sha256_bytes(raw)
    directory = run_dir / "evidence" / "refusals"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{sha}.html.gz").write_bytes(gzip.compress(raw))
    envelope, request_id = sanitize_provider_response(result.raw_response)
    record = {
        "url": result.url,
        "target_status": result.status,
        "provider_status": result.provider_status,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": len(raw),
        "sha256": sha,
        "provider_envelope": envelope,
    }
    (directory / f"{sha}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def _redact_values(item):
    """redact_text applied to every string inside a JSON-like value (keeps it valid JSON)."""
    if isinstance(item, dict):
        return {k: _redact_values(v) for k, v in item.items()}
    if isinstance(item, list):
        return [_redact_values(v) for v in item]
    return redact_text(item) if isinstance(item, str) else item


def save_failed_response(run_dir: Path, result, receipt: dict, max_bytes: int = 1_000_000) -> dict:
    """Archive a response that arrived but could not be used, even when it is not JSON or has an unsupported shape.

    `original_sha256` is the SHA-256 of the exact body received (the provider envelope when there is one, else the
    page). The stored copy is that body sanitized (credential keys, cookies, Bearer/Basic values, URL passwords and the
    configured credential values removed) and bounded to `max_bytes`, with its own `stored_sha256`. The receipt links
    both hashes to the request (URL, request body, attempt, budget ledger line), the timestamps and the failure.
    Request headers are never stored."""
    original = (result.raw_response or result.html or "").encode("utf-8")
    original_sha = sha256_bytes(original)
    envelope, request_id = sanitize_provider_response(original.decode("utf-8")) if original else ("", "")
    is_json = not isinstance(envelope, str)
    stored = (json.dumps(_redact_values(envelope), ensure_ascii=False) if is_json else envelope).encode("utf-8")
    truncated = len(stored) > max_bytes
    if truncated:
        stored = stored[:max_bytes].decode("utf-8", errors="ignore").encode("utf-8")
    directory = run_dir / "evidence" / "failed"
    directory.mkdir(parents=True, exist_ok=True)
    body_file = f"{original_sha}.{'json' if is_json else 'txt'}.gz"
    if not (directory / body_file).exists():
        (directory / body_file).write_bytes(gzip.compress(stored))
    request, _ = sanitize_provider_response(json.dumps(getattr(result, "request", None) or {}))
    record = {
        **_redact_values(receipt),
        "request_body": _redact_values(request),
        "provider_status": result.provider_status,
        "target_status": result.status or None,
        "request_id": request_id,
        "original_sha256": original_sha,
        "original_bytes": len(original),
        "original_format": "json" if is_json else "text",
        "stored_file": f"evidence/failed/{body_file}",
        "stored_sha256": sha256_bytes(stored),
        "stored_bytes": len(stored),
        "truncated": truncated,
        "sanitized": True,
    }
    name = f"{int(record.get('request_seq') or 0):04d}-{int(record.get('attempt') or 0)}-{original_sha[:16]}.json"
    record["receipt_file"] = f"evidence/failed/{name}"
    (directory / name).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    with (directory / "receipts.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
