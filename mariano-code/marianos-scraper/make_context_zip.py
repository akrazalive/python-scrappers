
from __future__ import annotations
import sys, zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(r"D:\PROJECTS\Monthly-Test\marianos-scraper")
SUBMISSION = Path(r"D:\PROJECTS\Monthly-Test\marianos-contest-submission")
OUT_DIR = Path(r"D:\Asif Khan Docs\ASH Rising Pvt LTD\chat-mariano-export")

RUN = "20261021T040736Z-03b8dc"      # the contest-entry run
LOC = "marianos-544-crystal-lake"

PROJECT_FILES = [
    "src/mscraper/models.py","src/mscraper/parse.py","src/mscraper/deals.py",
    "src/mscraper/fetch.py","src/mscraper/runner.py","src/mscraper/validate.py",
    "src/mscraper/checkpoint.py","src/mscraper/storage.py","src/mscraper/lock.py",
    "src/mscraper/config.py","src/mscraper/cli.py","src/mscraper/__main__.py",
    "src/mscraper/__init__.py","src/mscraper/report.py","src/mscraper/logging_setup.py",
    "src/mscraper/text.py","src/mscraper/version.py",
    "config/categories.csv","config/locations.yaml","config/settings.yaml",
    "config/private_label_brands.txt",
    # --- contest-entry run (nested, correct paths) ---
    f"state/{LOC}/runs/{RUN}/checkpoint.sqlite",
    f"state/{LOC}/runs/{RUN}/run.log",
    f"state/{LOC}/runs/{RUN}/evidence/store_page_state_excerpt.json",
    f"output/{LOC}/runs/{RUN}/records.json",
    f"output/{LOC}/runs/{RUN}/report.json",
    f"output/{LOC}/runs/{RUN}/coupons.json",
    # --- deploy / ops / packaging ---
    "deploy/azure/main.bicep","deploy/azure/deploy.sh",
    "Dockerfile","requirements.txt","README.md",
    "docs/ARCHITECTURE.md","docs/COST.md","docs/OPERATIONS.md",
    "tools/package_source.py","tools/results_board.py",
    # --- tests ---
    "tests/test_pipeline.py","tests/test_rules.py","tests/conftest.py",
    # --- hidden/project config (helps review, no secrets) ---
    ".gitignore",".dockerignore",".env.example",
]

SUBMISSION_FILES = [
    "ENTRY-1-description.txt","ENTRY-1-results-board.png","README.txt",
    "send-to-client/MESSAGE-TO-CLIENT.txt",
]

EXCLUDE_BASENAMES = {".DS_Store","Thumbs.db"}
EXCLUDE_DIR_PARTS = {"__pycache__",".git",".venv","node_modules",".pytest_cache"}

def gather(root, rels, prefix, missing):
    out = []
    for rel in rels:
        p = root / rel
        if p.is_file():
            out.append((p, f"{prefix}/{rel}"))
        else:
            missing.append(f"{prefix}/{rel}")
    return out

def main():
    if not PROJECT.is_dir():
        print(f"ERROR: project dir not found: {PROJECT}", file=sys.stderr); return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_zip = OUT_DIR / f"marianos-context-{ts}.zip"

    missing = []
    entries = gather(PROJECT, PROJECT_FILES, "project", missing)
    if SUBMISSION.is_dir():
        entries += gather(SUBMISSION, SUBMISSION_FILES, "submission", missing)
    else:
        print(f"NOTE: submission dir not found: {SUBMISSION}")

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, arc in entries:
            zf.write(src, arc)

    size_mb = out_zip.stat().st_size / (1024 * 1024)
    print(f"\nWrote {out_zip}  ({len(entries)} files, {size_mb:.2f} MB)")
    if missing:
        print("\nMISSING (not fatal):")
        for m in missing: print(f"  - {m}")
    else:
        print("\nAll requested files included.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
