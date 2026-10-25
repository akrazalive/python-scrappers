# Mariano's scraper – v1.1.0 delivery (Mariano's only; Walmart is a separate package)

Version 1.1.0 · code_sha256 `e6232f2edb21c12ecf0ab8d5089a0c9b3bb7eb7baa1356fe4c1fd8e4bc5029dc` · 2026-10-24
(SOURCE_FINGERPRINT.txt inside the source ZIP also lists the SHA-256 of every config file and of requirements.txt)

## Files
| File | What it is |
|---|---|
| 00-INDEX.md | this index: completed / pending, commands |
| 01-RESPONSE-TO-REVIEW.md | point-by-point answer to the #69 review (1-5, blockers, what is needed from you) |
| 02-CHANGELOG-and-run-reconciliation.md | which code produced which run; revalidation; query expansion; quota stop; v1.1.0 changes |
| 03-oxylabs-usage-quota-and-cost.md | actual Mariano's requests by test, quota interruption, quota still needed, twice-weekly usage |
| 04-offline-tests-v1.1.0.txt | 34 OFFLINE tests (saved real responses) – not live evidence |
| 05-offline-replay-v1.1.0/ | OFFLINE replay of saved real responses through v1.1.0: the new output files in their real format – not a fresh run |
| 06-original-v1.0.0-run-logs/ | original logs of runs 03b8dc, fa0c1b (entry #69, both sessions), cf40b8 (quota stop + 23-Oct resume attempt) |
| 07-coverage-reconciliation-v1.0.0-runs.json | machine-readable coverage / remaining-gap reconciliation of the entry #69 run and the stopped run |
| 08-entry69-original-data/ | the entry #69 JSON (1,027 rows, sha256 0e1b7260…1051), both reports and coupons, unchanged |
| marianos-scraper-1.1.0-src.zip | complete runnable source, config, tests + real fixtures, Azure Bicep + scripts, docs, exact requirements |
| SHA256SUMS.txt | checksums of every file in this folder |

## Completed (code + offline tests, or files)
* 1 Retention (no-price, no-UPC, carried with own dates) · 2 Weight rule (wording only, triggers logged)
* 3 Coverage mechanism (brand slices) + coverage.json + live `probe` command; reconciliation of the delivered run (07)
* 4 Volume terms complete + structured; digital coupon flag via Mariano's savings=Coupons filter; exact dependency stated
* 5 Per-page ledger, price-bearing evidence, per-row response link, code/config hashes at start/resume/finish;
  version/run reconciliation (02) · exact dependency pins
* Azure for your limited test access: deploys into your existing resource group (no subscription rights), read-only
  preflight, role commands for your administrator, Key Vault secret stored by you, read-only evidence collection

## Pending (live) – needs Oxylabs quota and the Azure role (01 §6, §7)
1. preflight (read-only) → 2. probe (≈ 10-15 requests) → 3. deploy infra → your admin runs 2 role commands + stores key
→ 4. deploy job → 5. fresh full-CSV run in Azure, killed once and resumed → 6. failed-publication proof → 7. second
unattended scheduled execution → 8. coverage.json gap figures → package v1.1.x with all live evidence

## Commands
```
pip install -r requirements.lock            # Python 3.12/3.13
set PYTHONPATH=src                          # Linux/macOS: export PYTHONPATH=src
python -m pytest -q                         # offline tests
python -m mscraper probe --location marianos-544-crystal-lake --query Batteries
python -m mscraper run --location marianos-544-crystal-lake            # full run (all CSV rows, no caps)
python -m mscraper run --location marianos-544-crystal-lake --resume   # continue an interrupted run
./deploy/azure/preflight.sh <subscription-id> <resource-group>         # read-only
./deploy/azure/deploy.sh <subscription-id> <resource-group> infra      # then: job
./deploy/azure/collect_evidence.sh <subscription-id> <resource-group>  # read-only proof of unattended runs
```
