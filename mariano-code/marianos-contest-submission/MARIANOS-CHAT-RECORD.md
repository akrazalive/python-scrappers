# Mariano's Scraper Contest – complete record of our work (chat summary)

Prepared 2026-10-24 for Asif Khan. Covers everything in this chat about the Mariano's contest: the brief, how the
scraper was built, every live run, every package sent, the client's reviews and our replies, and what is still open.
Times are UTC unless noted. (Walmart is handled in a separate Claude session and is not covered here.)

---

## 1. The contest brief (Freelancer, prize $700)

**"Build a production-ready Mariano's scraper for Microsoft Azure."** Key requirements:

* Mariano's (Kroger-owned). Collect location-specific products, prices, measurements, promotions, categories and
  subcategories; run in the client's existing Azure; scrape each location **twice per week**; support multiple locations.
* Process every category/subcategory in `Marianos_Category_URLs.csv` (28 rows incl. Coupons); broadest catalogue, not
  only featured/sale items; verify the store stays selected; detect duplicates, missing categories, empty/thin results;
  never overwrite good data with an empty or incomplete run.
* **Exact 22-field JSON order:** zipcode, store_name, store_location, store_logo, store_brand, category, sub_category,
  product_title, weight, regular_price, sale_price, volume_deals_description, volume_deals_price,
  digital_deals_description, digital_deals_price, image_url, url, upc, gupc, ppm, unit_price, crawl_date.
* Rules: missing values = empty strings (no nulls); scrape UPC; exclude approximate-weight products; preserve URLs;
  store_brand default "no"; **PPM scraped exactly as displayed, never calculated**; `unit_price` and `gupc` always empty.
* Deals: volume (no clipping) vs digital (clip/activate) kept separate, retailer wording preserved, no calculated prices.
* Technical: Python/Playwright preferred; Azure unattended; store selection by ID/ZIP; pagination, lazy loading;
  pacing, retries, logging, checkpoints, safe resume; silent-block detection; secrets outside code.
* Entry: working demo with ≥ 500 valid records from one location, multiple categories, counts, duplicates,
  completeness, PPM/deal examples, store proof, architecture, cost, evidence the scraper produced the data.
* Files: `D:\PROJECTS\Monthly-Test\Marianos_Category_URLs.csv`, `Shared_Scraper_Technical_Requirements.docx`.

---

## 2. Investigation (21 Oct) – how Mariano's can be read

| Finding | Detail |
|---|---|
| Direct access blocked | marianos.com times out from Pakistan (bot protection / geo); Playwright direct not possible |
| Provider | Oxylabs Web Scraper API, Kroger endpoint `webapi.oxylabs.io/v1/scrape/kroger` (Bearer key already in walmart-scraper `.env`) |
| Store pinning | `store_id: "53100544"` → Mariano's **Crystal Lake**, 105 Northwest Hwy, Crystal Lake, IL 60014 – every price carries `sourceLocationId` |
| Data source | Mariano's server-rendered page state `window.__INITIAL_STATE__` (JSON): store prices, promo, `equivalizedUnitPriceString` (PPM as displayed), UPC, offers, taxonomy, images |
| Blocked page types | `/pl/` product-list pages and `/p/` product pages fail through the provider (HTTP 500 after retries); search pages work |
| Discovery | Department pages often fail → the **site menu** (embedded in every page) gives every department's subcategories with taxonomy ids |
| Pagination | **Mariano's server search returns the first 24 results for every page number** (page 2 = same 24 UPCs, ranks renumbered) |
| Deals | Volume offers (`MEGA_EVENT` "Save $1 each when you buy 5 or more", "2 For $5.00") are in product data; digital coupon terms are not shown to anonymous visitors on products |
| Coupons page | Rendered page lists coupons (id, wording, expiry); "Shop All Items" (qualifying products) loads in the browser only |
| Weight items | Sold-by-weight products show "about $10.39 each" (estimated) |

---

## 3. What was built – `D:\PROJECTS\Monthly-Test\marianos-scraper`

Python 3.12/3.13, asyncio. Package `src/mscraper/`:

| Module | Role |
|---|---|
| `fetch.py` | Oxylabs Kroger fetcher (store pinned), pacing, retries/backoff, block detection, request budget; fixture fetcher for tests; (1.1.1) classic `realtime.oxylabs.io` adapter |
| `parse.py` | page state extraction, store info, department/menu shelves, search pages, product → 22-field record, coupons |
| `deals.py` | volume vs digital classification, prices only when displayed, (1.1.0) complete terms |
| `runner.py` | verify store → canary → discovery → crawl → coupons → validate → publish; checkpoints; (1.1.0) ledger, brand slices, observations, carry-forward |
| `checkpoint.py` | SQLite run state (listings, items, ledger, observations, exclusions, coupon flags) |
| `validate.py` / `report.py` | publication gate / run report |
| `storage.py` / `lock.py` | local or Azure Blob, safe publish (`latest/` only after validation), run lock |
| `coverage.py`, `evidence.py`, `retention.py`, `probe.py` | (1.1.x) coverage reconciliation, provenance, carried products, live probe |
| `config/` | `categories.csv`, `locations.yaml`, `settings.yaml`, `private_label_brands.txt` |
| `deploy/azure/` | Bicep + `deploy.sh` (+ 1.1.0 `preflight.sh`, `collect_evidence.sh`) |
| `tests/` | offline tests on saved real marianos.com responses (17 → 34 → 38) |

---

## 4. Live runs (store 53100544 Crystal Lake)

| Run | When | Scope | Result |
|---|---|---|---|
| 20261021T040736Z-03b8dc | 21 Oct 04:07 | 7 rows, limit 150 | 799 rows; validation failed (Dairy/Breakfast discovery, zero-result shelves, Batteries page-12 error) – exposed the bugs |
| **20261021T042105Z-fa0c1b** (entry) | 21 Oct 04:21–04:31 + continuation 04:32–04:37 | Dairy, Coffee, Breakfast, Batteries, Light Bulbs, Coupons | **1,027 rows**, 24 coupons, 192 pages store-verified, 0 mismatches; first-page reads only (Batteries 24 of 121, Light Bulbs 24 of 100) |
| 20261021T044142Z-cf40b8 | 21 Oct 04:41 | same, with query expansion | 85 requests / 950 rows, then **Oxylabs trial quota exhausted** (HTTP 429 QUOTA_EXCEEDED, shared with Walmart); process stopped; resumed 23 Oct 06:53 (13 attempts, all 429, no change) |

Mistake reported to you at the time: while stopping run cf40b8 my process filter also stopped a Walmart run belonging
to the other session (it was restarted by that session's script; checkpoint intact).

Oxylabs usage for Mariano's: ≈ 411 successful requests, ≈ 51 faulted (not charged), 263 quota rejections
(details: `docs/COST.md`).

---

## 5. Submissions and client reviews

### Entry #69 (21–23 Oct) – v1.0.0
* Board image `ENTRY-1-results-board.png`, 944-char description, private message with 1,027-row JSON, reports,
  coupons, run log, tests, source ZIP 1.0.0, checksums. Folder: `marianos-contest-submission\marianos-entry-69\`.
* Honest notes: 24-per-search limit, demo subset, coupons dependency, revalidation.

### Client review of #69 – corrections requested
1. **Retention** – keep products without price/UPC; no item id in UPC field; carried observations separate.
2. **Weight** – don't exclude all sold-by-weight items; only approximate/estimated wording.
3. **Coverage** – resolve pagination; full CSV coverage, no caps; machine-readable gap reconciliation.
4. **Offers** – complete product-linked digital terms or exact dependency; volume vs digital distinct.
5. **Provenance** – price-bearing response evidence, store/fulfillment ledger, code/config hashes, live resume,
   failed-publication proof, real unattended Azure runs.
Plus: separate versioned packages (Walmart / Mariano's), exact dependencies, logs, Oxylabs usage/cost by test,
quota explanation, concrete completion date.

### v1.1.0 (24 Oct) – `marianos-contest-submission\marianos-v1.1.0.zip`
* Retention (no-price / no-UPC kept, carry-forward), weight rule by wording (exclusions.json with trigger text),
  brand-slice partitioning + coverage.json + `probe` command, volume terms + coupon flag via `savings=Coupons`,
  per-page ledger + evidence + hashes, exact requirement pins, CHANGELOG reconciliation, Oxylabs usage/quota doc,
  Contributor-only Azure deploy (preflight, two phases, admin role commands, evidence collector),
  coverage reconciliation of the #69 run (99 searches, 19 provably complete; 22 product rows not covered),
  original #69 data, offline replay sample, 34 offline tests.
* Correction made to the client: run fa0c1b's second session was a **checkpoint continuation**, not crash recovery.

### Azure access (24 Oct)
* Client invited **debugging.specialist@gmail.com** (Freelancer support confirmed email sharing is allowed).
* Device-code sign-in: own old tenant `ccc59be7…` blocked by security defaults (AADSTS530035); client tenant
  `b6d4bd45-c947-4f69-9949-7e688a70561e` reachable but **no role yet**.

### Client reply to v1.1.0
* Azure: RG **scraper-contest-asif-test**, subscription **febcf465-0d68-44e1-bc04-303bf48bf02d**, tenant b6d4bd45…,
  West US 2; zero role assignments yet; use the Contributor-only path + 2 admin role assignments; deployment/cost plan
  not yet approved.
* Coverage: all 28 rows; **zero unexplained gaps**; keep both counts and original responses when totals are
  stale/capped/changing; never count incomplete as complete.
* Stores: keep Crystal Lake labelled; must also support **Vernon Hills, 1720 N Milwaukee Ave, IL 60061** with its
  id verified from responses; name the store before each run.
* Coupons: list + flag = interim only; document exact missing linkage and dependency; no account/charges agreed.
* Quota/schedule: they have a paid Oxylabs service – specify compatible endpoint/plan and a bounded first test before
  any key setup or purchase; propose a Central-time window; do **not** activate an unattended schedule; outputs to
  private Blob in the test RG; keep offline labels; don't present 19/99 or checkpoint reuse as coverage/recovery.

### v1.1.1 (24 Oct) – `marianos-contest-submission\marianos-v1.1.1.zip` (code_sha256 268b672e…2f42)
* Coverage: every count kept with its response; every gap split into explained reasons with evidence; validation
  fails on any unexplained gap.
* Vernon Hills candidate store **53100502** (from the public store page URL …/531/00502), disabled until verified;
  verification also checks IN_STORE fulfillment; test proves stores are never relabelled.
* Azure job **manual by default** (`SCHEDULE=on` only after approval).
* Classic Oxylabs realtime adapter; hard request caps (`probe` ≤ 15, `verify-store` ≤ 2).
* `09-COUPONS…md` (missing linkage + dependency), `10-TEST-PLAN…md` (endpoint, Test 1 ≤ 19 requests,
  Test 2 ≤ 300, Central-time window). 38 offline tests.
* Message: `marianos-v1.1.1\MESSAGE-TO-CLIENT.txt` – asks for role confirmation + plan approval, Oxylabs
  product/endpoint + Test 1 agreement, a Central-time day.

---

## 6. Where things are

| Item | Path |
|---|---|
| Scraper source | `D:\PROJECTS\Monthly-Test\marianos-scraper` |
| Run data | `marianos-scraper\state\marianos-544-crystal-lake\runs\…` |
| Entry #69 package | `marianos-contest-submission\marianos-entry-69\` |
| v1.1.0 package | `marianos-contest-submission\marianos-v1.1.0.zip` (superseded) |
| **Current package** | `marianos-contest-submission\marianos-v1.1.1.zip` + `marianos-v1.1.1\MESSAGE-TO-CLIENT.txt` |
| Client chat copy | `marianos-contest-submission\marianoChat.txt` |

---

## 7. Status and next steps

**Blocked on:** (1) Azure role on scraper-contest-asif-test + deployment/cost approval; (2) Oxylabs – trial key is
QUOTA_EXCEEDED; client to name their paid endpoint/plan and agree Test 1.

**Then, in order:**
1. Test 1 (≤ 19 requests): verify Crystal Lake + Vernon Hills, probe paging / brand filter.
2. Test 2 (≤ 300): Batteries + Light Bulbs end to end with full coverage reconciliation.
3. Deploy (preflight → infra → admin role commands + key in Key Vault → manual job).
4. Test 3: fresh full-CSV run (store named first) with a real kill + resume.
5. Failed-publication checksum proof; second execution; coverage figures.
6. Live evidence package (v1.1.x); schedule activated only after the client approves days/time.

**Open risks:** the brand filter must be honoured live for coverage proof; Mariano's 1,000 display cap; digital coupon
terms need a browser/session path; full-run request volume (estimate 15k–30k per run) to be measured in Test 2.

---

## 8. Update 25 Oct – client feedback of 24 Oct + access applied → v1.1.2

Client (24 Oct): keep 21-Oct live evidence separate from offline tests; reconcile #60/#69; their product is Oxylabs
Web Scraper API – name exact feature/auth (no credentials); executable commands + enforced totals for 19/300;
store/fulfillment evidence; coupon linkage; clarify deploy-vs-test sequence, manual only; nothing approved.
Then: RG access **applied** (Contributor on scraper-contest-asif-test); asked to confirm visibility and send a
per-task CT completion plan with blockers and package dates. Asif is in the top three for both contests
(encouragement, not an award); the RG is for verifying the production scraper, not a test-only project.

v1.1.2 (code_sha256 c6a0f502…cb38, 42 offline tests): `budget.py` persistent TOTAL request caps (`--budget`,
`MSCRAPER_BUDGET`), `bounded-test test1|test2`, `budget-status`; Azure job runs `MSCRAPER_ARGS` (default
`budget-status`, 0 requests), `deploy/azure/run_test.sh`, `fetchProvider` param; `tools/store_evidence.py`.
Oxylabs docs (25 Oct): Web API = API key as Bearer on a Web API instance; `/v1/scrape/kroger` with store_id (a
`/v1/scrape/marianos` endpoint also exists, unused); credit-based shared balance.
Package: `marianos-v1.1.2.zip` (+ `marianos-v1.1.2/MESSAGE-TO-CLIENT.txt`). Plan: v1.1.3 Thu 29 Oct 17:00 CDT,
final v1.2.0 Wed 4 Nov 17:00 CST, if D1-D5 are met. Measured live throughput ≈ 8-9 requests/min → full run 28-56 h.
