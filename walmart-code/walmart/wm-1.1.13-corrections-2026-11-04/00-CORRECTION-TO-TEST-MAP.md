# Walmart 1.1.13 - correction-to-test map

Scope: the five offline corrections from your static review of 1.1.12 (fingerprint `be5c0469...`).
This is offline engineering only. No Oxylabs request, Azure deployment, redeployment, budget change or Mariano's change was made.
The Walmart probe balance is still **3/10**.

- Package: `walmart-scraper-1.1.13-src.zip`, zip sha256 `48382c21f633fea818aed53329a440398fb774bb977fb72b704dd2a538188835`
- Source fingerprint: `f9e02ced92e5b1056a35de20ee8a8616d23f3e59884162e1430989435897868b`
- Tests: full suite **136 passed**. The same 136 pass from a clean extract of the ZIP.
  - Added: 52 cases in `tests/test_v113_corrections.py` and 1 in `test_detection.py`.
  - Removed: the 6 deal-classification tests, because `parse/deals.py` was removed (point 2).
- Readable copies:
  - `READABLE-CHANGED-FILES-1.1.13.txt`: one text file with path, sha256 and line numbers.
  - `A-CHANGED-FILES/`: the same files at their paths.
  - `B-DIFF/diff-1.1.12-to-1.1.13.patch`: UTF-8, LF, built from the two ZIPs. It also shows the removed `deals.py`.

Line numbers below refer to the 1.1.13 files.

| # | Your finding | Correction (file:line) | Tests (`tests/test_v113_corrections.py` unless noted) |
|---|---|---|---|
| 1 | `classic_payload` dropped page and filter parameters, so page=1 and page=2 built the same request, and the 1.1.12 route test expected that loss. | `fetch/base.py:83` `search_payload`: `page` -> `start_page`; `min_price` / `max_price` are carried as whole numbers, matching the Oxylabs Walmart search parameter table (see "Documentation check"). The mapping lives in `config/settings.yaml:59` `search_params`. Any other parameter (facet, sort, cat_id, a different `stores`) and any invalid or fractional value is **refused** as terminal `compat`, never dropped. `/browse` category URLs do not use this helper (`fetch/base.py:113`). `runner.py:784-797`: a page with exactly the previous page's products fails the listing ("pagination not honoured"), so a repeated page one is never counted as traversal. | `test_search_pages_build_distinct_requests`, `test_search_price_filters_are_carried`, `test_search_unsupported_or_invalid_parameters_are_refused` (10 cases, including `min_price=5.5` and `page=2.0`), `test_category_browse_does_not_use_search_route`, `test_repeated_page_one_is_not_traversal`. The 1.1.12 test is corrected: `tests/test_v112_offline.py::test_walmart_search_route_builds_store_pinned_payload` now expects `start_page: 2`. |
| 2 | `runner._record` still filled the four Walmart deal fields through `deals.classify`. | `runner._record` (`runner.py:851`) no longer classifies offers. `models.py:37-49`: `WALMART_EMPTY_OFFER_FIELDS` are blanked in `Record.to_ordered_dict` and by `enforce_empty_fields`, which `Run.finish` applies to fresh **and** carried-forward records (`runner.py:236`) before anything is written or published. `validate.py:38-40` fails the run if any of the four fields is non-empty. Walmart offers are no longer collected anywhere: `parse/deals.py`, promotion-text parsing (`parse/walmart.py`), the offer census and the deal examples in `report.json` (`report.py`, `tools/`) are removed. | `test_offer_fields_empty_on_fresh_records_despite_displayed_offers` (fixtures display "2 for $9", "Clip Coupon", "$3.50 each with Digital Coupon"), `test_offer_fields_empty_on_carried_forward_records` (old dataset with filled offers carried forward), `test_offer_fields_contract_in_model_and_validation`, `test_detection.py::test_no_offer_collection_for_walmart` (no census, no deal examples, 0% fill). Updated: `test_pipeline.py::test_full_run_publishes_valid_data`, `test_detection.py::test_price_ppm_promotions_only_from_store_offer`. |
| 3 | Collection still used the unanchored `format_price`, so "Only 2 left" or "Save $2" could become a price. | `parse/text.py:43` `listing_price`: a typed number must be finite and > 0; a string must be one whole price token (`$4.98`, `4.98`, `$1,299.50`, `27 ¢`). Validation happens before normalisation. `runner._record` uses it for both listing price fields. A rejected value gives `""` (the product identity is kept, no price is invented) and is logged as a `price_rejected` event. `validate.py:36` also requires prices > 0. | `test_listing_price_rejects_non_prices` (17 cases: "Only 2 left", "Save $2", "2 for $5", ranges, "Now $4.98", 0, negatives, NaN, inf, bool, None), `test_listing_price_accepts_whole_price_tokens` (7), `test_collection_rejects_text_in_listing_price_fields` (full offline collection run). |
| 4 | `_check_context` checked only `storeId`. Listings also need Pickup/ZIP context and a store-bound price/offer chain, with regressions for missing, conflicting and shipping context. Eligible unavailable identities must be preserved. | Page: `runner.py:295` `context_problems` requires the selected `storeId` (and `pickupStore` when present), intent `PICKUP` and the configured ZIP. Each must be present and match. `parse/walmart.py:127-144`: another location block on the page that disagrees is a conflict. Item: `parse/walmart.py:189` `store_offer_problem`, applied in `runner._reject_reason` (`runner.py:838`), rejects items in Walmart's shipping stack, items whose fulfillment summary names another store, and in-stock items with no entry for this store. An unavailable store item (Walmart drops the summary when it is out of stock) is kept with its identity. | `test_listing_context_requires_store_pickup_and_zip` (6 cases: missing intent, SHIPPING intent, missing ZIP, wrong ZIP, missing storeId, conflicting location block; each fails the run and publishes nothing), `test_real_listing_location_shape_passes`, `test_listing_items_need_store_bound_offer_chain` (bound / conflicting / unbound / unavailable / shipping-stack), `test_unavailable_store_item_identity_preserved_in_run`. Existing `test_store_mismatch_blocks_publication` still passes. |
| 5 | `tests/test_v112_offline.py` needs `walmart-500-demo.json`, which was not in the ZIP. | The existing fixture is attached unchanged in `D-FIXTURE/` (sha256 `434f2ceb...`) and is now packaged (`tools/package_source.py`). It was not recreated. `D-FIXTURE/fixture-test-output-1.1.12.txt` holds the recorded 1.1.12 output and a re-run of the delivered 1.1.12 ZIP: 1 failed without the fixture, 3 passed with it. The diff that added the test is `B-DIFF/diff-1.1.11-to-1.1.12.patch`. | `tests/test_v112_offline.py::test_500_product_fixture_passes_offline_contract` (renamed). Its docstring states that the fixture is offline evidence only. The test now also checks that the four offer fields are empty. |

## Documentation check for point 1 (2026-11-04)

The classic-source page (`.../web-scraper-api/targets/walmart/search`) returned HTTP 500 and could not be read.
The Walmart search parameter table I could read is in Oxylabs' API reference
(`developers.oxylabs.io/api-reference/dedicated-scrapers/commerce-scrapers`, section `POST /v1/scrape/walmart/search`).

- It lists `query`, `start_page` (integer), `min_price` / `max_price` (integer), `sort_by`, `store_id`, `fulfillment_type`, `fulfillment_speed`, `domain` and output options.
- It lists **no `pages`** parameter, so 1.1.13 sends none.
- It lists **no `delivery_zip`**. The search template keeps `delivery_zip` from 1.1.12. It is unconfirmed for this route, and any provider rejection of it is a terminal, non-retried error.
- `sort_by` is not mapped, so `sort` stays refused, because its allowed values are not documented.

Whether our account supports this route at all is not verified. The route stays PROPOSED and not run.

## Evidence check on archived real listings (offline, no request)

I parsed the 37 archived store-#100 listing pages already in our evidence folders (1,714 price values) with the new rules:
- All 1,714 real listing price values pass the whole-token check, so the stricter rule rejects none of them.
- All 37 pages carry agreeing `storeId 100 / PICKUP / 72712` blocks, so every page passes the stricter context check.
- 31 out-of-stock store items have no fulfillment summary. These are kept as unavailable identities.
- 1 STORE-typed item sat in Walmart's shipping ("ships instead") stack. 1.1.12 would have accepted it. 1.1.13 rejects it as `shipping_context_not_store_offer`.

## What remains unverified

- Account support for the search route and its parameters (see above). Category browsing is not established by this helper.
- The repeated-page guard compares each page with the page before it. It catches an ignored page parameter. It does not prove that coverage is complete.
- `walmart-500-demo.json` is a fixture, not a genuine 500-product demonstration.

## Walmart completion list (live-offer collection removed)

Offline, done in 1.1.13: items 1-5 above.

Still dependent on your decisions (none of them approved here):
1. Bounded three-request qualification (store page plus two `walmart_product` canaries; retries use the same slots).
2. Fresh store-100 listing and price evidence, and the genuine 500-product demonstration.
3. Full category, subcategory, pagination and detail coverage.
4. UPC/PPM pass.
5. Same-version recovery, failed-publication proof and unattended Azure repeats.

The four volume/digital offer fields stay `""` for Walmart. Walmart offers are not collected, and offer collection is no longer on this list.

## Next checkpoint (CST, UTC-6)

- **Thursday 2026-11-05, 10:00 CST**: offline reply to any findings you raise on 1.1.13 (offline only; no rebuild if nothing changes).
- Live work does not start until you approve it in writing. Nothing live is scheduled.
