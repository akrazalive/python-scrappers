# Operations, Recovery and Maintenance

## 1. Install in Azure (existing resource group, resource-group Contributor is enough)

Prerequisites: Azure CLI signed in (`az login --tenant <tenant>`), Bicep (bundled), Python 3.12+. The scripts never
create resource groups, never need subscription-level rights and never receive a provider credential.

```bash
# 0. read-only check of the access (roles, providers, existing resources) – changes nothing
./deploy/azure/preflight.sh <subscription-id> <resource-group>

# 1. infrastructure: Log Analytics, Storage (container walmart-scraper), EMPTY Key Vault, managed identity,
#    Container Apps environment. No job, no schedule, no Oxylabs credential needed, 0 provider requests.
./deploy/azure/deploy.sh <subscription-id> <resource-group> infra
#    writes evidence/azure-deploy-*/HANDOVER-azure-ids.txt (vault name/id, secret name, identity principal id,
#    container id) and admin-role-commands.sh. The client's administrator runs the two scoped role assignments and
#    stores the Oxylabs credential in the vault (never sent in chat). PROVIDER=oxylabs for API user + password.

# 2. job (after the secret and roles exist): trigger Manual, default command `status` (0 provider requests)
./deploy/azure/deploy.sh <subscription-id> <resource-group> job

# 3. approved tests, each one manual execution with its own request cap (see deploy/azure/run_test.sh)
./deploy/azure/run_test.sh <subscription-id> <resource-group> check          # 0 requests
./deploy/azure/run_test.sh <subscription-id> <resource-group> probe          # <= 10 requests
./deploy/azure/run_test.sh <subscription-id> <resource-group> run <cap>      # client-approved cap
./deploy/azure/run_test.sh <subscription-id> <resource-group> collect        # evidence + checksums
```

| Resource | Purpose |
|---|---|
| Container Apps Job `wmscraper-job` | Manual trigger, 24 h per execution, no automatic retry (a cap cannot be exceeded) |
| Storage – Blob container `walmart-scraper` | release ZIP the job runs, output, checkpoints, run history, run lock (blob lease) |
| Key Vault | `oxylabs-webapi-key` (or `oxylabs-username` + `oxylabs-password`), set by the client |
| User-assigned managed identity | Storage Blob Data Contributor (container `walmart-scraper` only) + Key Vault Secrets User (vault) |
| Log Analytics workspace | JSON logs of every execution |

No container registry is used: the job runs the versioned source ZIP on the public `python:3.12-slim` image, so no
AcrPull role is needed. The `Dockerfile` is for local runs only.

## 2. Schedule

None until the client approves days and time. Then `SCHEDULE=on ./deploy/azure/deploy.sh <sub> <rg> job` switches the
trigger to `cronExpression` (default `0 6 * * 1,4`, Monday and Thursday 06:00 UTC, `run-all`).
`parallelism: 1` plus a Blob lease per location guarantee runs never overlap.

## 3. Monitoring

Log Analytics → `ContainerAppConsoleLogs_CL`, JSON events: `run_start`, `store_verified`, `category_discovered`,
`page`, `retry`, `listing_failed`, `store_context_mismatch`, `canary`, `published` / `not_published`, `run_end`.

```kusto
ContainerAppConsoleLogs_CL
| extend e = parse_json(Log_s)
| where e.event in ("run_end", "not_published", "listing_failed", "store_context_mismatch")
| project TimeGenerated, e.event, e.run_id, e.records, e.ok, e.errors
```

Each run also writes `runs/<run_id>/report.json` (counts, completeness, exclusions, examples, validation).

## 4. Recovery

| Situation | What happens / what to do |
|---|---|
| Container stopped mid-run | Nothing to do. Next execution resumes the open run from its checkpoint. |
| Abandon an open run instead | `python -m wmscraper run --location X --fresh` closes it (kept in `runs/` for audit) and starts a new run. |
| Run failed validation | `latest/` untouched. Read `runs/<id>/report.json → validation.errors`. |
| Some listings failed (temporary block) | `python -m wmscraper retry-failed --location X --run-id ID` then start the job – only failed listings are re-fetched. |
| Need to roll back published data | Copy `latest/previous-records.json` → `latest/records.json`, or restore a blob version. |
| Stale lock after crash | Blob lease expires automatically within 60 s; local lock is cleared after 6 h or delete `.run.lock`. |
| Walmart page layout changed | Runs fail with `ShapeError` (no bad data published). Update `src/wmscraper/parse/walmart.py`, add a fixture test, redeploy. |

## 5. Add a location

Add a block to `config/locations.yaml` (key, store_id, zipcode, fulfillment, canary_items), then redeploy
(`deploy.sh <sub> <rg> job`). No code changes.

## 6. Add or change categories

Edit `config/categories.csv` (same columns). Subcategory exclusions go in Notes, e.g.
`Exclude 'Farm Animals' subcategory`. Redeploy.

## 7. Change provider

In Azure: `PROVIDER=oxylabs_webapi|oxylabs` at deployment (sets `WMSCRAPER_FETCH_PROVIDER`) and the matching secrets in
Key Vault. Locally: `fetch.provider` in `config/settings.yaml` (`oxylabs_webapi`, `oxylabs`, `zyte`, `playwright`).

## 8. Tests

`python -m pytest -q` – run before every deployment.

## 9. Evidence and verification tools

| Command | Purpose |
|---|---|
| `python tools/package_source.py` | Builds `dist/walmart-scraper-<ver>-src.zip` + MANIFEST + source fingerprint (matches `report.json → scraper.source_sha256`). |
| `python tools/make_evidence.py --location <key>` | Real run with a hard kill and resume, dataset, logs, coverage CSV, yield-drop check, results board → `evidence/<ts>/`. |
| `python -m wmscraper validate --location <key> --run-id <id> [--previous report.json]` | Re-validates a finished run (used to demonstrate yield-drop detection). |
| `./deploy/azure/run_test.sh <sub> <rg> collect [exec]` | Azure proof: job trigger, execution, console log from Log Analytics, published blobs, manifest, checksums. |

## 10. Thin-result detection

Each listing stores Walmart's own reported product count on page 1. After the run, a listing that yielded less than
`validation.thin_listing_ratio` (default 70 %) of what is reachable (`min(reported, 25 pages × page size)`) fails
validation. Optional absolute floors: `validation.category_minimums`. Plus zero-item and yield-vs-last-good checks.

## 11. Scoped locations

A location may limit itself to `categories` and/or `only_subcategories` in `config/locations.yaml`. A scoped
location runs, validates and publishes exactly like a full one – useful for a low-cost acceptance run.
