#!/usr/bin/env bash
# One-command deployment into an existing Azure subscription (works on free-trial subscriptions:
# no ACR Tasks / Docker build needed – the job runs the versioned source package from Blob Storage).
#   ./deploy/azure/deploy.sh <resource-group> <region>
# Provider secret is read from the environment and stored in Key Vault:
#   export OXYLABS_WEBAPI_KEY=...   (or OXYLABS_USERNAME / OXYLABS_PASSWORD, or ZYTE_API_KEY)
set -euo pipefail
RG=${1:?resource group}; REGION=${2:?region e.g. eastus}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$HERE/../.."
AZ=${AZ:-az}; az(){ "$AZ" "$@"; }

echo "1/4 source package (versioned ZIP + fingerprint)"
python "$ROOT/tools/package_source.py"
ZIP=$(ls "$ROOT"/dist/walmart-scraper-*-src.zip | tail -1); NAME=$(basename "$ZIP")

echo "2/4 infrastructure"
az group create -n "$RG" -l "$REGION" -o none
OUT=$(az deployment group create -g "$RG" -n infra -f "$HERE/main.bicep" \
  -p oxylabsWebApiKey="${OXYLABS_WEBAPI_KEY:-}" oxylabsUsername="${OXYLABS_USERNAME:-}" \
     oxylabsPassword="${OXYLABS_PASSWORD:-}" zyteApiKey="${ZYTE_API_KEY:-}" releaseBlob="releases/$NAME" \
  --query properties.outputs -o json)
SA=$(echo "$OUT" | python -c "import json,sys;print(json.load(sys.stdin)['storageAccount']['value'])")
JOB=$(echo "$OUT" | python -c "import json,sys;print(json.load(sys.stdin)['jobName']['value'])")

echo "3/4 upload release package (the job runs exactly this file)"
ME=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)
az role assignment create --assignee-object-id "$ME" --assignee-principal-type User --role "Storage Blob Data Contributor" --scope "$SCOPE" -o none 2>/dev/null || true
az storage blob upload --account-name "$SA" -c walmart-scraper --auth-mode login -n "releases/$NAME" -f "$ZIP" --overwrite -o none

echo "4/4 done. Job $JOB runs Mon+Thu 06:00 UTC."
echo "Start a run now:   az containerapp job start -g $RG -n $JOB"
echo "Execution history: az containerapp job execution list -g $RG -n $JOB -o table"
