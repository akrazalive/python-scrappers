# Mariano's v1.1.10 - readable handoff (same version, not rebuilt)

This is exactly the version you named: `marianos-v1.1.10-vernon-pickup-2026-11-03.zip`, containing
`marianos-scraper-1.1.10-src.zip` (sha256 `438133ff21950e002fc594199dd1ebfbb5eaec7485e5384173f695a2654c499d`).
Nothing was changed or rebuilt, and that ZIP is not sent again. Every file here was copied byte-for-byte from it.
Check: 66 of 66 files, 0 differences.

- `code_sha256` 94d4da6a6dc2256fb8010c2c5810b440cc9d8d23f994845fe7d33c06ee936400
- `release_sha256` e8e1412b861a680e2e5e94c3afcc14d725ed4e9bf16d8f84f364722d393fa30e

## Contents

| Item | What it is |
|---|---|
| `READABLE-PRIORITY-FILES-1.1.10.txt` | One plain-text file with the priority files below, in your order. Each has its path, sha256 and line numbers. |
| `A-SOURCE-1.1.10/marianos-scraper/` | The complete package unpacked (66 files). It can be hosted as a read-only folder or repository. |
| `A-SOURCE-1.1.10/FILE-HASHES-1.1.10.txt` | sha256 of every packaged file. |
| `B-DIFF/diff-1.1.9-to-1.1.10.patch` | Normalized diff (UTF-8, LF) built from the delivered 1.1.9 and 1.1.10 ZIPs. The earlier copy was UTF-16, which is why it showed as binary. |
| `C-TESTS/` | The 1.1.10 test output as sent (converted to UTF-8), plus a re-run from the unpacked package on 2026-11-04: **92 passed**. |
| `01-ONE-REQUEST-QUALIFICATION.md` | The proposed single request: command, query, body, deadline, CST time, approval condition and the expected redacted receipt. |

## Priority files (your order)

| Priority | File (sha256) | Where to look |
|---|---|---|
| Qualification-price helper | `src/mscraper/runner.py` (`b73fd413...`) | `_DISPLAY_PRICE_RE` line 32. `_positive_number` 35: finite > 0, not bool. `_has_monetary_price` 39: regular/promo block, modality filter, numeric or anchored display price. `_has_qualifying_store_price` 59: price source must be the configured store. `verify_store` 162: the 8 checks. |
| Location / request builder | `src/mscraper/fetch.py` (`3b6c2d73...`) | `realtime_payload` 280: `kroger_search` body. `store_id` and `fulfillment_type` come from the location. Page > 1 and `savings` are refused as `compat`. `get` 105: request cap, ledger entry before sending, retries. |
| | `src/mscraper/config.py` (`56f68ab6...`), `config/locations.yaml` (`87d1bc29...`), `config/settings.yaml` (`9248f21f...`) | Vernon Hills `53100502` / `60061` / `1720 N Milwaukee` / `PICKUP`, enabled. Crystal Lake `53100544` disabled, diagnostic only. The `search_payload` template. |
| Listing adapter | `src/mscraper/parse.py` (`004a27d8...`) | `search_page` 219, `map_product` 330. Query slicing in `runner.py` `_slice` 446 and `_expand` 469. |
| Publication gates | `src/mscraper/validate.py` (`946fd276...`) | `validate_run` 63. Publication decision in `runner.py` `finish` 574. |
| Bounded tests / budget | `src/mscraper/cli.py` (`f574cafc...`), `src/mscraper/budget.py` (`025d2fea...`) | `BOUNDED_TESTS` 98: Test 1 total 19, Test 2 total 300. `TotalBudget.take` writes the ledger line before the counter. |
| Tests | `tests/test_v1110_scope.py`, `tests/test_v119_price.py`, `tests/test_v112_bounded_tests.py` | Scope, payload pinning, price rule, budget caps. |

## Balances (unchanged)

The Mariano's Test 1 budget is still **0/19**. No Oxylabs request, Azure change, deployment or run was made for this handoff.
