# Mariano's – infrastructure-first sequence and Azure handover (v1.1.3)

Answers the client clarification of 26 Oct. Nothing has been deployed, run or spent. No provider requests.

## 1. Confirmation: the infrastructure step needs no Oxylabs credential

`./deploy/azure/deploy.sh <subscription> scraper-contest-asif-test infra` deploys `main.bicep` with `deployJob=false`
and `assignRoles=false`. It creates only:

| Resource | Name (prefix `mscraper`) | Notes |
|---|---|---|
| Log Analytics workspace | `mscraper-logs` | 30-day retention |
| User-assigned managed identity | `mscraper-id` | the job's identity; its principal id goes to you |
| Storage account | `mscraper<unique>` | Blob container **`marianos-scraper`** (release ZIP, output, run lock) + Azure Files share `scraper-state` (checkpoints) |
| Key Vault | `mscraper-kv-<unique>` | **empty**, RBAC mode, soft delete on |
| Container Apps environment | `mscraper-env` | no app, no job |

It creates **no job, no schedule and no secret**, and sends **0 provider requests**. The Oxylabs credential is not
read, passed or needed at this step. The only data written is the versioned source ZIP
(`releases/marianos-scraper-1.1.3-src.zip`), uploaded with the storage account key that resource-group Contributor
can read.

## 2. What you receive after the infrastructure step

The script writes two files and I send both to you:

**`HANDOVER-azure-ids.txt`**

| Item | Example form |
|---|---|
| Key Vault name | `mscraper-kv-xxxxxxxxxxxx` |
| Key Vault resource id | `/subscriptions/<sub>/resourceGroups/scraper-contest-asif-test/providers/Microsoft.KeyVault/vaults/<name>` |
| Key Vault URI | `https://<name>.vault.azure.net/` |
| Intended secret name | `oxylabs-webapi-key` (API key, Bearer). With an API user instead: `oxylabs-username` + `oxylabs-password` |
| Managed identity principal / object id | GUID (also client id and resource id) |
| Storage container resource id | `/subscriptions/<sub>/resourceGroups/scraper-contest-asif-test/providers/Microsoft.Storage/storageAccounts/<sa>/blobServices/default/containers/marianos-scraper` |
| Container registry | **none**: the job runs the public `python:3.12-slim` image, so **AcrPull is not needed** |

**`admin-role-commands.sh`** (generated with the real ids):

```bash
# 1) blob data access limited to the designated test container
az role assignment create --assignee-object-id <principal-id> --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope <container-resource-id>
# 2) secret read access limited to the test vault
az role assignment create --assignee-object-id <principal-id> --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope <key-vault-resource-id>
# your administrator stores the credential (needs Key Vault Secrets Officer on the vault; never sent in chat)
az keyvault secret set --vault-name <vault-name> --name oxylabs-webapi-key --value "<YOUR-OXYLABS-API-KEY>"
# check
az role assignment list --assignee <principal-id> --all --query "[].{role:roleDefinitionName,scope:scope}" -o table
```

Change in v1.1.3: the storage role is scoped to the **`marianos-scraper` container**, not the whole storage
account (v1.1.2). Everything the identity reads or writes over Blob is in that container. Checkpoints are on the
Azure Files share, which the Container Apps environment mounts with the account key, so the identity needs no
account-wide data role.

## 3. Sequence and who waits on whom

| # | Step | Who | Provider requests | Waits on |
|---|---|---|---|---|
| 1 | Infrastructure (`deploy.sh … infra`); send `HANDOVER-azure-ids.txt` + `admin-role-commands.sh` | me | 0 | **D1** (your approval of the deployment/cost plan) |
| 2 | 2 scoped role assignments + Oxylabs credential into the vault | your administrator | 0 | step 1; which Oxylabs credential your plan supplies |
| 3 | Job (`deploy.sh … job`): trigger **Manual**, default command `budget-status`; `run_test.sh … status` shows it runs | me | 0 | step 2 |
| 4 | Test 1 (≤ 19 requests) | me | ≤ 19 | step 3 and **D3** (Test 1 approval) |
| 5 | Test 2 (≤ 300 requests) | me | ≤ 300 | Test 1 passed and **D3** (Test 2 approval) |
| 6 | Test 3 (full CSV at Crystal Lake, forced kill/resume) | me | cap from Test 2 | **D5** (your approval of the cap) |

No schedule is created at any step. D4 (test windows) is removed: each approved test is started as soon as its
prerequisites exist, and nobody needs to watch it.

## 4. Timing (relative, since there are no windows)

| After | I deliver |
|---|---|
| your D1 approval | infrastructure deployed and the two handover files sent **within 2 hours** (the deployment itself takes about 10 minutes) |
| your administrator confirms step 2 | job deployed and checked (0 requests) within 2 hours |
| step 3 + D3 | Test 1 started within 1 hour; Test 2 started right after Test 1 passes; v1.1.4 package (Test 1 + 2 live evidence, measured requests per CSV row, proposed Test 3 cap) within 1 working day |
| D5 | Test 3 started within 2 hours; measured duration stated in v1.1.4 (21-Oct throughput suggested 28-56 h; Test 2 measures the real rate) |
| Test 3 finished | coverage review, failed-publication proof and final package v1.2.0 within 2 working days |

The previously planned "v1.1.3 = Test 1 + 2 evidence" is now **v1.1.4**; v1.1.3 is this infrastructure update.

## 5. Waiting on you / separate decisions

| Item | Status |
|---|---|
| Azure login / access | resolved and verified (your message) |
| D1 deployment/cost plan | **pending your approval.** Idle cost while no job runs: about $1-3 per month (storage, Key Vault operations, Log Analytics under its free ingestion; the Container Apps environment and job cost nothing while nothing executes). Per-run cost is in `docs/COST.md` |
| D2 credential + roles | after step 1 |
| Oxylabs compatibility / quota | separate: which authentication your plan supplies (Web API key, Bearer, for `webapi.oxylabs.io/v1/scrape/kroger`, as used on 21 Oct; or an API user name + password, `PROVIDER=oxylabs_realtime`, then Test 1 proves it) and its request allowance |
| D3 Test 1 + Test 2 budgets (≤ 19, ≤ 300) | separate |
| D4 test windows | **removed** |
| D5 Test 3 cap, larger budgets, schedule | after v1.1.4 |
| D6 coupon browser probe | separate, unchanged |

## 6. Walmart in the same resource group

The Walmart scraper deploys into the same group with its own prefix (`wmscraper-…`): its own storage container,
empty Key Vault and managed identity. It follows the same sequence with its own handover file and two role commands,
and is described in the separate Walmart package. The two scrapers share no resources and no credentials.
