#!/usr/bin/env bash
# Runs ONE agreed bounded live test as a single MANUAL execution of the deployed job. Creates no schedule.
#
#   ./deploy/azure/run_test.sh <subscription-id> <resource-group> test1     # <= 19 provider requests in total
#   ./deploy/azure/run_test.sh <subscription-id> <resource-group> test2     # <= 300 provider requests in total
#   ./deploy/azure/run_test.sh <subscription-id> <resource-group> status    # budget usage; 0 provider requests
#
# The total cap is enforced inside the scraper by a budget file on the job's Azure Files share (state/_budgets/),
# so repeating or resuming a test can never send more than its total. The job's trigger must be Manual, or nothing
# is started. After the execution the job is set back to `budget-status` (an accidental start sends no requests).
# Output: evidence/azure-<test>-<ts>/ (execution record, console log, budget ledger, probe / run evidence).
set -euo pipefail
SUB=${1:?subscription id}; RG=${2:?resource group}; WHAT=${3:?test1|test2|status}
case "$WHAT" in test1|test2) ARGS="bounded-test $WHAT" ;; status) ARGS="budget-status" ;;
  *) echo "unknown test: $WHAT"; exit 1 ;; esac
az account set --subscription "$SUB"
JOB=$(az containerapp job list -g "$RG" --query "[?starts_with(name,'mscraper')].name | [0]" -o tsv)
[ -n "$JOB" ] || { echo "no mscraper job in $RG"; exit 1; }
TRIG=$(az containerapp job show -g "$RG" -n "$JOB" --query properties.configuration.triggerType -o tsv)
[ "$TRIG" = "Manual" ] || { echo "refusing: job trigger is '$TRIG', bounded tests run only on a Manual job"; exit 1; }
OUT="evidence/azure-$WHAT-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"

az containerapp job update -g "$RG" -n "$JOB" --set-env-vars "MSCRAPER_ARGS=$ARGS" -o none
trap 'az containerapp job update -g "$RG" -n "$JOB" --set-env-vars "MSCRAPER_ARGS=budget-status" -o none' EXIT
EXEC=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv)
echo "$(date -u +%FT%TZ) started $JOB execution $EXEC: mscraper $ARGS" | tee "$OUT/execution.txt"
while :; do
  ST=$(az containerapp job execution show -g "$RG" -n "$JOB" --job-execution-name "$EXEC" --query properties.status -o tsv)
  case "$ST" in Running|Processing|"") sleep 30 ;; *) break ;; esac
done
az containerapp job execution show -g "$RG" -n "$JOB" --job-execution-name "$EXEC" -o json > "$OUT/execution.json"
echo "$(date -u +%FT%TZ) execution $EXEC finished: $ST" | tee -a "$OUT/execution.txt"

# console log (Log Analytics ingestion can lag a few minutes; re-run the query below if it comes back short)
WS=$(az monitor log-analytics workspace list -g "$RG" --query "[?contains(name,'mscraper')].customerId | [0]" -o tsv)
sleep 120
az monitor log-analytics query -w "$WS" --analytics-query "
ContainerAppConsoleLogs_CL | where ContainerJobName_s == '$JOB' and ContainerGroupName_s startswith '$EXEC'
| project TimeGenerated, Log_s | order by TimeGenerated asc" -o json > "$OUT/console-log.json"

# budget ledger + verification / probe / run evidence from the job's state share
SA=$(az storage account list -g "$RG" --query "[?starts_with(name,'mscraper')].name | [0]" -o tsv)
KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
az storage file download-batch --account-name "$SA" --account-key "$KEY" -s scraper-state -d "$OUT/state" \
  --pattern "_budgets/*" -o none
if [ "$WHAT" != "status" ]; then
  az storage file download-batch --account-name "$SA" --account-key "$KEY" -s scraper-state -d "$OUT/state" -o none
fi
( cd "$OUT" && find . -type f ! -name SHA256SUMS.txt | sort | xargs sha256sum > SHA256SUMS.txt )
echo "evidence written to $OUT"
