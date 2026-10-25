# Mariano's – remaining tasks and completion plan (US Central time)

CDT (UTC-5) until Sun 1 Nov 2026 02:00, then CST (UTC-6). Dates assume each dependency in the "Needs" column is
met by the date shown. If one slips, every later date moves by the same amount; I will re-confirm dates with each
package.

## Dependencies on you (in the order they are needed)

| ID | What | Needed by |
|---|---|---|
| D1 | Approve the deployment/cost plan (03 §2 step 1). Providers and policy are already checked: all five providers Registered, no policy assignment on the group (folder C) – tell me only if a subscription-level rule applies that the group does not show | Tue 27 Oct 12:00 CDT |
| D2 | Administrator runs `admin-role-commands.sh` (2 scoped managed-identity role assignments) and stores the Oxylabs Web API key in the test Key Vault (`oxylabs-webapi-key`), ideally from a separate Web API instance | Tue 27 Oct 17:00 CDT |
| D3 | Approve Test 1 (≤ 19 requests) and Test 2 (≤ 300 requests); the per-request Web API rate is in your Oxylabs dashboard | Tue 27 Oct 17:00 CDT |
| D4 | Test windows (proposed): Test 1 **Wed 28 Oct 09:30-10:00 CDT**; Test 2 **Thu 29 Oct 09:00-10:00 CDT** | Tue 27 Oct |
| D5 | Approve the Test 3 request cap and window (proposed in v1.1.3 from the Test 2 measurement) | Thu 29 Oct 20:00 CDT |
| D6 | Coupon linkage: decide whether a browser feasibility probe (≤ 10 page loads, no account) may be run (04) | any time; not in the dates below |

## Tasks

| # | Task | My time | Needs | Target (US Central) |
|---|---|---|---|---|
| 1 | v1.1.2: total request caps enforced, bounded-test commands, Azure manual execution per test, store/fulfillment evidence, plan | done | – | Sun 25 Oct (this package) |
| 2 | Confirm access in Azure CLI; read-only preflight + what-if of the infra phase | done | RG access | **done** Sat 24 Oct 22:41 CDT (folder C) |
| 3 | Phase 1 infra deploy; send `admin-role-commands.sh` | 1 h | D1 | within 4 h of D1 – Tue 27 Oct 16:00 CDT |
| 4 | Phase 2 job deploy (Manual, default `budget-status`); one `status` execution (0 provider requests) as proof the job runs | 1 h | D2 | Wed 28 Oct 09:00 CDT |
| 5 | **Test 1** in Azure – verify Crystal Lake 53100544 and Vernon Hills candidate 53100502; paging / brand-filter probe; ≤ 19 requests | 15 min run, 2 h review | D3, D4 | Wed 28 Oct 09:30-10:00 CDT; result to you 13:00 CDT |
| 6 | Code adjustment if Test 1 shows paging / brand-filter behaviour that differs from 21 Oct; Vernon Hills enabled only if verified | 0-6 h | 5 | Wed 28 Oct 20:00 CDT |
| 7 | **Test 2** in Azure – Batteries + Light Bulbs, Crystal Lake, no publish, ≤ 300 requests; coverage.json with every count and every gap explained | 45 min run, 4 h review | 5/6, D4 | Thu 29 Oct 09:00-10:00 CDT |
| 8 | **Next reviewable package v1.1.3**: Test 1 + 2 live evidence (ledger, response SHA-256, store/fulfillment ledger, budget ledger, console log), measured requests per CSV row, proposed Test 3 cap and duration | 3 h | 7 | **Thu 29 Oct 17:00 CDT** |
| 9 | **Test 3** in Azure – fresh run of all 28 CSV rows incl. Coupons, Crystal Lake; one forced kill mid-run and resume from checkpoint. Runs entirely in the cloud. | runtime measured in Test 2* (expected under 24 h), my time ~5 h | D5 | start Fri 30 Oct 09:00 CDT; finished by Sun 1 Nov 20:00 CST at the latest |
| 10 | Coverage review of Test 3; re-collect or explain every gap; any fixes | 1 day | 9 | Mon 2 Nov 17:00 CST |
| 11 | Failed-publication proof: scoped run forced to fail, latest/ checksums before/after unchanged (≈ 50 requests) | 2 h | 9 | Tue 3 Nov 12:00 CST |
| 12 | Second execution (repeat) – scoped repeat of 2-3 CSV rows (≈ 1,500 requests, ~3 h) or a full repeat if you prefer (adds 1-2.5 days) | 3 h | your choice + approval | Tue 3 Nov 20:00 CST (scoped) |
| 13 | **Final evidence package v1.2.0**: records, coverage reconciliation, recovery, publication proof, Azure executions, actual Oxylabs requests per test, twice-weekly usage per store from measured figures | 4 h | 9-12 | **Wed 4 Nov 17:00 CST** (scoped repeat) |
| 14 | Coupon linkage: feasibility probe (0.5 day), then implementation if qualifying products load anonymously (2 days) | 2.5 days | D6 | +3 working days after D6; not included in task 13 |
| 15 | Schedule activation (twice weekly) | 30 min | your approval of days/time after review | after task 13 |

\* Throughput measured on 21 Oct: ~8-9 provider requests per minute (131 requests in 16.1 min; 85 in 9 min); at that
rate a 15,000-30,000-request full run would take ~28-56 hours. v1.1.2 removes the main cause: the crawl ran in waves,
and each wave waited for its slowest request (retries and back-off included) while most parallel slots stood idle.
It is now a continuous queue, and the number of parallel requests is a setting. Test 2 measures the real rate and
the request count per CSV row; v1.1.3 will give the measured Test 3 duration and propose the concurrency your
Oxylabs plan allows. The run executes entirely in Azure (one execution may run up to 24 h, and a stopped replica
resumes from its checkpoint automatically), so it does not depend on my machine. The forced kill/resume is a
separate, deliberate step and is reported as such.

## Change from the earlier two-day estimate

The earlier "two days after access and quota" covered roughly tasks 3-8. With access now applied, my own working
time for tasks 2-13 is about 4 working days, spread over 10 calendar days (Sun 25 Oct – Wed 4 Nov) because of the
approval points D1-D5, the agreed test windows and the measured runtime of the full run. Coupon linkage (task 14)
depends on D6 and is not included in the 4 Nov date.
