# Operations, Recovery and Maintenance

## 1. Install in Azure

Prerequisites: Azure CLI logged in (`az login`), permission to create resources in the target subscription.

```bash
export OXYLABS_USERNAME=...   OXYLABS_PASSWORD=...        # or ZYTE_API_KEY=...
./deploy/azure/deploy.sh rg-walmart-scraper eastus 1.0.0
```

Creates Log Analytics, Container Registry, Storage (versioning + soft delete), Key Vault, a managed identity with
least-privilege roles, a Container Apps environment and the scheduled job. The image is built in ACR (no local Docker).

Run immediately: `az containerapp job start -g rg-walmart-scraper -n wmscraper-job`

## 2. Schedule

`cronExpression` in `deploy/azure/main.bicep` – default `0 6 * * 1,4` (Monday and Thursday 06:00 UTC).
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
(`deploy.sh … <new tag>`). No code changes.

## 6. Add or change categories

Edit `config/categories.csv` (same columns). Subcategory exclusions go in Notes, e.g.
`Exclude 'Farm Animals' subcategory`. Redeploy.

## 7. Change provider

`fetch.provider` in `config/settings.yaml` (`oxylabs`, `zyte`, `playwright`) and the matching secrets in Key Vault.

## 8. Tests

`python -m pytest -q` – run before every deployment.

## 9. Evidence and verification tools

| Command | Purpose |
|---|---|
| `python tools/package_source.py` | Builds `dist/walmart-scraper-<ver>-src.zip` + MANIFEST + source fingerprint (matches `report.json → scraper.source_sha256`). |
| `python tools/make_evidence.py --location <key>` | Real run with a hard kill and resume, dataset, logs, coverage CSV, yield-drop check, results board → `evidence/<ts>/`. |
| `python -m wmscraper validate --location <key> --run-id <id> [--previous report.json]` | Re-validates a finished run (used to demonstrate yield-drop detection). |
| `./deploy/azure/collect_evidence.sh <rg> <key>` | Azure proof: schedule, executions, run events from Log Analytics, published blobs and manifest. |

## 10. Thin-result detection

Each listing stores Walmart's own reported product count on page 1. After the run, a listing that yielded less than
`validation.thin_listing_ratio` (default 70 %) of what is reachable (`min(reported, 25 pages × page size)`) fails
validation. Optional absolute floors: `validation.category_minimums`. Plus zero-item and yield-vs-last-good checks.

## 11. Scoped locations

A location may limit itself to `categories` and/or `only_subcategories` in `config/locations.yaml`. A scoped
location runs, validates and publishes exactly like a full one – useful for a low-cost acceptance run.
