#!/usr/bin/env bash
# Collects proof of UNATTENDED Azure execution: job schedule, every execution, run logs, published files.
#   ./deploy/azure/collect_evidence.sh <subscription-id> <resource-group> [location-key]
# Output: evidence/azure-<ts>/ – read-only, changes nothing.
set -euo pipefail
SUB=${1:?subscription id}; RG=${2:?resource group}; LOC=${3:-marianos-544-crystal-lake}
az account set --subscription "$SUB"
OUT="evidence/azure-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT/latest" "$OUT/runs"
JOB=$(az containerapp job list -g "$RG" --query "[?contains(name,'mscraper')].name | [0]" -o tsv)
SA=$(az storage account list -g "$RG" --query "[?starts_with(name,'mscraper')].name | [0]" -o tsv)
WS=$(az monitor log-analytics workspace list -g "$RG" --query "[?contains(name,'mscraper')].customerId | [0]" -o tsv)
KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)

az containerapp job show -g "$RG" -n "$JOB" --query "{name:name, trigger:properties.configuration.triggerType, \
  cron:properties.configuration.scheduleTriggerConfig.cronExpression, timeout:properties.configuration.replicaTimeout, \
  image:properties.template.containers[0].image}" -o json > "$OUT/01-job-schedule.json"
az containerapp job execution list -g "$RG" -n "$JOB" \
  --query "[].{name:name, status:properties.status, start:properties.startTime, end:properties.endTime}" -o json > "$OUT/02-executions.json"

az monitor log-analytics query -w "$WS" --analytics-query "
ContainerAppConsoleLogs_CL
| where ContainerJobName_s == '$JOB'
| where Log_s has_any ('release ', 'store verification', 'crawl', 'run finished', 'store mismatch', 'listing', 'retry', 'discovery')
| project TimeGenerated, ContainerGroupName_s, Log_s
| order by TimeGenerated asc" -o json > "$OUT/03-run-log-events.json"

az storage blob list --account-name "$SA" --account-key "$KEY" -c marianos-scraper --prefix "$LOC/" \
  --query "[].{name:name, size:properties.contentLength, modified:properties.lastModified}" -o json > "$OUT/04-blobs.json"
for f in manifest.json report.json coverage.json observations.json; do
  az storage blob download --account-name "$SA" --account-key "$KEY" -c marianos-scraper -n "$LOC/latest/$f" \
    -f "$OUT/latest/$f" -o none 2>/dev/null || echo "missing latest/$f" >> "$OUT/missing.txt"
done
for r in $(az storage blob list --account-name "$SA" --account-key "$KEY" -c marianos-scraper --prefix "$LOC/runs/" \
             --query "[?ends_with(name,'/report.json')].name" -o tsv); do
  d="$OUT/runs/$(basename "$(dirname "$r")")"; mkdir -p "$d"
  az storage blob download --account-name "$SA" --account-key "$KEY" -c marianos-scraper -n "$r" -f "$d/report.json" -o none
done
( cd "$OUT" && find . -type f ! -name SHA256SUMS.txt | sort | xargs sha256sum > SHA256SUMS.txt )
echo "Azure evidence written to $OUT"
