"""Scraper version and code fingerprint, written into every report (evidence the data came from this code)."""
from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

__version__ = "1.1.5"
_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parents[1]
# release_sha256 covers everything that decides what a deployment does (client review 27 Oct: code_sha256 alone
# excludes the template): application code, config, the Azure template/scripts, requirements and Dockerfile.
RELEASE_PARTS = ("src", "config", "deploy", "requirements.txt", "requirements.lock", "Dockerfile")


def code_sha256() -> str:
    h = hashlib.sha256()
    for p in sorted(_SRC.rglob("*.py")):
        h.update(p.relative_to(_SRC).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _tree_sha256(parts, root: Path = _ROOT) -> str:
    """SHA-256 over (relative path, content with LF line endings) of every file, sorted – same on Windows and Linux."""
    files = []
    for part in parts:
        p = root / part
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc"]
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.relative_to(root).as_posix()):
        h.update(f.relative_to(root).as_posix().encode() + b"\0")
        h.update(f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def release_sha256() -> str:
    return _tree_sha256(RELEASE_PARTS)


def deploy_sha256() -> str:
    return _tree_sha256(("deploy",))


def version_info() -> dict:
    return {"name": "marianos-scraper", "version": __version__, "code_sha256": code_sha256(),
            "release_sha256": release_sha256(), "deploy_sha256": deploy_sha256(),
            "python": sys.version.split()[0], "platform": platform.platform()}
