# Mariano's scraper – v1.1.2 (Mariano's only; Walmart is a separate package)

Version 1.1.2 · code_sha256 `40c404a02eaae755cd7daea89b818d2213cb29c24fd005f5c339b4e2b6678129` · 2026-10-25
(SOURCE_FINGERPRINT.txt in the source ZIP also lists the SHA-256 of every config file and requirements.txt.)
**No new live data.** The only live Mariano's evidence is from 2026-10-21 (folder A). Everything else is code and
offline tests (folder B).

## One entry, one status per package

There is one Mariano's contest entry: **entry #69**. Your 23-Oct review heading called it "#69 (earlier #60)"; there
is no separate #60 package. Every package below belongs to entry #69.

| Package | Date | Status |
|---|---|---|
| Entry #69 = v1.0.0 + live run 20261021T042105Z-fa0c1b | 21-23 Oct | **Live data of 21 Oct, kept unchanged in folder A.** Demonstration subset (5 of 28 CSV rows, first-page reads), never published to latest/. Code superseded. |
| v1.1.0 | 24 Oct | Superseded by v1.1.1. Offline only. |
| v1.1.1 | 24 Oct | Superseded by v1.1.2. Offline only. |
| **v1.1.2** | 25 Oct | **Current.** Code + 44 offline tests. No live run. |
| v1.1.3 (planned) | see 02 | Live Test 1 + Test 2 evidence from Azure |
| v1.2.0 (planned) | see 02 | Final evidence: fresh full run, real kill/resume, failed-publication proof, second execution |

## Files

| File | What it is |
|---|---|
| 01-RESPONSE-TO-FEEDBACK-24-OCT.md | each point of your 24-Oct feedback → answer and file |
| 02-COMPLETION-PLAN-US-CENTRAL.md | every remaining task, estimate, dependency and date/time (US Central) |
| 03-BOUNDED-TESTS-commands-limits-oxylabs-azure-sequence.md | exact Oxylabs feature/auth, deployment-vs-test sequence, executable commands, enforced totals |
| 04-COUPON-LINKAGE-unresolved.md | what is linked now, the exact missing linkage, the dependency |
| **A-LIVE-EVIDENCE-2026-10-21/** | LIVE only: entry #69 data, original run logs, raw responses, store/fulfillment evidence, reconciliation of the 21-Oct runs |
| **C-AZURE-PREFLIGHT-2026-10-25/** | read-only Azure check of the test resource group: access, role, providers, policy, what-if preview. Nothing created. |
| **B-OFFLINE-ONLY/** | OFFLINE only: 44 tests on saved responses, offline replay. Not live evidence. |
| marianos-scraper-1.1.2-src.zip | runnable source, config, tests, Azure (manual job, run_test.sh), docs, exact requirements |
| SHA256SUMS.txt | checksums of every file in this folder |
