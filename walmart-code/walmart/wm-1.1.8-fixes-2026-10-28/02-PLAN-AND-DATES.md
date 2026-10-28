# Walmart #32/#38 – plan and dates (US Central, CDT)

Milestones are kept apart: offline / zero-provider Azure / live store test / recovery / full acceptance.

| # | Milestone | Kind | Condition | Date (CDT) |
|---|---|---|---|---|
| 1 | 1.1.8 corrected code, diff, 71 offline tests (this package) | offline | – | **completed Tue 27 Oct, 23:00 CDT**; delivered with this message |
| 2 | Redeploy job to 1.1.8 + `selfcheck` | Azure, 0 provider requests | your OK to redeploy | within 2 h of your OK |
| 3 | Store-verification probe, Classic `walmart_product` route | live, ≤ 7 remaining of the existing 10 | your entitlement/rate check and explicit approval of that route | within 2 h of approval; result the same day |
| 4 | Listing route that can be pinned to store #100 on the Classic plan | design + small live test | milestone 3 passes; a documented route exists; budget approved | about 2 working days after approval; **at risk**, see B §4.3 |
| 5 | Full coverage traversal (≈ 17,000 requests), UPC/data/offer checks, same-version interruption/resume, failed-publication proof, unattended Azure repeat | live, recovery, acceptance | milestone 4 solved; budgets approved; coverage rule decided by you (the proposed exception is withdrawn) | about 5–7 working days after those approvals |

Unavailable eligible products stay retained, and historical observations stay separate from fresh collection, as
in 1.1.5. Unresolved coverage stays blocked, and nothing is published or relabelled.
