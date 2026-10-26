#!/usr/bin/env bash
# Deploys the Walmart scraper into an EXISTING resource group (no subscription-level rights needed).
#
#   ./deploy/azure/deploy.sh <subscription-id> <resource-group> infra     # phase 1: storage, empty Key Vault, identity, env
#   ./deploy/azure/deploy.sh <subscription-id> <resource-group> job       # phase 2: the job (MANUAL start; SCHEDULE=on only after approval)
#
# Options (environment variables):
#   ASSIGN_ROLES=true      deployer may assign roles (Owner / User Access Administrator / RBAC Administrator)
#   PROVIDER=oxylabs_webapi|oxylabs   Oxylabs API key (Bearer, default) or API user name + password
#   TAGS='{"owner":"x"}'   tags required by policy
#   SCHEDULE=off|on        off (default) = manual-start job only; on = unattended cron (only after client approval)
#   CRON='0 6 * * 1,4'     schedule (UTC) used when SCHEDULE=on
# Phase 1 needs no Oxylabs credential. Without role-assignment rights it writes HANDOVER-azure-ids.txt and
# admin-role-commands.sh for the client's administrator. Credentials are never passed to or stored by this script.
set -euo pipefail
SUB=${1:?subscription id}; RG=${2:?existing resource group}; PHASE=${3:?infra|job}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$HERE/../.."
ASSIGN_ROLES=${ASSIGN_ROLES:-false}; CRON=${CRON:-0 6 * * 1,4}
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep /subscriptions/... resource ids unchanged
SCHEDULE=${SCHEDULE:-off}; SCHED_ENABLED=false; if [ "$SCHEDULE" = "on" ]; then SCHED_ENABLED=true; fi
TAGS=${TAGS:-}; PROVIDER=${PROVIDER:-oxylabs_webapi}
if [ -z "$TAGS" ]; then TAGS='{}'; fi
az account set --subscription "$SUB"
az group show -n "$RG" -o none            # must exist; this script never creates resource groups
OUTDIR="$ROOT/evidence/azure-deploy-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUTDIR"

python "$ROOT/tools/package_source.py" | tee "$OUTDIR/package.txt"
ZIP="$ROOT/dist/walmart-scraper-$(PYTHONPATH="$ROOT/src" python -c 'import wmscraper;print(wmscraper.__version__)')-src.zip"
NAME=$(basename "$ZIP")
DEPLOY_JOB=false; [ "$PHASE" = "job" ] && DEPLOY_JOB=true

OUT=$(az deployment group create -g "$RG" -n "wmscraper-$PHASE" -f "$HERE/main.bicep" \
  -p assignRoles="$ASSIGN_ROLES" deployJob="$DEPLOY_JOB" releaseBlob="releases/$NAME" tags="$TAGS" \
     cronExpression="$CRON" scheduleEnabled="$SCHED_ENABLED" fetchProvider="$PROVIDER" \
  --query properties.outputs -o json)
echo "$OUT" > "$OUTDIR/deployment-outputs.json"
get(){ echo "$OUT" | python -c "import json,sys;print(json.load(sys.stdin)['$1']['value'])"; }
SA=$(get storageAccount); KV=$(get keyVault); PID=$(get identityPrincipalId); CID=$(get containerId); KID=$(get keyVaultId)
SECRETS=$(echo "$OUT" | python -c "import json,sys;print(' '.join(json.load(sys.stdin)['secretNames']['value']))")

# upload the exact release the job runs (account key via Contributor; no data-plane role needed)
KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
az storage blob upload --account-name "$SA" --account-key "$KEY" -c walmart-scraper -n "releases/$NAME" -f "$ZIP" --overwrite -o none
echo "uploaded releases/$NAME" | tee -a "$OUTDIR/package.txt"

if [ "$PHASE" = "infra" ]; then
  # Handover for the client: every id they need for the scoped role assignments and the Key Vault secret.
  {
    echo "# Walmart scraper - Azure test infrastructure (phase 1, no provider requests, no job, no schedule)"
    echo "resource group:            $RG"
    echo "key vault name:            $KV"
    echo "key vault resource id:     $KID"
    echo "key vault uri:             $(get keyVaultUri)"
    echo "secret name(s) to set:     $SECRETS   (provider $PROVIDER)"
    echo "managed identity:          $(get identityName)"
    echo "  principal / object id:   $PID"
    echo "  client id:               $(get identityClientId)"
    echo "  resource id:             $(get identityId)"
    echo "storage account:           $SA"
    echo "storage container:         $(get containerName)"
    echo "storage container res. id: $CID"
    echo "container registry:        none (public python:3.12-slim image; AcrPull not needed)"
  } > "$OUTDIR/HANDOVER-azure-ids.txt"
  if [ "$ASSIGN_ROLES" != "true" ]; then
    cat > "$OUTDIR/admin-role-commands.sh" <<EOF
# Run by an administrator with role-assignment rights on resource group $RG (two scoped assignments):
# 1) blob data access limited to the designated test container, 2) secret read access limited to the test vault.
az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope $CID
az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $KID
EOF
    if [ "$PROVIDER" = "oxylabs_webapi" ]; then
      cat >> "$OUTDIR/admin-role-commands.sh" <<EOF
# Store the Oxylabs Web Scraper API key yourself (never in chat; you need "Key Vault Secrets Officer" on $KV).
# The developer's resource-group Contributor role cannot read Key Vault secrets.
az keyvault secret set --vault-name $KV --name oxylabs-webapi-key --value "<YOUR-OXYLABS-API-KEY>"
EOF
    else
      cat >> "$OUTDIR/admin-role-commands.sh" <<EOF
# Store the Oxylabs API user yourself (never in chat; you need "Key Vault Secrets Officer" on $KV).
# The developer's resource-group Contributor role cannot read Key Vault secrets.
az keyvault secret set --vault-name $KV --name oxylabs-username --value "<API-USER-NAME>"
az keyvault secret set --vault-name $KV --name oxylabs-password --value "<API-USER-PASSWORD>"
EOF
    fi
    cat >> "$OUTDIR/admin-role-commands.sh" <<EOF
# Check (lists the two assignments):
az role assignment list --assignee $PID --all --query "[].{role:roleDefinitionName,scope:scope}" -o table
EOF
    cat "$OUTDIR/HANDOVER-azure-ids.txt"
    echo "Phase 1 done. Send HANDOVER-azure-ids.txt + admin-role-commands.sh ($OUTDIR) to the client, then run phase 'job'."
  else
    echo "Phase 1 done (roles assigned). The client stores the credential: az keyvault secret set --vault-name $KV --name $SECRETS ..."
  fi
else
  JOB=$(get jobName)
  az containerapp job show -g "$RG" -n "$JOB" --query "{name:name,trigger:properties.configuration.triggerType,cron:properties.configuration.scheduleTriggerConfig.cronExpression}" -o json | tee "$OUTDIR/job.json"
  if [ "$SCHED_ENABLED" = "true" ]; then echo "Phase 2 done. Job $JOB runs unattended on '$CRON' (UTC)."
  else echo "Phase 2 done. Job $JOB is MANUAL (no schedule). Check: ./deploy/azure/run_test.sh $SUB $RG status"; fi
fi
