# Live test plan – bounded, store-identified, schedule off

All tests run against ONE store at a time, named before starting. Every request is counted in the run's ledger.
Hard caps are enforced by the code (`--max-requests`); retries count against the cap.

## Provider (what is compatible)
* Used for every run so far: **Oxylabs Web Scraper API**, Kroger target – `POST https://webapi.oxylabs.io/v1/scrape/kroger`,
  Bearer API key, body `{url, location: US, output: [html], store_id}` (store pinning per request), `run_js` only for the
  Coupons page and one probe request. `fetch.provider: oxylabs_kroger`.
* If the client's existing paid service is the classic **Web Scraper API realtime** endpoint
  (`realtime.oxylabs.io/v1/queries`, username/password): `fetch.provider: oxylabs_realtime`, payload in
  `config/settings.yaml` (default `{source: kroger, url, store_id}`); it must pass Test 1 before anything else.
* Billing: one request = one delivered page; Oxylabs states faulted requests are not charged. The cost per request
  depends on the client's plan (JS-rendered requests may be priced higher) – cost = requests × plan rate.

## Test 1 – store + paging/brand-filter probe (≤ 19 requests, ~10 minutes)
| Step | Command | Cap |
|---|---|---|
| verify Crystal Lake 53100544 / 60014 | `verify-store --location marianos-544-crystal-lake` | ≤ 2 |
| verify Vernon Hills candidate 53100502 / 60061 / 1720 N Milwaukee | `verify-store --location marianos-502-vernon-hills` | ≤ 2 |
| probe (page 1, page 2, JS page 2, brand slices of page 1) | `probe --location <store> --query Batteries --max-requests 15` | 15 |
Output: verification records + probe.json with every response's SHA-256 and evidence file. Decides whether brand
slicing can prove coverage before any larger run.

## Test 2 – two complete small CSV rows (≤ 300 requests, ~30-45 minutes)
`run --location <store> --categories "Batteries,Light Bulbs" --max-requests 300 --no-publish` – shows the brand-slice
reconciliation end to end (coverage.json with every count, every gap explained) on rows where #69 stopped at 24.

## Test 3 – fresh full-CSV run, killed once and resumed (estimate 15,000-30,000 requests, several hours)
Only after Tests 1-2 and the client's go-ahead; the request cap is set from the Test 2 measurement.
Then: failed-publication proof (scoped run forced to fail; latest/ checksums unchanged) and the second execution.

## Schedule
The Azure job is deployed MANUAL (no unattended schedule) until the client approves days/time after the measured
runtime. Twice-weekly remains configurable (`SCHEDULE=on`, `CRON=...`).

## Proposed window (US Central, CDT = UTC-5 until 2026-11-01)
Test 1: a weekday 09:00-09:30 CT (14:00-14:30 UTC, 19:00-19:30 PKT). Test 2: the same day 10:00-11:00 CT. Exact
dates are proposed only after access and quota are confirmed, so they never overlap the client's tests.
