# Mariano's scraper – v1.1.3 (Mariano's only; Walmart is a separate package)

Version 1.1.3 · code_sha256 `f0badef517dcd5f6840704ff49e25360ff2d2594b5e1bf7849c5d79d1d95e2e3` · 2026-10-26
**Deployment files only, and no new live data.** `src/mscraper` is unchanged from v1.1.2 apart from the version number.
The only live Mariano's evidence is still from 2026-10-21 (v1.1.2 package, folder A-LIVE-EVIDENCE-2026-10-21).
Nothing has been deployed, run or spent.

| Package | Status |
|---|---|
| Entry #69 (live data of 21 Oct) | unchanged; in the v1.1.2 package, folder A |
| v1.1.2 | superseded by v1.1.3 (live evidence folder A and the coupon note 04 still apply) |
| **v1.1.3** | **current.** Infrastructure-first deployment, container-scoped storage role, handover of Azure ids, test windows removed. 44 offline tests |
| v1.1.4 (planned) | live Test 1 + Test 2 evidence from Azure (previously announced as "v1.1.3") |
| v1.2.0 (planned) | final evidence |

## Files

| File | What it is |
|---|---|
| 01-INFRASTRUCTURE-FIRST-sequence-and-handover.md | confirmation that the infrastructure step needs no Oxylabs credential, the exact ids and commands you receive, sequence, relative timing, what waits on whom |
| 02-diff-1.1.2-to-1.1.3.patch | every changed line (deploy/azure/main.bicep, deploy.sh, docs, CHANGELOG, version) |
| 03-offline-tests-v1.1.3.txt | 44 offline tests, all passed (no live requests) |
| marianos-scraper-1.1.3-src.zip | complete source; CHANGELOG.md section 1.1.3 lists the changes |
| MESSAGE-TO-CLIENT.txt | the covering message |
| SHA256SUMS.txt | checksums of the files above |
