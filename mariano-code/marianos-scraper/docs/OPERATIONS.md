# Operations

## 1. Install in Azure (existing resource group, limited access supported)

Prerequisites: Azure CLI signed in to the target tenant (`az login --tenant <tenant>`), Bicep (bundled), Python 3.12+.
The scripts never create resource groups and never need subscription-level rights.

```bash
# 0. read-only check of the access (roles, providers, existing resources) – changes nothing
./deploy/azure/preflight.sh <subscription-id> <resource-group>

# 1. infrastructure: Log Analytics, Storage (Blob + Azure Files), Key Vault, managed identity, Container Apps env
./deploy/azure/deploy.sh <subscription-id> <resource-group> infra
#    with resource-group Contributor only: the script writes evidence/azure-deploy-*/admin-role-commands.sh –
#    the client's administrator runs the two scoped role assignments and stores the Oxylabs key in Key Vault
#    (the key is never sent in chat). With role-assignment rights: ASSIGN_ROLES=true; OXYLABS_WEBAPI_KEY=... optional.

# 2. scheduled job (after the key and roles exist)
./deploy/azure/deploy.sh <subscription-id> <resource-group> job          # Tue + Fri 07:00 UTC (CRON=... to change)

# 3. proof of unattended execution: schedule, executions, run logs, published files, checksums (read-only)
./deploy/azure/collect_evidence.sh <subscription-id> <resource-group>
```

| Resource | Purpose |
|---|---|
| Container Apps Job `mscraper-job` | scheduled run, 8 h timeout; an unfinished run resumes from its checkpoint next time |
| Storage – Blob container `marianos-scraper` | releases (the exact ZIP the job runs), published output, run history, run lock (blob lease) |
| Storage – Azure Files share `scraper-state` | checkpoints mounted at `/state` → interrupted runs resume |
| Key Vault | secret `oxylabs-webapi-key` |
| User-assigned managed identity | Storage Blob Data Contributor (storage account) + Key Vault Secrets User (vault) |
| Log Analytics workspace | JSON logs of every run |

Run on demand: `az containerapp job start -g <rg> -n mscraper-job`

## 2. What a scheduled run does

For every `enabled: true` store in `config/locations.yaml`:
1. takes a blob lease `<location>/.run.lock` – a second overlapping run exits immediately
2. resumes the latest unfinished run from its checkpoint, or starts a new one
3. verifies the store (id, ZIP, address, every price's source store), runs the canary
4. discovers sub-categories from each CSV department page, crawls every shelf, reads the Coupons page
5. runs the canary again, validates the whole run, writes `runs/<run_id>/…`
6. publishes to `latest/` **only if validation passed**; otherwise `latest/` keeps the last good dataset

## 3. Monitoring

Log Analytics → `ContainerAppConsoleLogs_CL | where ContainerJobName_s == "mscraper-job"`.
Every line is JSON: store, category, sub-category, page, products listed / matched / kept, retries, errors, final status.

Useful queries:
* final status: `| where Log_s has "run finished"`
* store problems: `| where Log_s has "store mismatch"`
* retries: `| where Log_s has "retry"`

`runs/<run_id>/report.json` contains the validation result, counts per category and sub-category, completeness,
exclusions, store checks, canary results, request statistics and the last 50 audit events.

## 4. Recovery

| Situation | What happens / what to do |
|---|---|
| container killed / timeout / VM restart | next execution resumes the same run from the last committed page (no duplicates, no lost pages) |
| provider or Mariano's temporarily failing | each page is retried 4× with backoff; a shelf that still fails marks the run invalid → not published; the next run retries only failed shelves |
| store context changed / mismatch | run fails validation, nothing published; check `config/locations.yaml` `store_id` and run `verify-store` |
| bad data published by mistake | copy `latest/previous-records.json` → `latest/records.json` (one-step rollback); blob versioning keeps 14 days |
| need to restart from scratch | run without `--resume` (new run id) |

## 5. Add a store

1. find the store id (division 531 + 5-digit store number), e.g. from marianos.com/stores
2. add an entry to `config/locations.yaml` with `key`, `store_id`, `zipcode`, `expected_address`, canary UPCs
3. `python -m mscraper verify-store --location <key>` – must print `"verified": true`
4. upload the new package (`deploy.sh` again) – no code changes

## 6. Add or change categories

Edit `config/categories.csv` (same columns as the contest file). Department URLs (`/d/<slug>`) are expanded into
their sub-categories automatically; product-list URLs (`/pl/<slug>/<id>`) are crawled as one sub-category;
the coupons URL is read as the Coupons category. Brand/merchandising shelves to skip are regexes in
`config/settings.yaml` → `crawl.skip_shelf_patterns`.

## 7. Maintenance

* `python -m pytest -q` before every release (runs offline on saved real responses)
* if Mariano's changes its page format, the run fails validation (it never publishes partial data) and
  `tests/test_rules.py` shows which field moved; parsing lives in one module: `src/mscraper/parse.py`
* rotate the provider key: update the Key Vault secret `oxylabs-webapi-key`; no redeploy needed
