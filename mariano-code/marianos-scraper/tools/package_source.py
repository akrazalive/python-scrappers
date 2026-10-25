"""Build dist/marianos-scraper-<version>-src.zip: the complete, unencrypted delivery package + fingerprint."""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mscraper.version import __version__, code_sha256  # noqa: E402
from mscraper.evidence import file_sha256  # noqa: E402

INCLUDE = ["src", "config", "tests", "deploy", "docs", "tools", "README.md", "CHANGELOG.md", "requirements.txt",
           "requirements.lock", ".env.example", "Dockerfile"]
SKIP = ("__pycache__", ".pyc", ".pytest_cache")


def main() -> Path:
    out = ROOT / "dist" / f"marianos-scraper-{__version__}-src.zip"
    out.parent.mkdir(exist_ok=True)
    cfg = "".join(f"config_sha256[{n}]={file_sha256(ROOT / 'config' / n)}\n"
                  for n in ("settings.yaml", "categories.csv", "locations.yaml", "private_label_brands.txt"))
    fp = (f"version={__version__}\ncode_sha256={code_sha256()}\n{cfg}"
          f"requirements_sha256={file_sha256(ROOT / 'requirements.txt')}\n")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in INCLUDE:
            p = ROOT / item
            files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
            for f in files:
                if any(s in str(f) for s in SKIP):
                    continue
                z.write(f, f"marianos-scraper/{f.relative_to(ROOT).as_posix()}")
        z.writestr("marianos-scraper/SOURCE_FINGERPRINT.txt", fp)
    print(out, hashlib.sha256(out.read_bytes()).hexdigest())
    return out


if __name__ == "__main__":
    main()
