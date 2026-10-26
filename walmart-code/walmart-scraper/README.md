# Walmart Location Scraper for Microsoft Azure

Production scraper that collects **location-specific** Walmart products, prices, PPM and promotions for
every category and subcategory in `config/categories.csv`, runs **twice a week** as an Azure Container
Apps Job, and **only publishes a dataset after it passes validation**.

| | |
|---|---|
| Language | Python 3.12, asyncio |
| Page access | Oxylabs Web API, Walmart endpoint – every request pinned to the store (`store_id`, pickup, ZIP) |
| Parsing | Walmart's embedded `__NEXT_DATA__` JSON (not fragile CSS selectors) |
| State | SQLite checkpoint per run (genuine page-level continuation) |
| Output | JSON in the exact required field order → local disk or Azure Blob Storage |
| Azure | Container Apps Job (manual; schedule after approval), Blob Storage, Key Vault, Log Analytics, managed identity |
| Tests | `pytest` – rules, deals, dedup, store mismatch, failed-run protection, interruption recovery |

## Quick start (local)

```bash
python -m venv .venv && .venv/Scripts/activate     # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                # add OXYLABS_WEBAPI_KEY
# set store_id / zipcode in config/locations.yaml
set PYTHONPATH=src                                  # Linux/macOS: export PYTHONPATH=src

python -m wmscraper verify-store --location walmart-100-bentonville
python -m wmscraper run --location walmart-100-bentonville --categories "Food,Pets" --limit 600   # demo, never published
python -m wmscraper run --location walmart-100-bentonville                                        # full run
python -m wmscraper summary --location walmart-100-bentonville
python -m pytest -q
```

## Output

`output/<location>/latest/records.json` – last **validated** dataset (replaced only by a run that passes every check)
`output/<location>/runs/<run_id>/` – every run's records, report, log and checkpoint (audit trail)

Field order (all strings, missing = `""`):
`zipcode, store_name, store_location, store_logo, store_brand, category, sub_category, product_title, weight,
regular_price, sale_price, volume_deals_description, volume_deals_price, digital_deals_description,
digital_deals_price, image_url, url, upc, gupc, ppm, unit_price, crawl_date`

`gupc` and `unit_price` are always empty (owned by the downstream pipeline). `ppm` is copied exactly as Walmart
displays it and never calculated.

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – components, data flow, every data-quality rule
* [docs/OPERATIONS.md](docs/OPERATIONS.md) – Azure install, scheduling, monitoring, recovery, adding stores / categories
* [docs/COST.md](docs/COST.md) – monthly operating cost and every paid service

No telemetry, no remote kill-switch, no obfuscation, no hidden dependencies. All secrets come from environment
variables / Key Vault.
