# Requirement check

| Requirement | File | Regression |
|---|---|---|
| Recheck lease after pacing before reservation/send | `src/wmscraper/fetch/base.py` | `tests/test_v119_findings.py::test_lease_lost_after_pacing_does_not_send` |
| Target 401/403 is terminal `refused` and archived | `src/wmscraper/fetch/base.py`, `src/wmscraper/runner.py` | refusal archive path; existing archive tests plus status-kind regression |
| Provider auth and transient HTTP remain distinct | `src/wmscraper/fetch/base.py` | `test_provider_and_target_statuses_keep_distinct_kinds` |
| No new store claims | `config/settings.yaml`, `docs/CHANGES.md` | product canaries remain the only probe route |

The store page probe body remains `universal`. Product canaries use
`{"source":"walmart_product","product_id":"10450114","store_id":"100","delivery_zip":"72712","fulfillment_type":"pickup"}`.
The listing route remains unresolved; `walmart_search` is proposed only as a separate later probe.

