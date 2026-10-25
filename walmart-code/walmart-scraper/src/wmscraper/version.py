"""Source fingerprint: proves which exact code version produced a dataset.

The fingerprint is a SHA-256 over every source and config file (sorted, path + content),
excluding secrets and output. It is written into every report and log, and is
reproduced by tools/package_source.py for the delivered source package.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ("src", "config", "deploy", "tools", "tests", "requirements.txt", "Dockerfile")
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "output", "evidence", "dist", "entry"}


def source_files(root: Path = ROOT) -> list[Path]:
    files = []
    for item in INCLUDE:
        p = root / item
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and not EXCLUDE_PARTS & set(f.relative_to(root).parts)
                      and f.suffix not in (".pyc", ".sqlite") and f.name != ".env"]
    return sorted(files, key=lambda f: f.relative_to(root).as_posix())


def fingerprint(root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for f in source_files(root):
        h.update(f.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


def version_info() -> dict:
    return {"version": __version__, "source_sha256": fingerprint()}
