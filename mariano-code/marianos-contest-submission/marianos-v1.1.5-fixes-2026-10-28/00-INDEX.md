# Mariano's #69 – marianos-scraper 1.1.5 corrections (2026-10-28)

Hashes (SOURCE_FINGERPRINT-1.1.5.txt; also inside the source zip):
- `code_sha256` 99eafc35962c4fec3abbfab7f28172f15b78d0dd4f533b1aae9b18f817938268 (src/mscraper)
- `release_sha256` f1f7b0cdead650e5160000cdc8c6e62d02b282306270ece42bd36d14b0428256 (src + config + deploy + requirements + Dockerfile)
- `deploy_sha256` fe9215d89659aabd57a1481233a364042c95e5ea5c5d826db26b6d053f1641a8 (deploy/)
- `main.bicep` de5f9776864e2e45c2df1c23392813e1b7ea91895a43d9586e2631423b5076a2

**Offline only:** no provider request, no Azure execution, no deployment since 27 Oct. The Azure budget `test1`
(0 of 19 used) is untouched and keeps its identity.

| Item | Kind | Content |
|---|---|---|
| A-OFFLINE/diff-1.1.4-to-1.1.5.patch | offline | every changed line against the 1.1.4 zip you inspected |
| A-OFFLINE/offline-tests-1.1.5.txt | offline | 64 tests, all passed (46 existing + 18 new in tests/test_v115_safety.py) |
| A-OFFLINE/RECOVERY-AND-LOCKING.md | design | stop rule, exclusive ownership, lease loss, checkpoint flush/restore, hashes; each mapped to its test |
| B-CLASSIC-API-ROUTE/ | proposal | what Oxylabs documents for the Classic API (page saved, hashed), why the earlier Classic body is withdrawn, the proposed documented route, what Test 1 must establish |
| 03-REQUIREMENT-CHECK.md | check | each of your points → where it is done → the test that proves it; corrected 27-Oct timestamps by source |
| 02-PLAN-AND-DATES.md | plan | dated checkpoint plus conditional live and full-completion estimates (CDT) |
| marianos-scraper-1.1.5-src.zip | source | complete source; CHANGELOG section 1.1.5 |
| MESSAGE-TO-CLIENT.txt | | covering message |
| SHA256SUMS.txt | | checksums of everything above |

Your points → tests (tests/test_v115_safety.py):
1. Stop rule → `test_failed_first_store_check_stops_bounded_test_before_any_other_step`, `test_terminal_provider_errors_are_not_retried_and_stop_the_test`
2. Overlap, shared budget, restart → `test_overlapping_execution_is_refused_and_sends_nothing`, `test_budget_needs_the_live_lock_and_survives_restart`, `test_budget_state_is_never_cached_between_two_holders`, `test_inconsistent_budget_fails_closed[...]`, `test_crash_between_ledger_and_state_counts_the_request_as_used`, `test_real_provider_adapter_refuses_to_start_without_the_live_lock`
3. Lease loss → `test_lease_loss_stops_requests_checkpoint_writes_and_publication`
4. Checkpoint integrity / restart → `test_snapshot_checkpoint_survives_hard_kill_and_resumes_without_loss_or_duplicates`, `test_corrupt_or_inconsistent_snapshot_fails_closed`, `test_snapshot_mode_refuses_an_unmanifested_direct_database`
5. Same budget identity → `test_existing_test1_identity_from_azure_is_kept_with_19_remaining`; template hashes → SOURCE_FINGERPRINT-1.1.5.txt; timestamps → `run_test.sh collect` writes timestamps.json
