"""Scraper version and code fingerprint, written into every report (evidence the data came from this code)."""
from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

__version__ = "1.1.2"
_SRC = Path(__file__).resolve().parent


def code_sha256() -> str:
    h = hashlib.sha256()
    for p in sorted(_SRC.rglob("*.py")):
        h.update(p.relative_to(_SRC).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def version_info() -> dict:
    return {"name": "marianos-scraper", "version": __version__, "code_sha256": code_sha256(),
            "python": sys.version.split()[0], "platform": platform.platform()}
