# Walmart #32/#38 – Azure results 2026-10-27 (walmart-scraper 1.1.7, source_sha256 91b8113d…)

| Folder | Kind | Result |
|---|---|---|
| A-OFFLINE/ | offline only: diff 1.1.6 → 1.1.7 (persistent request ledger + selfcheck), 49 offline tests | passed |
| B-AZURE-SELFCHECK-0-requests/ | Azure, 0 provider requests: execution record, console log | **PASSED** (secrets present, blob write/read) |
| C-LIVE-PROBE-FAILED-3-requests/ | live probe: execution record, console log, ledger `budget-probe.json/.jsonl` (3/10), raw store page + index with SHA-256 | **FAILED on store context**: product responses show pickup store 4376, not 100 |
| walmart-scraper-1.1.7-src.zip | complete source; docs/CHANGES.md 1.1.7 | |

No listing or product data was collected; publication stays blocked. Console logs contain no credential values.
