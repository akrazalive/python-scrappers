# Changelog and version / run reconciliation – Mariano's scraper

All times UTC. `code_sha256` = SHA-256 over every `src/mscraper/*.py` file (path + bytes, sorted), as computed by
`mscraper.version.code_sha256()` and printed by `tools/package_source.py`.

## Runs and the code that produced them

| Run | Code at collection | Scope | Result |
|---|---|---|---|
| 20261021T040736Z-03b8dc | 1.0.0-dev, `ec8cdaac5b47…` (report.json) | 7 CSV rows, limit 150/category | 799 rows; validation failed (discovery of Dairy/Breakfast, zero-result shelves, Batteries page-12 error). Not delivered as the entry run. |
| 20261021T042105Z-fa0c1b (**entry #69**) | session 1 04:21–04:31 (finished, validation failed: 2 discovery errors) and checkpoint continuation 04:32–04:37 with `--run` (completed requests reused, only new work fetched – a continuation, NOT a crash recovery) on 1.0.0-dev `0c5be3f444b3…` (03-run-report-as-collected.json) | Dairy, Coffee, Breakfast, Batteries, Light Bulbs, Coupons | 1,027 rows; first-page reads (pagination variant). Re-validated offline on the delivered 1.0.0 code `1ce1f359…0240` (02-run-report.json); records.json byte-identical (sha256 `0e1b7260…1051`). |
| 20261021T044142Z-cf40b8 | 1.0.0 query-expansion code (between `0c5b…` and `1ce1…`; code hash not recorded by that version) | same 6 rows | 85 requests done, 950 rows in wave 1; 2026-10-21 04:50 trial quota exhausted (249 × HTTP 429 QUOTA_EXCEEDED); process force-stopped mid-wave (kill). Resumed 2026-10-23 06:53 (all categories): 13 attempts, all 429; no data change. No report/records (never finished). |

Why the code changed between collection and delivery of entry #69:
* `0c5b… → 1ce1…`: validation rule (three Coffee menu links with no products of their own taxonomy = warning, not error),
  brand + noun expansion-term fix, query expansion (`crawl.paginate: false`). Records of run fa0c1b were not re-collected.
* v1.0.0 did not record its code hash at run start (only at finish) – fixed in 1.1.0 (`report.json → provenance.start`).

## 1.1.0 (2026-10-24) – corrections from the client review of entry #69

1. **Retention** – `parse.map_product`: no rejection for a missing price or UPC any more.
   * no store price → row kept, price fields `""`, `observations.json availability: no_store_price`
   * no UPC → row kept, `upc: ""`, identity `product:<data.id>`, `source_product_id`, `identity_source: data.id`
   * the UPC comes only from `item.upc`. The old `item.upc or prod.id` fallback is removed: in 240 sampled real
     responses `item.upc` = product key = `data.id` and a top-level `prod.id` does not exist (test:
     `test_upc_only_from_item_upc_and_equals_product_key_in_real_data`)
   * products of the last published dataset that a run does not return are carried (`retention.py`) with their own
     last `crawl_date`; `observations.json` keeps `status fresh|carried`, `first_observed`, `last_observed`,
     `last_observed_run`, `carried_since`. Carried indefinitely.
2. **Weight rule** – `exclude_sold_by_weight` removed. Excluded only when Mariano's own size or price wording is
   approximate/estimated (`parse.approximate_weight_trigger`, e.g. `"about $10.39 each"`); every exclusion is written
   to `exclusions.json` with the field and exact text. Sold-by-weight products with exact wording, titles such as
   "(About 3 Steaks per Pack)", and family-pack / multipack labels are kept; sizes are preserved as displayed.
3. **Coverage** – brand-slice partitioning with Mariano's own `brandName` filter for every seed request that
   reports more than it returned; `coverage.json` reconciles reported totals vs distinct products read per request
   (`gap`, `complete`, `reported_total_is_capped` for Mariano's 1,000 display cap). Slices whose filter Mariano's
   ignores are failed, never counted. Per-shelf query cap and slice cap default to 0 (no cap). New
   `mscraper probe` command measures paging / JS paging / brand filtering live with evidence.
4. **Offers** – volume descriptions keep the retailer wording and add the source terms from the same object
   (validity dates, modalities, limits), e.g. `Save $1 each when you buy 5 or more (valid 2026-10-07T00:00:00Z to
   2026-10-27T23:59:59Z; applies to: in-store)`; every offer is kept structured in `observations.json → offers`. Digital
   and volume never merge; titles / pack labels are never promotions.
5. **Provenance** – per-page `ledger.json` (response SHA-256, store / request location, modality, priced count,
   price `sourceLocationId`s), `evidence/pages/<sha>.json.gz` price-bearing excerpts for every page,
   `evidence/raw/` full HTML samples, `observations.response_sha256` per row; code / config / requirements hashes at
   start, every resume and finish (`report.json → provenance`).
* exact dependency pins: `requirements.txt` (direct) and `requirements.lock` (full set).

### 1.1.0 package additions (2026-10-24, same code_sha256 – no change under src/)
* Azure for limited test access: `deploy/azure/main.bicep` + `deploy.sh` deploy into an EXISTING resource group in two
  phases (`infra`, then `job`); role assignments optional (`ASSIGN_ROLES`), otherwise `admin-role-commands.sh` is written
  for the client's administrator; the Oxylabs key can be stored by the client in Key Vault (never sent in chat);
  `tags` and `CRON` parameters; the job installs `requirements.lock`.
* `deploy/azure/preflight.sh` – read-only access check (roles, providers, existing resources) before deploying.
* `deploy/azure/collect_evidence.sh` – read-only proof of unattended execution (schedule, executions, run logs,
  published latest/ files, every run report, checksums).
* `tools/reconcile_v100_runs.py` – machine-readable coverage / remaining-gap reconciliation of the delivered entry #69
  run and the stopped query-expansion run, from their own checkpoints.

## 1.1.2 (2026-10-25) – client feedback of 24 Oct (bounded tests, Azure sequence, Oxylabs feature)
* **Enforced TOTAL request caps** (`src/mscraper/budget.py`): `--budget NAME:TOTAL` / env `MSCRAPER_BUDGET` puts any
  command under a total that is stored in the state directory (Azure: the Azure Files share) and counted BEFORE each
  provider request is sent. It holds across commands, retries, `--resume`, container restarts and repeated job
  executions; a total can never be raised under the same name. Every counted request is logged
  (`state/_budgets/<name>.jsonl`: time, command, store, URL).
* `python -m mscraper bounded-test test1` (verify Crystal Lake ≤ 2 + verify Vernon Hills candidate ≤ 2 + probe ≤ 15,
  **total ≤ 19**) and `bounded-test test2` (Batteries + Light Bulbs, Crystal Lake, `--no-publish`, **total ≤ 300**);
  `budget-status` shows used / remaining.
* Azure: the job runs `MSCRAPER_ARGS` per manual execution; the deployed default is `budget-status` (0 provider
  requests, so an accidental start costs nothing). `deploy/azure/run_test.sh <sub> <rg> test1|test2|status` runs one
  bounded test as one manual execution, refuses a non-Manual job, resets the job to `budget-status` afterwards and
  downloads console log, budget ledger and evidence. `fetchProvider` parameter: `oxylabs_kroger` (Web API key,
  default) or `oxylabs_realtime` (API user name + password); the client's administrator stores the secret(s) in Key
  Vault – RG Contributor cannot read them.
* `tools/store_evidence.py`: store / fulfillment evidence from saved raw responses (selected store, modality, request
  pin, per-product price source and IN_STORE availability, verbatim price excerpts, file SHA-256).
* **Crawl throughput**: the wave loop is replaced by a continuous work queue (`Runner.crawl_pending`). Up to 1.1.1 a
  wave waited for its slowest request (retries and back-off included) before the next wave started, leaving most of
  the 4 parallel slots idle – the main cause of ~8-9 requests/minute on 21 Oct. Now every queued request starts as
  soon as a slot is free; each request is started at most once per session. `crawl.max_expansion_waves` removed.
  Parallel requests: `fetch.concurrency` or env `MSCRAPER_CONCURRENCY` (Bicep `concurrency`), to be set from Test 2.
* Azure: one execution may run up to `replicaTimeoutSeconds` (default 24 h, was a fixed 8 h) with
  `replicaRetryLimit` 2 (a stopped replica resumes from the checkpoint), so a full run completes in the cloud with no
  developer machine involved. `run_test.sh` starts and returns at once; actions `test1`, `test2`, `full <cap>` (Test 3;
  the same command resumes), `stop` (forced interruption for the kill/resume test), `status`, `collect [exec]`.
  Scripts set `MSYS_NO_PATHCONV=1` and `preflight.sh` resolves `az.cmd`, so they also run from Git Bash on Windows.
* Tests: 44 offline (38 + 6: total budget, bounded tests, crawl queue).

## 1.1.1 (2026-10-24) – client reply to v1.1.0
* Coverage: zero UNEXPLAINED gaps. Every seed request's gap is split into explained items (request/slice not completed,
  capped total, slice exceeds a page, brands not discovered, site count inconsistent), each with the response SHA-256
  it rests on; every count Mariano's reported is kept (`observed_totals`), so stale / capped / changing counts are
  reconciled explicitly; a request is complete only when proven; validation FAILS on any unexplained gap.
* Stores: Vernon Hills (1720 N Milwaukee Ave, IL 60061) added as candidate `53100502` from the public store page URL,
  DISABLED and unverified until `verify-store` confirms id + ZIP + address + store-sourced prices from responses.
  Store verification now also checks and records the fulfillment modality (IN_STORE) and the response SHA-256.
  Test: one store's settings against another store's responses fail verification – results are never relabelled.
* Azure: the job deploys MANUAL by default (no unattended schedule) until the client approves days/time
  (`SCHEDULE=on`, `CRON`); outputs go to the private Blob container in the test resource group.
* Provider: optional adapter for the classic Oxylabs realtime endpoint (`fetch.provider: oxylabs_realtime`,
  configurable payload) for clients whose existing paid Oxylabs service is that product; `probe --max-requests`
  hard cap (default 15), stops cleanly at the cap.
* Docs: docs/COUPONS.md (exact missing coupon linkage + proposed dependency), docs/TEST-PLAN.md (bounded tests,
  compatible endpoint, Central-time window).
