#!/usr/bin/env bash
# Collects proof of unattended Azure execution and publishing.
#   ./deploy/azure/collect_evidence.sh <resource-group> [location-key]
# Output: evidence/azure-<timestamp>/ (job definition, schedule, executions, logs, published blobs)
set -euo pipefail
RG=${1:?resource group}; LOC=${2:-walmart-100-bentonville}
OUT="evidence/azure-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"
JOB=$(az containerapp job list -g "$RG" --query "[0].name" -o tsv)
SA=$(az storage account list -g "$RG" --query "[0].name" -o tsv)
WS=$(az monitor log-analytics workspace list -g "$RG" --query "[0].customerId" -o tsv)

az containerapp job show -g "$RG" -n "$JOB" \
  --query "{name:name, trigger:properties.configuration.triggerType, cron:properties.configuration.scheduleTriggerConfig.cronExpression, parallelism:properties.configuration.scheduleTriggerConfig.parallelism, image:properties.template.containers[0].image}" \
  -o json > "$OUT/01-job-schedule.json"
az containerapp job execution list -g "$RG" -n "$JOB" \
  --query "[].{name:name, status:properties.status, start:properties.startTime, end:properties.endTime}" -o table > "$OUT/02-executions.txt"

az monitor log-analytics query -w "$WS" --analytics-query "
ContainerAppConsoleLogs_CL
| where ContainerJobName_s == '$JOB'
| extend e = parse_json(Log_s)
| where tostring(e.event) in ('run_start','store_verified','category_discovered','canary','run_resumed','listing_failed','store_context_mismatch','published','not_published','run_end')
| project TimeGenerated, event=tostring(e.event), run_id=tostring(e.run_id), detail=Log_s
| order by TimeGenerated asc" -o json > "$OUT/03-run-events.json"

az storage blob list --account-name "$SA" -c walmart-scraper --auth-mode login --prefix "$LOC/" \
  --query "[].{name:name, size:properties.contentLength, modified:properties.lastModified}" -o table > "$OUT/04-blobs.txt"
az storage blob download --account-name "$SA" -c walmart-scraper --auth-mode login \
  -n "$LOC/latest/manifest.json" -f "$OUT/05-published-manifest.json" -o none
az storage blob download --account-name "$SA" -c walmart-scraper --auth-mode login \
  -n "$LOC/latest/report.json" -f "$OUT/06-published-report.json" -o none

echo "Azure evidence written to $OUT"
