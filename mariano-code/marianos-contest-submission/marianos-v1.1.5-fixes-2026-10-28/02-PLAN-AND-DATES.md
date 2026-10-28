# Mariano's #69 – plan and dates (US Central, CDT)

Milestones are kept apart: offline / zero-provider Azure / live store test / recovery / full acceptance.

| # | Milestone | Kind | Condition | Date (CDT) |
|---|---|---|---|---|
| 1 | 1.1.5 corrected code, diff, 64 offline tests, recovery/locking design (this package) | offline | – | **completed Tue 27 Oct, 23:00 CDT**; delivered with this message |
| 2 | Redeploy job to 1.1.5 (snapshot checkpoints, live lock) + `selfcheck` | Azure, 0 provider requests | your OK to redeploy | within 2 h of your OK |
| 3 | Test 1 (existing `test1` budget, 19 remaining) on the Classic route in B | live | your check of `kroger_search` entitlement/rate and your OK for that route | within 2 h of approval; result the same day |
| 4 | Test 2 (≤ 300, Batteries + Light Bulbs, no publication) | live | Test 1 passes | started right after Test 1 passes; result within 3 h |
| 5 | Evidence package (you called it v1.1.4; it will carry code 1.1.5): Tests 1-2, measured requests per CSV row, proposed Test 3 cap | report | milestone 4 | 1 working day after Test 2 |
| 6 | Test 3: fresh full run of all 28 CSV rows, forced interruption + same-version resume | live + recovery | your approval of the cap | duration measured in Test 2 (21-Oct throughput suggested 28-56 h) |
| 7 | Failed-publication proof, scoped second (unattended) Azure execution, final evidence | recovery + acceptance | milestone 6, approvals | about 2-3 working days after Test 3 |

The coupon linkage (browser probe decision) remains separate and is not inside these dates. If milestone 3 shows
that the Classic route cannot serve the Mariano's store, everything after it depends on your decision about the
provider route.
