"""Builds the delivered source package.

  python tools/package_source.py

Creates dist/walmart-scraper-<version>-src.zip containing the complete, unencrypted source,
config, deployment files, docs and tests, plus MANIFEST.txt (SHA-256 of every file) and
SOURCE_FINGERPRINT.txt. The fingerprint is the same value the scraper writes into every
run report and log (report.json → scraper.source_sha256), which ties each dataset to the
exact code that produced it. Secrets (.env), outputs and caches are never included.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wmscraper import __version__  # noqa: E402
from wmscraper.version import fingerprint, source_files  # noqa: E402

EXTRA = ["README.md", ".env.example", ".gitignore", ".dockerignore", "docs"]


def main() -> Path:
    files = source_files(ROOT)
    for item in EXTRA:
        p = ROOT / item
        files += [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
    files = sorted(set(files), key=lambda f: f.relative_to(ROOT).as_posix())
    assert not any(f.name == ".env" for f in files), "secrets must never be packaged"
    fp = fingerprint(ROOT)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"walmart-scraper-{__version__}-src.zip"
    manifest = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(ROOT).as_posix()}" for f in files]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"walmart-scraper/{f.relative_to(ROOT).as_posix()}")
        z.writestr("walmart-scraper/MANIFEST.txt", "\n".join(manifest) + "\n")
        z.writestr("walmart-scraper/SOURCE_FINGERPRINT.txt", f"version {__version__}\nsource_sha256 {fp}\n")
    zip_sha = hashlib.sha256(out.read_bytes()).hexdigest()
    (dist / "SHA256SUMS.txt").write_text(f"{zip_sha}  {out.name}\n", encoding="utf-8")
    print(f"{out}\n  files: {len(files)}\n  source_sha256: {fp}\n  zip_sha256: {zip_sha}")
    return out


if __name__ == "__main__":
    main()
