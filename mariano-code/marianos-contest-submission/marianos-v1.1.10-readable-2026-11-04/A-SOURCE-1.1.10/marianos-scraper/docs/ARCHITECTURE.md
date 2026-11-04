# Architecture

```
config/ (CSV categories, stores, settings, store brands)
        │
        ▼
   Runner (one store) ──► Fetcher (Oxylabs Kroger endpoint, store_id pinned, pacing, retries, block detection)
        │                         │
        │                         ▼
        │                 marianos.com page  ──►  parse.py (application state → store, shelves, products, coupons)
        ▼
  Checkpoint (SQLite)  ──►  validate.py  ──►  report.py  ──►  storage.py (local / Azure Blob, safe publish)
```

## Data flow per run

1. **Store verification** – a canary search page is read with the store pinned. The page's store details
   (`modalityPreferences.storeDetails`) must show the configured location id, ZIP and address; the search request
   itself must carry that location id; every price on the page must have `sourceLocationId` = configured store.
2. **Canary (start)** – the canary search must return store-priced products including the configured canary UPCs.
3. **Discovery** – each `/d/<department>` URL from the CSV is opened; its sub-category links
   (`navItems`) become listings. `/pl/<slug>/<taxonomy>` links are read through Mariano's search
   (the `/pl/` pages themselves are not served to automated clients) and filtered to products whose
   `subCommodityCode` starts with that taxonomy id, so a product is only assigned to the sub-category it belongs to.
   Curated shelves (e.g. *Steaks*) are read from their own search URL and filtered to the department code.
   Pure brand shelves (*Simple Truth*, *Private Selection*, *Kroger*) are skipped – they only repeat products of real
   sub-categories. `/pl/` rows in the CSV (Batteries, Light Bulbs, …) are one listing each.
4. **Crawl** – every listing is paged (24 per page) until Mariano's returns a short page (end of results), three
   consecutive pages contain nothing of the target sub-category, or the ~1,000-result search window is reached
   (reported as a warning). Each page is committed atomically with its records.
5. **Coupons** – the CSV's coupons URL is rendered and every displayed digital coupon (id, wording, expiry) is saved
   to `coupons.json`.
6. **Canary (end)**, **validation**, **report**, **publication** (only if valid).

## Field rules

| Field | Source / rule |
|---|---|
| zipcode, store_name, store_location | store details of the verified store (e.g. `60014`, `Marianos Crystal Lake`, `105 Northwest Hwy, Crystal Lake, IL 60014`) |
| store_logo | Mariano's logo image on the page |
| store_brand | `yes` when the brand is in `config/private_label_brands.txt` (Roundy's, Kroger, Simple Truth, Private Selection, …), else `no` |
| category / sub_category | CSV category / Mariano's sub-category name from the department page |
| product_title | item description |
| weight | `customerFacingSize` as displayed (e.g. `1/2 gal`, `6 ct / 8 fl oz`) |
| regular_price | store regular price |
| sale_price | store promo price when it is a single-unit price lower than regular (what the card shows as Sale/Price Cut) |
| volume_deals_* (v1.1.0: + terms) | multi-buy prices (`nfor` > 1, e.g. "2 for $5.00" → price 5.00) and offers that need no clipping (e.g. `MEGA_EVENT` "Save $1 each when you buy 5 or more" → description only, no calculated price) |
| digital_deals_* | offers requiring clip / digital coupon; price only when written ("$3.99 each with Digital Coupon") |
| image_url | the product-card image URL (front, medium) exactly as served |
| url | Mariano's product URL (`shareLink`) |
| upc | Mariano's 13-digit UPC, never modified |
| gupc, unit_price | always `""` |
| ppm | `equivalizedUnitPriceString` exactly as displayed, from the price the card shows (promo if on sale) |
| crawl_date | run date (YYYY-MM-DD), last field |

Retention (v1.1.0): products without a current store price are KEPT with empty price fields (`observations.json`
`availability: no_store_price`); products without a UPC are KEPT with `upc` empty and Mariano's product id recorded as
`source_product_id` (never in `upc`); products a run does not return are CARRIED from the last published dataset with
their own last `crawl_date` (`status: carried`, `last_observed`, `carried_since`). The UPC only ever comes from
`item.upc`; in all sampled real responses `item.upc` = product key = `data.id`, and a top-level `prod.id` does not exist.

Excluded and counted in the report (`exclusions.json`, with the exact trigger): products whose own size or price wording
is approximate / estimated (e.g. "about $10.39 each"); products from a different store (fails the run); products outside
the shelf's sub-category; duplicates (first placement wins). A product is never excluded only because it is sold by
weight, and titles (e.g. "(About 3 Steaks per Pack)", "Family Pack") never trigger an exclusion or a deal.

## Silent-blocking and completeness detection

* response shape: missing application state, challenge page, response below `fetch.min_page_bytes` → retried, then failed
* upstream failure: a search page that lists UPCs but carries no product details (Mariano's product service timed out) is
  **not** treated as an empty page – it is retried and fails the shelf if it persists
* store context on every page and every price (`store_mismatches` must be 0)
* canary search at start and end of the run
* zero products on a shelf, category below minimum, yield drop vs the last published run → run not published
* per-category report: shelves discovered / done / failed, pages read, products listed, products of the sub-category, kept

## Failed runs never replace good data

`latest/` is written only by `storage.publish()`, which is called only when validation passed and the run was not a
scoped demo. Files are staged first and the manifest is written last (commit point); the previous dataset is kept as
`previous-records.json`. A run that fails keeps its own files under `runs/<run_id>/` for diagnosis only.

## Interruption recovery

Each page's records and the listing's next-page pointer are written in one SQLite transaction. `run --resume`
(and every scheduled run) continues the latest unfinished run: verified store, discovery results and committed pages are
reused; failed shelves are retried; UPC is the primary key, so nothing is stored twice.


## Coverage proof (v1.1.0)

Mariano's server-rendered search returns the first 24 results of a request whatever page number is asked for
(verified: page 2 returns the same 24 UPCs with re-numbered ranks 25-48). Each seed request (shelf name / parts) that
reports more products than it returned is partitioned with Mariano's own `brandName` filter; `coverage.json` reconciles
every seed request's reported total against the distinct products read across the request and its brand slices
(`gap` = remaining products, 0 = proven complete). Expansion requests add products and brands and are listed separately.

## Provenance (v1.1.0)

`ledger.json`: one row per page used – time, kind, URL, SHA-256 + size of the exact response, store and request location
ids and active modality read from it, products listed / priced, `sourceLocationId`s on its prices.
`evidence/pages/<sha256>.json.gz`: the price-bearing excerpt of every page; `evidence/raw/`: full HTML for the first pages
per category. `observations.json` links every output row to the SHA-256 of the response it was read from.
`report.json → provenance`: code SHA-256, config file SHA-256s, requirements SHA-256, Python, argv – recorded at run start,
at every resume and at finish.
