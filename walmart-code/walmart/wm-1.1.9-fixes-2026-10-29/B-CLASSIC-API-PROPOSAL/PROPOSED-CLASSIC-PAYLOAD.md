# Proposed Classic Web Scraper API request for the Walmart store-verification probe

Status: a proposal for your assessment. It is not approved and has not been run. No paid attempt will be made until
you confirm the entitlement and rate on your plan.

## 1. Source of the proposal (documented, retrieved 2026-10-28)

The Oxylabs documentation pages were saved unchanged in `oxylabs-docs-retrieved-2026-10-28/`:

| File | Retrieved from | SHA-256 |
|---|---|---|
| walmart_product.md | https://developers.oxylabs.io/api-targets/e-commerce/walmart/product.md | 1c9a44c22380bc748e8843945ce8ed18802c2776c82981e5beb5ae0fcf93d380 |
| walmart-sources-overview.md | https://developers.oxylabs.io/api-targets/e-commerce/walmart.md (the page names its canonical path as products/web-scraper-api/targets/e-commerce/walmart.md) | 588593028d7c1397f58a6dc4a7d956511b4e4ebb4a72fb98ac145d8cf12b01ad |

What these pages state (quoted from walmart_product.md):
- Endpoint and authentication: the examples use `POST https://realtime.oxylabs.io/v1/queries` with API user name and
  password, which is the Classic endpoint your plan uses.
- `source` = `walmart_product`; `product_id` = "the number after the product name in the product page URL".
- Localization parameters: `store_id` ("Walmart store number … as a string"), `delivery_zip` ("The nearest store to
  the code becomes the page's store"), `fulfillment_type` (`pickup`, `delivery`, `shipping`; "Use it together with
  `store_id` or `delivery_zip`").
- "without `store_id` or `delivery_zip` it is a random US store".
- "In the case we can't set the `delivery_zip` - Walmart will return their default results without store targeting."
- `parse`: "without it, the response contains the page HTML in `content`."

From walmart-sources-overview.md:
- The two dedicated sources are `walmart_search` and `walmart_product`. "Any other Walmart page can be scraped by
  passing its `url` alone, no `source` needed."
- "For some targets our system **forces JavaScript rendering** even if you do not set `render`; those requests
  count as rendered traffic."

## 2. Exact request per probe request (1.1.8, `fetch.oxylabs.product_payload`)

| # | Page | Body sent to realtime.oxylabs.io/v1/queries |
|---|---|---|
| 1 | Store page walmart.com/store/100 (store identity) | `{"source": "universal", "url": "https://www.walmart.com/store/100", "render": "html", "geo_location": "72712"}` (unchanged; "url alone" route) |
| 2 | Canary 10450114 | `{"source": "walmart_product", "product_id": "10450114", "store_id": "100", "delivery_zip": "72712", "fulfillment_type": "pickup"}` |
| 3 | Canary 43436773 | `{"source": "walmart_product", "product_id": "43436773", "store_id": "100", "delivery_zip": "72712", "fulfillment_type": "pickup"}` |

No `parse` is sent: the scraper reads Walmart's own page data from `content` and verifies it there. It does not
rely on labels in Oxylabs' parsed output. The probe stays inside the existing persistent `probe` budget: 7 of 10
remaining, retries included.

## 3. Pass criteria (from Walmart's response, 1.1.8 `canary_problems`)

Each canary must show all of the following, or the probe stops at that item and the next one is not requested:

- `location.pickupLocation.storeId` = 100
- `location.storeIds` contains 100
- `location.intent` = PICKUP
- a PICKUP option for store 100 in `fulfillmentSummary`
- `fulfillmentType` = STORE (a store-sourced offer)
- a current price > 0
- postal code 72712

Every response is archived first: raw gzip, SHA-256 and the returned context.

## 4. What we have not established (please check on your side)

1. **Entitlement:** whether your Classic plan includes the `walmart_product` source. The documentation describes the
   API; it does not show what any individual plan includes.
2. **Rate:** what `walmart_product` is billed at on your plan. It may not be the "Other results" rate. Walmart pages
   may be force-rendered (rendered traffic), so the $1.35/1,000 rendered rate is the conservative assumption. At
   that rate, 7 requests cost at most about $0.01.
3. **Listings (not part of the probe, but decisive for full coverage):** the 1.1.5 full traversal reads `/browse/`
   category listings. Under the Classic API these are "url alone" pages with no documented store parameters, and the
   27-Oct probe showed that route selects Walmart's own store for the ZIP (4376). `walmart_search` is documented with
   store localisation, but it is a search route, not the category traversal. Whether category listings can be
   pinned to store #100 on your plan is therefore **unresolved**. It needs either a documented store-context route
   for browse pages or a redesigned traversal. I will not assume the newer Web API parameters transfer.
