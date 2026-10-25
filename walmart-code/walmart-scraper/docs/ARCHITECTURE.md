# Architecture

```
 Azure Container Apps Job (cron Mon+Thu 06:00 UTC, parallelism 1)
   └─ python -m wmscraper run-all            ── for each enabled location in config/locations.yaml
        1 lock          Blob lease per location → overlapping runs are impossible
        2 store         /store/<id> → id, name, address, ZIP must match config
        3 canary:start  known items must show a local Walmart offer at this store
        4 discovery     category pages → subcategory listings (CSV exclusions applied)
        5 listings      every page: shape check · store check · filters · dedup → checkpoint
        6 enrichment    product page: UPC, size, store re-check, marketplace re-check, deals
        7 canary:end
        8 validate      all checks pass → publish latest/  ·  otherwise keep last good data
   Fetch layer: pacing · retries + backoff · challenge / tiny-page / latency detection
   Provider: Oxylabs Web API, Walmart endpoint (store_id, fulfillment_type=pickup, delivery_zip per request)
             alternatives: Oxylabs Scraper API | Zyte | Playwright (settings.yaml; secrets in Key Vault)
   Storage: Blob  <location>/runs/<run_id>/…   <location>/latest/…   checkpoint.sqlite
   Logs: JSON lines → Log Analytics (store, category progress, retries, errors, counts, status)
```

## Data-quality rules

| Requirement | Implementation |
|---|---|
| Correct store | Store page verified (id, ZIP, street address) before collection. Every request is pinned to the store (provider `store_id`, `fulfillment_type=pickup`, `delivery_zip`, listing `stores=<id>`). **Every** listing and product page must report `pageMetadata.location.storeId` = configured store; any mismatch fails the listing and blocks publication. |
| Local pickup / in-store context | Per item: `fulfillmentSummary` must contain `PICKUP` (or in-store) **at the configured store id**; Walmart's secondary "ships instead" stack (`puShipFul`) is excluded. |
| Shipping-only offers | Excluded (`shipping_only_or_not_at_store`). |
| Marketplace prices | Excluded unless the seller is Walmart.com (seller id `F55CDC31…`), checked on listing **and** product page. |
| Sponsored placements | Real local products are kept **once**; repeated sponsored/organic/category appearances are removed by item-id dedup and counted in `duplicates_prevented`. |
| Duplicates | Primary key = Walmart item id across the whole run (pagination overlap, repeated category, sponsored copy). Counted as `duplicates_prevented`. |
| Approximate weight | Walmart `averageWeight` / sold-by-weight flag, title and product size checked for approx / approximately / avg wt / ~ / weight varies → excluded. |
| PPM | Walmart's displayed `UNIT_PRICE` price line copied verbatim (e.g. `10.2 ¢/fl oz`); empty when not shown; never computed. |
| UPC / GUPC | UPC from the product page, never altered. `gupc` always `""`. |
| unit_price | Always `""` (downstream pipeline). |
| Prices | `regular_price` = was-price when on sale, else current; `sale_price` = current when a was-price exists. Two-decimal strings. |
| Volume vs digital deals | `parse/deals.py`: clip / coupon / activate / add offer → digital; N for $X, BOGO, mix & match, must buy, buy N → volume. Wording preserved; price only when displayed; Walmart Cash / cashback / rebates never treated as price reductions. |
| Private label | `config/private_label_brands.txt` matched against brand and title start → `store_brand` = `yes` / `no`. |

## Category discovery

Each CSV category is opened as a store-scoped listing (`/browse/<category id>`). If Walmart reports more products than
the 25-page window can show, the node is split into the children of its **Departments** navigation facet (depth-first,
direct children only), until every crawled listing fits the window. Exclusions from the CSV notes ("Recipes", "Farm
Animals", "Shop All Foods") and configurable merchandising-shelf patterns are skipped; overlaps are removed by item-id
dedup.

## Silent-blocking and completeness detection

* Bot-challenge markers, block-page redirects, HTTP errors, tiny responses and abnormal latency are detected per request.
* Every parser validates the response **shape**; a changed or partial page raises `ShapeError` instead of returning 0 items.
* A listing that finishes with **zero** items fails validation – a block is never a legitimately empty category.
* Category counts are compared to the last successful run; a drop below `yield_drop_threshold` (60 %) blocks publication.
* Canary items are read at the start and end of the run; failure = run treated as blocked.
* Listings that hit Walmart's 25-page cap are flagged so they can be split further.

## Failed runs never replace good data

1. Every run writes only to `runs/<run_id>/`.
2. `latest/` is updated only after validation passes: stage → keep `previous-*` → swap → manifest (commit point).
3. Blob versioning + soft delete (14 days) give an extra rollback path.
4. An aborted production run keeps its checkpoint and `state.json` points to it; the next run **continues** it.

## Checkpointing

SQLite per run: listing table (next page, status), items table (record per item id), seen table (kept / skipped
reason), meta (store verification, canaries, runtime). Each page's records and the page pointer are written in **one
transaction**, so a crash can neither lose nor duplicate a page. In Azure the database is uploaded to Blob after every
committed page.
