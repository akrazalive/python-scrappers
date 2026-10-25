# Mariano's Location Scraper for Microsoft Azure (v1.1.0)

See CHANGELOG.md for the version / run reconciliation and the v1.1.0 corrections.

Production scraper that collects **store-specific** Mariano's products, prices, price-per-measure (PPM),
promotions, categories and sub-categories for every row of `config/categories.csv`, runs **twice a week** as an
Azure Container Apps Job, and **only publishes a dataset after it passes validation**.

| | |
|---|---|
| Language | Python 3.12, asyncio |
| Page access | Oxylabs Web Scraper API, Kroger endpoint – every request pinned to the configured `store_id` |
| Parsing | Mariano's own server-rendered application state (`__INITIAL_STATE__`): store prices, PPM string, UPC, offers, taxonomy – no fragile CSS selectors |
| Store proof | store details on every page + `sourceLocationId` on every single price must equal the configured store |
| State | SQLite checkpoint per run (page-level continuation after any interruption) |
| Output | JSON in the exact required field order → local disk or Azure Blob Storage |
| Azure | Container Apps Job (cron), Blob Storage, Azure Files (checkpoints), Key Vault, Log Analytics, managed identity |
| Tests | `pytest` on saved real marianos.com responses – rules, deals, store mismatch, failed-run protection, resume |

## Quick start (local)

```bash
python -m venv .venv && .venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.lock                          # exact versions (requirements.txt = direct pins)
cp .env.example .env                                     # add OXYLABS_WEBAPI_KEY
set PYTHONPATH=src                                       # Linux/macOS: export PYTHONPATH=src

python -m mscraper verify-store --location marianos-544-crystal-lake
python -m mscraper run --location marianos-544-crystal-lake --categories "Dairy,Meat" --limit 150   # demo, never published
python -m mscraper run --location marianos-544-crystal-lake                                         # full run
python -m mscraper run --location marianos-544-crystal-lake --resume                                # continue an interrupted run
python -m mscraper summary --location marianos-544-crystal-lake
python -m mscraper probe --location marianos-544-crystal-lake --query Batteries                 # live paging / brand-filter check
python -m mscraper bounded-test test1        # live Test 1: both stores + probe, TOTAL <= 19 requests (enforced)
python -m mscraper bounded-test test2        # live Test 2: Batteries + Light Bulbs, no publish, TOTAL <= 300 (enforced)
python -m mscraper budget-status             # requests used / remaining per bounded test
./deploy/azure/run_test.sh <sub> <rg> test1  # the same test as one MANUAL Azure job execution, evidence downloaded
python -m pytest -q                                                                             # offline tests (saved real responses)
```

## Output

`output/<location>/latest/records.json` – last **validated** dataset (replaced only by a run that passes every check)
`output/<location>/latest/previous-records.json` – the dataset before that (one-step rollback)
`output/<location>/runs/<run_id>/` – every run's records, report and coupons (audit trail)
`state/<location>/runs/<run_id>/` – checkpoint, run log, evidence (ledger, price-bearing page excerpts, raw HTML samples)
`.../runs/<run_id>/observations.json` – per row: identity, fresh/carried, availability, offers with terms, source response SHA-256
`.../runs/<run_id>/coverage.json` – per request: Mariano's reported total vs distinct products read, brand slices, gap
`.../runs/<run_id>/exclusions.json` / `ledger.json` – approximate-weight exclusions with trigger text / page provenance

Field order (all strings, missing = `""`):
`zipcode, store_name, store_location, store_logo, store_brand, category, sub_category, product_title, weight,
regular_price, sale_price, volume_deals_description, volume_deals_price, digital_deals_description,
digital_deals_price, image_url, url, upc, gupc, ppm, unit_price, crawl_date`

`gupc` and `unit_price` are always empty (owned by the downstream pipeline). `ppm` is copied exactly as Mariano's
displays it (`equivalizedUnitPriceString`, e.g. `$0.06/fl oz`) and never calculated.

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – components, data flow, every data-quality rule
* [docs/OPERATIONS.md](docs/OPERATIONS.md) – Azure install, scheduling, monitoring, recovery, adding stores / categories
* [docs/COST.md](docs/COST.md) – monthly operating cost and every paid service

No telemetry, no remote kill-switch, no obfuscation, no hidden dependencies. All secrets come from environment
variables / Key Vault.
