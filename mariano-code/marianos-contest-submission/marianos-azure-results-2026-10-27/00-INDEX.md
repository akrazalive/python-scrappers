# Mariano's #69 – Azure results 2026-10-27 (marianos-scraper 1.1.4, code_sha256 8df0e6e1…)

| Folder | Kind | Result |
|---|---|---|
| A-OFFLINE/ | offline only: diff 1.1.3 → 1.1.4, 46 offline tests | passed |
| B-AZURE-SELFCHECK-0-requests/ | Azure, 0 provider requests: execution record, console log, state files | **PASSED** (secrets present, blob + state write/read) |
| C-LIVE-TEST1-FAILED-0-requests/ | live test attempt: execution record, console log (traceback), persistent budget `state/_budgets/test1.json` (used 0/19) | **FAILED before any provider request** (SQLite lock on the SMB share) |
| marianos-scraper-1.1.4-src.zip | complete source; CHANGELOG 1.1.4 item 4 = the proposed `nobrl` fix (in the template, NOT deployed) | |

No live data was collected. Console logs contain no credential values (only "present: true").
