# Walmart – infrastructure-first sequence and Azure handover (walmart-scraper 1.1.6)

Answers the client clarification of 26 Oct. Nothing has been deployed, run or spent. No provider requests.

## 1. Why 1.1.6 was needed before deploying

The 1.1.5 Azure template could not follow your sequence:

| 1.1.5 template | Problem | 1.1.6 |
|---|---|---|
| created the three role assignments itself | fails under resource-group Contributor | `assignRoles=false`; the scoped commands are generated for your administrator |
| created the job in the same step, with Key Vault references | needed the credential before the vault existed | two phases: `infra` (no job) and `job` (after the credential and roles exist) |
| scheduled trigger, Mon + Thu 06:00 UTC | not allowed: manual only | trigger **Manual**; a schedule only with `SCHEDULE=on` after your approval |
| Container Registry + AcrPull | unused cost and an unneeded role | removed: the job runs the versioned source ZIP on the public Python image |
| credentials could be passed as deployment parameters | credentials must stay out of the deployment | parameters removed: only your administrator writes the secret |
| blob role on the whole storage account | wider than the designated container | scoped to the `walmart-scraper` container |

Collection, parsing, validation and publication code is unchanged from 1.1.5. The only code change is two CLI
additions: `status`, which makes 0 provider requests and is the job's default command, and `--max-requests` on
`verify-store`. See `02-diff-1.1.5-to-1.1.6.patch`.

## 2. Confirmation: the infrastructure step needs no Oxylabs credential

`./deploy/azure/deploy.sh <subscription> scraper-contest-asif-test infra` creates only:

| Resource | Name (prefix `wmscraper`) | Notes |
|---|---|---|
| Log Analytics workspace | `wmscraper-logs` | 30-day retention |
| User-assigned managed identity | `wmscraper-id` | the job's identity; its principal id goes to you |
| Storage account | `wmscraper<unique>` | Blob container **`walmart-scraper`**: release ZIP, output, checkpoints, run lock |
| Key Vault | `wmscraper-kv-<unique>` | **empty**, RBAC mode, soft delete on |
| Container Apps environment | `wmscraper-env` | no app, no job |

It creates **no job, no schedule and no secret**, and sends **0 provider requests**. The only data written is the
source ZIP (`releases/walmart-scraper-1.1.6-src.zip`), uploaded with the storage account key that resource-group
Contributor can read.

## 3. What you receive after the infrastructure step

**`HANDOVER-azure-ids.txt`**:
- Key Vault name, resource ID and URI
- intended secret name: `oxylabs-webapi-key`, or `oxylabs-username` + `oxylabs-password` for an API user
- managed identity principal/object ID, client ID and resource ID
- storage container resource ID (`…/storageAccounts/<sa>/blobServices/default/containers/walmart-scraper`)
- "container registry: none, AcrPull not needed"

**`admin-role-commands.sh`**, generated with the real IDs:

```bash
az role assignment create --assignee-object-id <principal-id> --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope <container-resource-id>
az role assignment create --assignee-object-id <principal-id> --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope <key-vault-resource-id>
az keyvault secret set --vault-name <vault-name> --name oxylabs-webapi-key --value "<YOUR-OXYLABS-API-KEY>"
az role assignment list --assignee <principal-id> --all --query "[].{role:roleDefinitionName,scope:scope}" -o table
```

The earlier request for three roles is now two: AcrPull is not needed.

## 4. Sequence and who waits on whom

| # | Step | Who | Provider requests | Waits on |
|---|---|---|---|---|
| 1 | Infrastructure (`deploy.sh … infra`); send the two handover files | me | 0 | your deployment/cost approval |
| 2 | 2 scoped role assignments + Oxylabs credential into the vault | your administrator | 0 | step 1; which credential your plan supplies |
| 3 | Job (`deploy.sh … job`), trigger **Manual**, default `status`; `run_test.sh … check` shows release, credential present (yes/no only) and storage access | me | 0 | step 2 |
| 4 | Store probe `run_test.sh … probe`: store #100 + canaries | me | ≤ 10 | step 3 + your approval of 10 requests |
| 5 | E1/E2 evidence for the 175 short listings | me | ≤ 1,220 | your approval (from my 25-Oct message) |
| 6 | Smoke run, hard stop and resume on the final hash, deliberately failed run | me | cap per step | your approval of each cap |
| 7 | Full Azure repeat | me | ≈ 17,000 | your approval |
| 8 | UPC pass | me | ≈ 55,500-57,700 | your approval |

Every live step is one manual execution started by `run_test.sh` with `--max-requests <cap>`. The cap counts every
attempt, retries included, and the job has `replicaRetryLimit 0`, so Azure never restarts an execution on its own.
`run_test.sh` refuses to start if the job is not Manual. There are no test windows: each approved step starts as
soon as its prerequisites exist.

## 5. Timing (relative to your approvals)

| After | I deliver |
|---|---|
| deployment/cost approval | infrastructure deployed and the two handover files sent **within 2 hours** (deployment ≈ 10 minutes) |
| your administrator confirms step 2 | job deployed and `check` run within 2 hours |
| approval of the probe | probe started within 1 hour; result sent the same day |
| approval of E1/E2 (1,220) | Package B 4 hours after the start |
| your decision on the 175 listings | 1.1.7 (the agreed exception rule + the UPC-queue fix) within 1 working day, then the Azure steps 6-8 as approved |

The items I previously planned for "v1.1.6" (the exception rule and the UPC-queue fix) are now **1.1.7**, because
they depend on your decision on the 175 listings. 1.1.6 is this Azure update only.

## 6. Waiting on you / separate decisions

| Item | Status |
|---|---|
| Azure login / access | resolved and verified |
| Deployment/cost approval | **pending.** Idle cost while no job runs: about $1-3 per month. The Container Registry (~$5 per month) is gone |
| Roles + credential | after step 1 |
| Oxylabs credential type / quota | separate. The live run used a Web API key (Bearer) on `webapi.oxylabs.io/v1/scrape/walmart` with `store_id=100`, `delivery_zip=72712`. An API user name + password (`realtime.oxylabs.io`) is supported (`PROVIDER=oxylabs`), but store pinning on that path is unverified and the probe must prove it first |
| Test windows | removed |
| Treatment of the 175 short listings; E1/E2 (≤ 1,220) | pending, from my 25-Oct message |
| Azure repeat (≈ 17,000), UPC pass, schedule | pending, separate |

## 7. Mariano's in the same resource group

Mariano's deploys into the same group with prefix `mscraper-…`: its own container, vault and identity, and its own
two role commands. The two scrapers share no resources and no credentials. If both use an Oxylabs API key, a
separate Web API instance per scraper keeps their credit use apart.
