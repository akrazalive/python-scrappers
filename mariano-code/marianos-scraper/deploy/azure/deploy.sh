#!/usr/bin/env bash
# Deploys the Mariano's scraper into an EXISTING resource group (no subscription-level rights needed).
#
#   ./deploy/azure/deploy.sh <subscription-id> <resource-group> infra     # phase 1: storage, Key Vault, identity, env
#   ./deploy/azure/deploy.sh <subscription-id> <resource-group> job       # phase 2: the job (MANUAL start by default; SCHEDULE=on only after approval)
#
# Options (environment variables):
#   ASSIGN_ROLES=true      deployer may assign roles (Owner / User Access Administrator / RBAC Administrator)
#   PROVIDER=oxylabs_kroger|oxylabs_realtime   Oxylabs Web Scraper API key (default) or API user name + password
#   OXYLABS_WEBAPI_KEY=..  store the key in Key Vault during phase 1 (normally the client's administrator stores it)
#   TAGS='{"owner":"x"}'   tags required by policy
#   SCHEDULE=off|on        off (default) = manual-start job only; on = unattended cron (only after client approval)
#   CRON='0 7 * * 2,5'     schedule (UTC) used when SCHEDULE=on
# Without role-assignment rights, phase 1 writes admin-role-commands.sh for the client's administrator.
set -euo pipefail
SUB=${1:?subscription id}; RG=${2:?existing resource group}; PHASE=${3:?infra|job}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$HERE/../.."
ASSIGN_ROLES=${ASSIGN_ROLES:-false}; CRON=${CRON:-0 7 * * 2,5}
SCHEDULE=${SCHEDULE:-off}; SCHED_ENABLED=false; if [ "$SCHEDULE" = "on" ]; then SCHED_ENABLED=true; fi
TAGS=${TAGS:-}; PROVIDER=${PROVIDER:-oxylabs_kroger}
if [ -z "$TAGS" ]; then TAGS='{}'; fi
az account set --subscription "$SUB"
az group show -n "$RG" -o none            # must exist; this script never creates resource groups
OUTDIR="$ROOT/evidence/azure-deploy-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUTDIR"

python "$ROOT/tools/package_source.py" | tee "$OUTDIR/package.txt"
ZIP=$(ls "$ROOT"/dist/marianos-scraper-*-src.zip | tail -1); NAME=$(basename "$ZIP")
DEPLOY_JOB=false; [ "$PHASE" = "job" ] && DEPLOY_JOB=true

OUT=$(az deployment group create -g "$RG" -n "mscraper-$PHASE" -f "$HERE/main.bicep" \
  -p assignRoles="$ASSIGN_ROLES" deployJob="$DEPLOY_JOB" releaseBlob="releases/$NAME" tags="$TAGS" \
     cronExpression="$CRON" scheduleEnabled="$SCHED_ENABLED" oxylabsWebApiKey="${OXYLABS_WEBAPI_KEY:-}" \
     fetchProvider="$PROVIDER" \
  --query properties.outputs -o json)
echo "$OUT" > "$OUTDIR/deployment-outputs.json"
get(){ echo "$OUT" | python -c "import json,sys;print(json.load(sys.stdin)['$1']['value'])"; }
SA=$(get storageAccount); KV=$(get keyVault); PID=$(get identityPrincipalId); SID=$(get storageId); KID=$(get keyVaultId)

# upload the exact release the job runs (account key via Contributor; no data-plane role needed)
KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
az storage blob upload --account-name "$SA" --account-key "$KEY" -c marianos-scraper -n "releases/$NAME" -f "$ZIP" --overwrite -o none
echo "uploaded releases/$NAME" | tee -a "$OUTDIR/package.txt"

if [ "$PHASE" = "infra" ]; then
  if [ "$ASSIGN_ROLES" != "true" ]; then
    cat > "$OUTDIR/admin-role-commands.sh" <<EOF
# Run by an administrator with role-assignment rights on resource group $RG (two scoped assignments):
az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope $SID
az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $KID
EOF
    if [ "$PROVIDER" = "oxylabs_kroger" ]; then
      cat >> "$OUTDIR/admin-role-commands.sh" <<EOF
# Store the Oxylabs Web Scraper API key yourself (never in chat; you need "Key Vault Secrets Officer" on $KV).
# The developer's resource-group Contributor role cannot read Key Vault secrets.
az keyvault secret set --vault-name $KV --name oxylabs-webapi-key --value "<YOUR-OXYLABS-API-KEY>"
EOF
    else
      cat >> "$OUTDIR/admin-role-commands.sh" <<EOF
# Store the Oxylabs Web Scraper API user yourself (never in chat; you need "Key Vault Secrets Officer" on $KV).
# The developer's resource-group Contributor role cannot read Key Vault secrets.
az keyvault secret set --vault-name $KV --name oxylabs-username --value "<API-USER-NAME>"
az keyvault secret set --vault-name $KV --name oxylabs-password --value "<API-USER-PASSWORD>"
EOF
    fi
    echo "Phase 1 done. Send $OUTDIR/admin-role-commands.sh to the administrator, then run phase 'job'."
  else
    echo "Phase 1 done (roles assigned). Store the key if not given: az keyvault secret set --vault-name $KV --name oxylabs-webapi-key --value <key>"
  fi
else
  JOB=$(get jobName)
  az containerapp job show -g "$RG" -n "$JOB" --query "{name:name,trigger:properties.configuration.triggerType,cron:properties.configuration.scheduleTriggerConfig.cronExpression}" -o json | tee "$OUTDIR/job.json"
  if [ "$SCHED_ENABLED" = "true" ]; then echo "Phase 2 done. Job $JOB runs unattended on '$CRON' (UTC)."
  else echo "Phase 2 done. Job $JOB is MANUAL (no schedule). Bounded tests: ./deploy/azure/run_test.sh $SUB $RG test1"; fi
fi
