# Mariano's scraper – v1.1.1 (Mariano's only; Walmart is a separate package)

Version 1.1.1 · code_sha256 `268b672e28873599357b42b45703f670b5a7e1655b5ed71f5f4ae0ae13b92f42` · 2026-10-24
(SOURCE_FINGERPRINT.txt in the source ZIP also lists the SHA-256 of every config file and requirements.txt)
Replaces v1.1.0. Nothing in this package was collected live after 2026-10-21; all new work is offline-tested code.

## Files
| File | What it is |
|---|---|
| 01-RESPONSE-TO-REVIEW.md | §A answers your reply on v1.1.0; §1-7 the original review points |
| 02-CHANGELOG-and-run-reconciliation.md | code ↔ run reconciliation; 1.1.0 and 1.1.1 changes |
| 03-oxylabs-usage-quota-and-cost.md | actual Mariano's requests by test, quota interruption, estimates |
| 04-offline-tests-v1.1.1.txt | 38 OFFLINE tests (saved real responses) – not live evidence |
| 05-offline-replay-v1.1.1/ | OFFLINE replay through v1.1.1 (new coverage format: every gap explained) – not a fresh run |
| 06-original-v1.0.0-run-logs/ | original logs of the 21-Oct runs and the 23-Oct resume attempt |
| 07-coverage-reconciliation-v1.0.0-runs.json | reconciliation of what was delivered in #69 and the stopped run (not full coverage) |
| 08-entry69-original-data/ | entry #69 JSON (sha256 0e1b7260…1051), reports, coupons – unchanged |
| 09-COUPONS-missing-linkage-and-dependency.md | exact missing coupon linkage and proposed dependency |
| 10-TEST-PLAN-bounded-tests-endpoint-window.md | compatible Oxylabs endpoint, bounded tests with hard caps, Central-time window |
| marianos-scraper-1.1.1-src.zip | runnable source, config, tests, Azure (Contributor-only, manual job), docs, exact requirements |
| SHA256SUMS.txt | checksums of every file in this folder |

## Status
* Done (code + offline tests): retention · weight wording rule · coverage with zero-unexplained-gap rule · offers
  terms + coupon flag · provenance ledger/hashes · Vernon Hills candidate (disabled, unverified) · manual-only Azure job.
* Waiting on you: role assignment on scraper-contest-asif-test; deployment/cost-plan approval; Oxylabs endpoint/plan
  choice for Test 1 (≤ 19 requests); a Central-time test window.
* Then, in order: Test 1 → Test 2 (≤ 300) → deploy (manual job) → Test 3 fresh full-CSV run with a real kill/resume
  → failed-publication checksum proof → second execution → coverage figures → live evidence package.
