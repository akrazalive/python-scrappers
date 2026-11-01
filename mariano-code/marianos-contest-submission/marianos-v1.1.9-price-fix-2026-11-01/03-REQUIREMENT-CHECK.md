# v1.1.9 requirement check

| Client point | Changed surface | Offline proof |
|---|---|---|
| Reject unrelated digits and non-positive prices | `src/mscraper/runner.py`, `_has_monetary_price` | `test_unrelated_or_nonpositive_display_text_is_rejected`, `test_nonfinite_or_nonpositive_numeric_prices_are_rejected` |
| Accept real regular and promo prices | `src/mscraper/runner.py`, qualification in `Runner.verify_store` | `test_payable_display_prices_are_accepted`, `test_numeric_regular_and_promo_prices_are_accepted` |
| Keep store and fulfilment context | `Runner.verify_store` and modality-aware price helper | `test_wrong_fulfillment_mode_is_rejected`, `test_verify_store_fixture_with_only_stock_count_is_not_verified` |
| Keep unavailable/no-price production products | production collection and retention paths unchanged | existing full-suite retention tests |
| Version and deployment release pointer | `src/mscraper/version.py`, `deploy/azure/main.bicep`, `CHANGELOG.md` | full suite: 89 passed |
| Offline-only delivery | no deployment or provider requests performed | saved `A-OFFLINE/offline-tests-1.1.9.txt` |
