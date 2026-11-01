# v1.1.11 requirement check

| Client point | Changed surface | Offline proof |
|---|---|---|
| Detect and fix digit-based canary price weakness | `src/wmscraper/runner.py`, `Run.canary_problems` | `test_unrelated_or_nonpositive_display_prices_fail` |
| Prefer numeric `priceInfo.currentPrice.price` | parsed `price_value`, finite-positive validation | `test_finite_positive_numeric_price_passes`, `test_nonfinite_or_nonpositive_numeric_price_fails` |
| Accept only anchored displayed prices | `Run.canary_problems` anchored currency regex | `test_anchored_display_price_passes` |
| Version and release pointer | `src/wmscraper/__init__.py`, `deploy/azure/main.bicep` | full suite: 86 passed |
| No live work | offline tests and source package only | saved `A-OFFLINE/offline-tests-1.1.11.txt` |
