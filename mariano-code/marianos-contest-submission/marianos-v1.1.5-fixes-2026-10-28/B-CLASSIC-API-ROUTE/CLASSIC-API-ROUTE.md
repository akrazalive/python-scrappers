# Mariano's – the Classic Web Scraper API route (found while preparing 1.1.5)

Status: a proposal for your assessment. It is not approved and has not been run.

## What Oxylabs documents (page saved unchanged: `oxylabs-docs-retrieved-2026-10-28/kroger.md`)

- Retrieved 2026-10-28 from https://developers.oxylabs.io/api-targets/e-commerce/kroger.md
- SHA-256 `fcacaeec85eb5239efa59f0d2eaec44898118b1466b492aea8f3aa4cc11c752f`

- Classic endpoint `realtime.oxylabs.io/v1/queries`, two dedicated sources: `kroger_search` (`query`) and
  `kroger_product` (`product_id`). "Any other Kroger page can be scraped by passing its `url` alone, no `source`
  needed."
- Localization for both sources: `store_id` ("the division number and the store number … joined together", e.g.
  `01100002`), `delivery_zip`, `fulfillment_type` (`pickup`, `delivery`, `in_store`; pickup and in_store need
  `store_id`). "A `store_id` that is not a Kroger store … returns `status_code` 400."
- These sources target **kroger.com**. No Mariano's source and no store parameters for marianos.com URLs are
  documented on the Classic API. (A dedicated Mariano's endpoint with `store_id` exists only on the newer Web API,
  `webapi.oxylabs.io/v1/scrape/marianos`, which is not your plan.)

## Consequence

The 1.1.0-1.1.4 Classic body `{"source": "kroger", "url": <marianos.com URL>, "store_id": "53100544"}` is **not a
documented Classic request**. Test 1 with it would most likely have failed on its first request. 1.1.5 withdraws it.

## Proposed 1.1.5 Classic requests (`config/settings.yaml` → `fetch.oxylabs_realtime`)

| Page | Body |
|---|---|
| Search pages (Test 1 store check, probe, Test 2 shelves) | `{"source": "kroger_search", "query": "<query>", "store_id": "53100544", "fulfillment_type": "in_store"}` |
| Other pages (department, coupons) | `{"url": "<marianos.com URL>"}` (no documented store parameters) |

`53100544` is Crystal Lake's division (531) plus store (00544), the documented format.

## Not established (Test 1 decides; nothing is assumed)

1. Whether your plan includes `kroger_search` and its rate. Kroger pages may be force-rendered (rendered traffic),
   so I budget at $1.35/1,000. All of Test 1 (19 requests) costs at most about $0.03.
2. Whether kroger.com, with store 53100544, returns the **Mariano's Crystal Lake** store context, in-store modality
   and that store's own prices. The scraper reads all three from the returned page (Test 1 step 1). If not, step 1
   fails, the stop rule ends Test 1 after that first request, and I report it.
3. Department and coupon pages via `url` alone have no documented store pinning. Every such page must pass the
   store check, or it is not used.
