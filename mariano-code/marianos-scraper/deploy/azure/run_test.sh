#!/usr/bin/env bash
# Starts / stops / collects the agreed live runs as MANUAL executions of the deployed job. Creates no schedule.
# Every start returns at once: the execution runs in Azure, independent of the machine that started it.
#
#   run_test.sh <sub> <rg> test1             # <= 19 provider requests in total (both stores + probe)
#   run_test.sh <sub> <rg> test2             # <= 300 in total (Batteries + Light Bulbs, Crystal Lake, no publish)
#   run_test.sh <sub> <rg> full <cap>        # Test 3: all CSV rows, Crystal Lake, total <= <cap> (client-approved);
#                                            # the same command resumes the unfinished run from its checkpoint
#   run_test.sh <sub> <rg> stop              # forced interruption of the running execution (kill/resume test)
#   run_test.sh <sub> <rg> status            # executions + budget usage (0 provider requests)
#   run_test.sh <sub> <rg> collect [exec]    # download console log, budget ledger and state evidence; sets the
#                                            # job back to budget-status (an accidental start sends no requests)
#
# Total caps are enforced inside the scraper by budget files on the job's Azure Files share (state/_budgets/), so a
# repeated or resumed run can never send more than its total. Starts are refused unless the job trigger is Manual.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep /subscriptions/... resource ids unchanged
SUB=${1:?subscription id}; RG=${2:?resource group}; WHAT=${3:?test1|test2|full|stop|status|collect}
STORE=marianos-544-crystal-lake
az account set --subscription "$SUB"
JOB=$(az containerapp job list -g "$RG" --query "[?starts_with(name,'mscraper')].name | [0]" -o tsv)
[ -n "$JOB" ] || { echo "no mscraper job in $RG"; exit 1; }
TS=$(date -u +%Y%m%dT%H%M%SZ)
last_exec(){ az containerapp job execution list -g "$RG" -n "$JOB" --query "sort_by([], &properties.startTime)[-1].name" -o tsv; }

start(){  # $1 = mscraper arguments
  TRIG=$(az containerapp job show -g "$RG" -n "$JOB" --query properties.configuration.triggerType -o tsv)
  [ "$TRIG" = "Manual" ] || { echo "refusing: job trigger is '$TRIG'; live tests run only on a Manual job"; exit 1; }
  az containerapp job update -g "$RG" -n "$JOB" --set-env-vars "MSCRAPER_ARGS=$1" -o none
  EXEC=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv)
  mkdir -p evidence; echo "$TS started $JOB execution $EXEC: mscraper $1" | tee -a evidence/executions.log
  echo "Runs in Azure now (this machine can be switched off). Later: $0 $SUB $RG status | collect $EXEC"
}

case "$WHAT" in
  test1|test2) start "bounded-test $WHAT" ;;
  full) CAP=${4:?client-approved total request cap}; start "--budget test3:$CAP run --location $STORE --resume" ;;
  stop)
    EXEC=$(last_exec)
    az containerapp job stop -g "$RG" -n "$JOB" --job-execution-name "$EXEC" -o none
    mkdir -p evidence; echo "$TS FORCED STOP of execution $EXEC (kill/resume test)" | tee -a evidence/executions.log ;;
  status)
    az containerapp job execution list -g "$RG" -n "$JOB" \
      --query "[].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}" -o table
    SA=$(az storage account list -g "$RG" --query "[?starts_with(name,'mscraper')].name | [0]" -o tsv)
    KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
    TMP=$(mktemp -d)
    az storage file download-batch --account-name "$SA" --account-key "$KEY" -s scraper-state -d "$TMP" \
      --pattern "_budgets/*.json" -o none 2>/dev/null || true
    for f in "$TMP"/_budgets/*.json; do
      [ -f "$f" ] && python -c "import json,sys;b=json.load(open(sys.argv[1]));print(f\"budget {b['name']}: {b['used']}/{b['total']} used\")" "$f"
    done
    rm -rf "$TMP" ;;
  collect)
    EXEC=${4:-$(last_exec)}; OUT="evidence/azure-$EXEC-$TS"; mkdir -p "$OUT"
    az containerapp job execution show -g "$RG" -n "$JOB" --job-execution-name "$EXEC" -o json > "$OUT/execution.json"
    WS=$(az monitor log-analytics workspace list -g "$RG" --query "[?contains(name,'mscraper')].customerId | [0]" -o tsv)
    az monitor log-analytics query -w "$WS" --analytics-query "
ContainerAppConsoleLogs_CL | where ContainerJobName_s == '$JOB' and ContainerGroupName_s startswith '$EXEC'
| project TimeGenerated, ContainerGroupName_s, Log_s | order by TimeGenerated asc" -o json > "$OUT/console-log.json"
    SA=$(az storage account list -g "$RG" --query "[?starts_with(name,'mscraper')].name | [0]" -o tsv)
    KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
    az storage file download-batch --account-name "$SA" --account-key "$KEY" -s scraper-state -d "$OUT/state" -o none
    cp evidence/executions.log "$OUT/" 2>/dev/null || true
    ( cd "$OUT" && find . -type f ! -name SHA256SUMS.txt | sort | xargs sha256sum > SHA256SUMS.txt )
    ST=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['properties']['status'])" "$OUT/execution.json")
    if [ "$ST" != "Running" ]; then
      az containerapp job update -g "$RG" -n "$JOB" --set-env-vars "MSCRAPER_ARGS=budget-status" -o none
    fi
    echo "evidence written to $OUT (execution status: $ST)" ;;
  *) echo "unknown action: $WHAT"; exit 1 ;;
esac
