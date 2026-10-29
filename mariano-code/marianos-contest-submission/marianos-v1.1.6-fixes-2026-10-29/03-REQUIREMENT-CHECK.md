# Requirement check

| Requirement | File | Regression |
|---|---|---|
| Retailer 401/403 is terminal `refused`, body retained | `src/mscraper/fetch.py`, `src/mscraper/runner.py` | `tests/test_v116_findings.py::test_retailer_refusal_is_terminal_and_saved` |
| Classic brand mapping and page/coupon/unknown rejection | `src/mscraper/fetch.py` | `test_classic_search_maps_brand_and_rejects_unsupported_filters` |
| Mariano's banner is required; Vernon Hills remains separate/disabled | `src/mscraper/runner.py` | `test_non_marianos_banner_is_not_verified` |
| Local SQLite work is isolated per test | `tests/conftest.py` | autouse `isolated_local_work` fixture |

Classic routes are `kroger_search {query, store_id 53100544, fulfillment_type in_store, brand}`.
Pagination beyond page 1 and coupon filtering are explicitly unsupported, so Test 2's page/brand slices
will be partial or stop on Classic. A Crystal Lake pass says nothing about Vernon Hills.

