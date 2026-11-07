# Walmart 1.1.14 - correction-to-test map

Scope: the one finding from your static review of 1.1.13 (fingerprint `f9e02ced...`): `parse/walmart.py` `page_location` did not compare `pickupStore` across location blocks.
This is offline engineering only. There was no Oxylabs request, Azure deployment, redeployment or budget change, and nothing in Mariano's was touched.
The Walmart probe balance is still **3/10**.

- Package: `walmart-scraper-1.1.14-src.zip`, zip sha256 `0a67dce9d2836f43871efa3cc2c06edb4c8dc938191b2a1ab43ec76839844d76`
- Source fingerprint: `dc4c4783a85526bf033ba687d05b1f294cf9bd45303123d5af55fb4abf7b125c`
- Previous: 1.1.13 source `f9e02ced92e5b1056a35de20ee8a8616d23f3e59884162e1430989435897868b`, zip `48382c21f633fea818aed53329a440398fb774bb977fb72b704dd2a538188835`. 1.1.13 is unchanged and stays identifiable.
- Package entries: 55 files + `MANIFEST.txt` + `SOURCE_FINGERPRINT.txt` = 57. 1.1.13 had 56; the added entry is `tests/test_v114_corrections.py`.
- Changed files (4): `src/wmscraper/parse/walmart.py`, `src/wmscraper/__init__.py` (version), `docs/CHANGES.md`, `tests/test_v114_corrections.py` (new).
- Tests: full suite **145 passed** (136 + 9 new), run from a clean extract of the 1.1.14 ZIP (`C-TESTS/tests-full-1.1.14.txt`).
- The new tests run against unchanged 1.1.13 code: **4 failed, 5 passed** (`C-TESTS/new-tests-run-against-1.1.13.txt`). The 4 failures are the contradictory-block cases. The 5 passes are the agreeing-block and unavailable-identity controls, which should pass on both versions.

Line numbers refer to the 1.1.14 files.

| # | Your finding | Correction (file:line) | Tests (`tests/test_v114_corrections.py`) |
|---|---|---|---|
| 1 | `page_location` compared secondary blocks on `storeId`, intent and `postalCode`, but not `pickupStore`. With primary `pickupStore=100` and secondary `pickupStore=9999`, `conflicts` was empty and `Run.context_problems` returned no errors. | `parse/walmart.py:141-147`. Every secondary block's `pickupStore` is compared with the page's pickup store. That is the first block's `pickupStore`, or its selected `storeId` when the first block names none. A block that disagrees goes into `conflicts`. `runner.py:307-308` (unchanged) turns each conflict into a store-context error, so the listing fails and nothing is published. The existing checks are unchanged: the first block's `pickupStore` must equal the configured store (`runner.py:301`), plus `storeId`, `PICKUP` and ZIP. | `test_contradicting_secondary_pickup_store_is_a_conflict` (2 cases: your 100/9999 shape with the test store, and a first block with no `pickupStore`). `test_contradicting_third_block_pickup_store_is_a_conflict` (a disagreeing third block is also caught). `test_contradicting_secondary_pickup_store_fails_the_run` (full offline collection: validation fails, `published` is None, `latest/` is not written, and the `store_mismatch` event names the 9999 block). |
| 1a | Keep eligible unavailable identities. | No change to `store_offer_problem` or `_reject_reason`. | `test_unavailable_identity_kept_with_agreeing_pickup_store_blocks`: a page with two agreeing blocks that both carry `pickupStore` keeps the out-of-stock Lay's item with its UPC and price, and the run validates. The 1.1.13 tests `test_unavailable_store_item_identity_preserved_in_run` and `test_listing_items_need_store_bound_offer_chain` still pass. |
| 1b | No false conflicts on the real page shape. | - | `test_agreeing_pickup_store_blocks_pass` (4 cases: both blocks carry the same `pickupStore`, only one carries it, neither does). The 1.1.13 test `test_real_listing_location_shape_passes` (the archived store-100 shape) still passes. |

## Archived real listings (offline check, no request)

On 2026-11-05 I parsed every archived Walmart page in our evidence folders with the 1.1.14 `page_location`. Duplicates were removed by content hash.
- 59 distinct pages carry a selected-location block. All 59 show `storeId 100 / pickupStore 100 / PICKUP / 72712`.
- 39 of them are listing pages (`searchResult`) with two blocks. The secondary block carries `pickupStore 100` on all 39, so each one is a real example of the agreeing two-block shape.
- Conflicts under the 1.1.14 rule: **0**. The stricter rule changes no result on the real data we hold.

(The 1.1.13 report counted 37 listing pages. Today's count of 39 comes from a full scan of every evidence folder, deduplicated by content hash.)

## What this does not establish

- The pages tested here are synthetic fixtures. This change is offline logic. It does not show that a live listing returns a valid store-100 Pickup context.
- Account support for the proposed search route and its parameters is still unverified. `delivery_zip` and the search route remain qualification questions, not working routes.
- `walmart-500-demo.json` remains an offline fixture, not a genuine demonstration.

## Balance and approvals

- The Walmart probe balance is still **3/10**. Nothing ran in the November 4 window, and nothing will run automatically. That window is not treated as approved.
- Live qualification, redeployment and any paid request each need your written approval.
