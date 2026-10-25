# Live test plan – bounded, store-identified, manual only (v1.1.2)

Nothing here has run yet. Each test runs only after the client confirms its prerequisites and window.

## 1. Oxylabs: the exact feature and authentication needed

| Item | Needed |
|---|---|
| Product | **Oxylabs Web API** (the "Web Scraper API"), dedicated commerce scraper **Kroger**: `POST https://webapi.oxylabs.io/v1/scrape/kroger` |
| Authentication | **API key as Bearer token** (`Authorization: Bearer <key>`), generated on a **Web API instance** in the Oxylabs dashboard. Basic auth is not accepted on `/v1/scrape`. |
| Request parameters used | `url` (a marianos.com search / department / coupons URL), `store_id` (e.g. `53100544`), `location: "US"`, `output: ["html"]`; `run_js: true` only for the Coupons page and one probe request |
| Delivery mode | sync (realtime) |
| Billing | credits from the account's shared balance at the plan's Web API rate (shown in the dashboard). Faulted requests are not charged. |
| Recommended | a **separate Web API instance** for this test (Oxylabs' own advice: key isolation and separate credit tracking) |
| Secret handling | the client's administrator stores the key in the test Key Vault as `oxylabs-webapi-key`. The developer's resource-group Contributor role cannot read Key Vault secrets; the key is never sent in chat. |

This is exactly what every live run on 21 Oct used (`fetch.provider: oxylabs_kroger`). If the client's dashboard
instead shows an older Web Scraper API **API user** (user name + password, `realtime.oxylabs.io/v1/queries`),
deploy with `PROVIDER=oxylabs_realtime` (secrets `oxylabs-username`, `oxylabs-password`); that adapter has not been
run live and must pass Test 1 first. Oxylabs also lists a dedicated `/v1/scrape/marianos` endpoint with the same
parameters; it is not needed (the Kroger endpoint with `store_id` is proven) and is not used.

## 2. Deployment versus test sequence (manual only throughout)

| # | Step | Who | Provider requests | Needs |
|---|---|---|---|---|
| 0 | `deploy/azure/preflight.sh <sub> scraper-contest-asif-test` – read-only: roles, providers, policy, existing resources | developer | 0 | RG access (done) |
| 1 | `deploy.sh <sub> scraper-contest-asif-test infra` – Log Analytics, Storage, Key Vault, identity, Container Apps environment | developer | 0 | client approves deployment/cost plan; providers registered |
| 2 | `admin-role-commands.sh` – 2 scoped role assignments + Oxylabs secret into Key Vault | client admin | 0 | step 1 |
| 3 | `deploy.sh … job` – job, trigger **Manual**, default command `budget-status`; `run_test.sh … status` proves it runs | developer | 0 | step 2 |
| 4 | **Test 1** `run_test.sh <sub> <rg> test1` | developer | **≤ 19** | agreed CT window, Test 1 approved |
| 5 | **Test 2** `run_test.sh <sub> <rg> test2` | developer | **≤ 300** | Test 1 result reviewed, window |
| 6 | Test 3 `run_test.sh <sub> <rg> full <cap>` – fresh full-CSV run; `run_test.sh … stop` once mid-run (forced kill), then the same `full <cap>` resumes from the checkpoint | developer | cap set from Test 2 measurement, approved by client | client approval of the cap |
| 7 | failed-publication proof; second execution | developer | ≈ 50; second run approved separately | client approval |

The tests run inside Azure so the key stays in Key Vault, and every run continues in the cloud with no developer
machine involved: `run_test.sh` starts an execution and returns; one execution may run up to 24 h
(`replicaTimeoutSeconds`), and a stopped replica is retried from its checkpoint (`replicaRetryLimit` 2).
`run_test.sh … status` and `… collect` fetch progress and evidence at any time. No schedule exists at any step;
`SCHEDULE=on` is used only after the client approves days/time.

## 3. Executable commands and enforced limits

Locally (any machine with the key in the environment) and in Azure the same CLI runs:

```
python -m mscraper bounded-test test1
python -m mscraper bounded-test test2
python -m mscraper budget-status
```

| Test | Steps (each with its own cap) | Enforced TOTAL | Duration |
|---|---|---|---|
| test1 | `verify-store --location marianos-544-crystal-lake --max-requests 2` · `verify-store --location marianos-502-vernon-hills --max-requests 2` · `probe --location marianos-544-crystal-lake --query Batteries --max-requests 15` | **19** | ~10-15 min |
| test2 | `run --location marianos-544-crystal-lake --categories "Batteries,Light Bulbs" --max-requests 300 --no-publish --resume` | **300** | ~30-45 min |

How the total is enforced (`src/mscraper/budget.py`): a budget file `state/_budgets/<test>.json` on the job's Azure
Files share; each provider request is counted **before** it is sent, retries included; when the total is reached
every further request is refused. It persists across steps, resumes, container restarts and repeated executions,
and a total cannot be raised under the same name. Every counted request is logged with time, command, store and URL
in `state/_budgets/<test>.jsonl`. Offline tests: `tests/test_v112_bounded_tests.py` (worst case – every request
fails and retries – stays ≤ 19 even when the test is started twice).

In Azure, `deploy/azure/run_test.sh <sub> <rg> test1|test2|full <cap>` refuses to start unless the job trigger is
Manual, sets the execution's command and starts ONE execution, then returns. `stop` interrupts the running
execution (kill/resume test); `status` lists executions and budget usage; `collect [exec]` writes
`evidence/azure-<exec>-<ts>/` (execution record, console log, budget ledger, verification / probe / run evidence,
SHA256SUMS) and sets the job back to `budget-status`.

## 4. Stores

* Test 1: Crystal Lake **53100544** / 60014 (verified 21 Oct) and the Vernon Hills candidate **53100502** / 60061 /
  1720 N Milwaukee Ave. Vernon Hills stays disabled unless verify-store confirms location id, ZIP, address,
  **IN_STORE** modality and store-sourced prices from Mariano's own responses.
* Test 2: Crystal Lake 53100544.
* Test 3: named to the client before starting.

## 5. Cost of Tests 1-2

Requests ≤ 319 in total (≤ 19 + ≤ 300). Of these at most 2 use JS rendering (probe). Cost = requests × the plan's
Web API rate per request (dashboard); faulted requests are not charged.
