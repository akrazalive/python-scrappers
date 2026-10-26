# Changes

## 1.1.6 (2026-10-26) – Azure: infrastructure first, manual only, scoped roles

Deployment and CLI only. Collection, parsing, validation and publication logic are unchanged from 1.1.5
(`src/wmscraper/runner.py`, `parse/`, `validate.py`, `fetch/` identical); no live requests were made.

1. **Two-phase deployment into the existing resource group** (`deploy/azure/main.bicep`, `deploy.sh`):
   phase `infra` creates Log Analytics, Storage, an empty Key Vault, the managed identity and the Container Apps
   environment – no job, no schedule, no Oxylabs credential. Phase `job` adds the job after the client has stored
   the credential and applied the roles.
2. **No role assignments by the developer**: `assignRoles=false` by default (resource-group Contributor cannot
   assign roles). Phase `infra` writes `HANDOVER-azure-ids.txt` (vault name, id and URI, secret name(s), identity
   principal/object id, client id, resource id, storage container id) and `admin-role-commands.sh` with the two
   scoped assignments: Storage Blob Data Contributor on the `walmart-scraper` **container**, Key Vault Secrets User
   on the vault.
3. **No container registry, no AcrPull**: the ACR resource and its role are removed; the job runs the versioned
   source ZIP on the public Python image (as before).
4. **Manual only**: trigger Manual unless `SCHEDULE=on`; default command `status`; `replicaRetryLimit` 0 so an
   execution can never exceed its request cap through automatic restarts.
5. **No credentials through the deployment**: the `@secure()` credential parameters were removed; only the client
   writes secrets into the vault. The provider (`oxylabs_webapi` API key or `oxylabs` API user) is chosen at
   deployment (`PROVIDER=`, sets `WMSCRAPER_FETCH_PROVIDER`).
6. **CLI**: `status` (version, source hash, provider, credential present yes/no by name only, storage reachable;
   0 provider requests); `verify-store --max-requests N` (cap includes retries).
7. **`deploy/azure/run_test.sh`** (check / probe ≤ 10 / run with a cap / stop / status / collect) replaces
   `collect_evidence.sh`; refuses to start unless the job is Manual; storage read with the account key, so the
   developer needs no data-plane role. `deploy/azure/preflight.sh` added (read-only access check).
8. Tests: `tests/test_azure_manual.py` (4 offline tests; 47 in total).
