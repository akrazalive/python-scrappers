# Digital coupons – what is linked now, what is missing, and the exact dependency

## Linked now (anonymous, via the current provider)
| Evidence | Source | Fields |
|---|---|---|
| Coupon list | `/savings/cl/coupons/` rendered (coupons.json) | coupon id, full displayed wording incl. qualifier and restrictions ("SAVE $1.00 on 2 Pillsbury™ …", "PICKUP OR DELIVERY ONLY"), expiry, response SHA-256 |
| Product has a digital coupon | Mariano's own search filter `savings=Coupons` (one request per shelf) | per product `digital_coupon_available` + evidence response SHA-256 in observations.json |

Output fields stay `""` for digital deals unless the product's own data shows the terms. No coupon price, PPM or
eligibility is calculated or inferred, and a coupon is never attached to a product by matching words.

## Missing linkage (exact)
For each coupon: its qualifying products (UPCs), and per product the coupon's quantity requirement, clip requirement,
eligibility (in-store / pickup / delivery), purchase limit, validity window and the resulting price when Mariano's
shows one.

Where it lives: the coupon card's "Shop All Items" button opens a script-driven modal that loads the qualifying
products from Mariano's coupon service after the page has loaded; anonymous visitors see "Sign In To Clip". It is not
in the server-rendered HTML that the provider returns, and Mariano's product pages (/p/…), which may show the coupon
for a product, are not served by the provider (HTTP 500 after its retries in 4 tests on 2026-10-21).

What the current provider cannot do (verified 2026-10-21): the Oxylabs Web Scraper API Kroger endpoint rejects
cookies, headers and page actions (`HTTP 400 UNSUPPORTED_BODY_PROPERTY`), so it cannot click "Shop All Items",
keep a session, or sign in.

## Proposed dependency (not assumed, nothing purchased)
1. A browser path that can click and capture the page's network responses for a pinned store: either a provider
   product that supports browser instructions / sessions, or a self-hosted browser (Playwright) behind a US proxy.
   First step: a feasibility probe of at most 10 requests on 3 coupons – do qualifying products load for an
   anonymous visitor? No account is needed for this step.
2. Only if qualifying products or clip-only terms require sign-in: a Mariano's test customer account (credentials in
   Key Vault, never in chat). Not agreed; requires the client's decision.
