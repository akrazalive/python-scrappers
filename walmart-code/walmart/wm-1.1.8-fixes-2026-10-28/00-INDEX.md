# Walmart #32/#38 – walmart-scraper 1.1.8 corrections (2026-10-28)

source_sha256 `f3396f3a237afd416fcd2c559425e66ca8e8152c6440e1de6e1d8d8910b8f4e0`. This fingerprint covers src, config,
deploy (template + scripts), tools, tests, requirements and Dockerfile; see SOURCE_FINGERPRINT-1.1.8.txt.
**Offline only:** no provider request, no Azure execution, no deployment since 27 Oct. The 27-Oct failure and the
`probe` budget (3/10 used, 7 remaining) are preserved, and publication stays blocked.

| Item | Kind | Content |
|---|---|---|
| A-OFFLINE/diff-1.1.7-to-1.1.8.patch | offline | every changed line against the 1.1.7 zip you inspected |
| A-OFFLINE/offline-tests-1.1.8.txt | offline | 71 tests, all passed (49 existing + 22 new in tests/test_v118_safety.py) |
| B-CLASSIC-API-PROPOSAL/ | proposal | exact documented Classic request per probe request, the Oxylabs pages it is based on (saved, hashed), pass criteria, and what is NOT established (entitlement, rate, listing route) |
| 03-REQUIREMENT-CHECK.md | check | each of your points → where it is done → the test that proves it |
| 02-PLAN-AND-DATES.md | plan | dated checkpoint plus conditional live and full-completion estimates (CDT) |
| walmart-scraper-1.1.8-src.zip | source | complete source; docs/CHANGES.md section 1.1.8 |
| MESSAGE-TO-CLIENT.txt | | covering message |
| SHA256SUMS.txt | | checksums of everything above |

Your five points → test(s) in tests/test_v118_safety.py:
1. Budget across overlapping executions → `test_two_holders_of_a_one_request_budget_cannot_both_reserve`, `test_overlapping_execution_is_refused_before_any_request`, `test_budget_requires_the_live_lock`, `test_deleted_state_with_remaining_ledger_never_resets_to_zero`, `test_inconsistent_state_fails_closed[...]`, `test_existing_azure_probe_identity_keeps_its_7_remaining`, `test_lease_loss_stops_requests_checkpoint_writes_and_publication`
2. Stop at first failed canary; terminal vs retryable → `test_first_wrong_store_canary_stops_before_the_second_request`, `test_verify_store_returns_failure_when_any_canary_fails`, `test_auth_failure_is_terminal_and_not_retried`
3. Fulfillment, not just store id → `test_configured_store_id_alone_is_not_enough[intent SHIPPING / FC / no PICKUP option / no price]`, `test_correct_store_fulfillment_and_price_pass`
4. Archive every canary before validation → `test_canary_responses_archived_with_hash_and_context_even_when_failing`
5. `--categories` → `test_exact_documented_categories_command_resolves_food_and_pets_with_the_real_config`, `test_documented_categories_command_runs`
