# Digital coupons – UNRESOLVED product linkage (status 25 Oct, unchanged since v1.1.1)

## Linked now (anonymous visitor, current provider)
| Evidence | Source | Fields |
|---|---|---|
| Coupon list | `/savings/cl/coupons/` rendered (coupons.json) | coupon id, full displayed wording incl. qualifier and restrictions ("SAVE $1.00 on 2 Pillsbury™ …", "PICKUP OR DELIVERY ONLY"), expiry, response SHA-256 |
| Product has a digital coupon | Mariano's own search filter `savings=Coupons` (one request per shelf) | per product `digital_coupon_available` + evidence response SHA-256 in observations.json |

This is interim evidence only. In the output, `digital_deals_description` and `digital_deals_price` stay `""` unless
the product's own data shows the terms. No coupon price, PPM or eligibility is calculated or inferred, and a coupon
is never attached to a product by matching words.

## Missing linkage (exact)
For each coupon: its qualifying products (UPCs); per product: the quantity requirement, clip requirement,
eligibility (in-store / pickup / delivery), purchase limit, validity window, and the resulting price when Mariano's
shows one.

Where it lives: the coupon card's "Shop All Items" button opens a script-driven panel that loads the qualifying
products from Mariano's coupon service after the page has loaded; anonymous visitors see "Sign In To Clip". It is
not in the server-rendered HTML the provider returns. Mariano's product pages (/p/…), which may show a product's
coupon, are not served by the provider (HTTP 500 after its retries, 4 tests on 2026-10-21).

What the current provider cannot do (verified 2026-10-21): the Oxylabs Web API Kroger endpoint rejects cookies,
headers and page actions (`HTTP 400 UNSUPPORTED_BODY_PROPERTY`). `run_js` renders the page but cannot click "Shop All
Items", keep a session or sign in.

## Proposed dependency (your decision; nothing assumed, nothing purchased)
1. **Browser feasibility probe, no account** – a self-hosted browser (Playwright) that clicks "Shop All Items" on 3
   coupons for the pinned store and saves the network responses. It needs a US exit IP; options: a proxy product
   on your existing Oxylabs account (Oxylabs bills all products from one shared credit balance), or another US
   proxy you choose. Cap: ≤ 10 page loads. Result: do qualifying products and terms load for an anonymous visitor?
2. **Only if step 1 shows that products or terms need sign-in**: a Mariano's test customer account (credentials in
   Key Vault, never in chat). Not agreed; your decision.
3. If neither is approved, the fields stay empty strings, with the coupon list and the per-product flag as the
   documented interim evidence.

Time once approved: probe 0.5 day; implementation and live check 2 days (02, task 14).
