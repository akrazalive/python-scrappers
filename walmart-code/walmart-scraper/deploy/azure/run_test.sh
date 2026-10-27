#!/usr/bin/env bash
# Starts / stops / collects approved live tests as MANUAL executions of the deployed job. Creates no schedule.
# Every start returns at once: the execution runs in Azure, independent of the machine that started it.
#
#   run_test.sh <sub> <rg> check              # job runs `status`: release, credential present, storage (0 requests)
#   run_test.sh <sub> <rg> selfcheck          # credentials present + test-blob write/read with the identity (0 requests)
#   run_test.sh <sub> <rg> probe              # store #100 + canary check, persistent total `probe` <= 10 requests
#   run_test.sh <sub> <rg> run <name> <cap> [args]   # `run --location walmart-100-bentonville` under the persistent
#                                             # total <name>:<cap> (client-approved); repeating it never adds requests
#   run_test.sh <sub> <rg> budget <name>      # used / remaining of a persistent total (0 provider requests)
#   run_test.sh <sub> <rg> stop               # forced interruption of the running execution (hard-stop/resume test)
#   run_test.sh <sub> <rg> status             # executions of the job (0 provider requests)
#   run_test.sh <sub> <rg> collect [exec]     # execution record, console log, run files, checksums; sets the job
#                                             # back to `status` (an accidental start sends no provider request)
#
# Totals are enforced by the fetcher with a persistent ledger in the walmart-scraper container (budget.py): every
# attempt, retries included, is counted and saved before it is sent, across restarts and repeated executions. The
# job also has replicaRetryLimit 0, so Azure never restarts an execution on its own. Starts are refused unless the
# job is Manual.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep /subscriptions/... resource ids unchanged
SUB=${1:?subscription id}; RG=${2:?resource group}; WHAT=${3:?check|probe|run|stop|status|collect}
STORE=walmart-100-bentonville
az account set --subscription "$SUB"
JOB=$(az containerapp job list -g "$RG" --query "[?starts_with(name,'wmscraper')].name | [0]" -o tsv)
[ -n "$JOB" ] || { echo "no wmscraper job in $RG"; exit 1; }
TS=$(date -u +%Y%m%dT%H%M%SZ)
last_exec(){ az containerapp job execution list -g "$RG" -n "$JOB" --query "sort_by([], &properties.startTime)[-1].name" -o tsv; }

start(){  # $1 = wmscraper arguments
  TRIG=$(az containerapp job show -g "$RG" -n "$JOB" --query properties.configuration.triggerType -o tsv)
  [ "$TRIG" = "Manual" ] || { echo "refusing: job trigger is '$TRIG'; live tests run only on a Manual job"; exit 1; }
  az containerapp job update -g "$RG" -n "$JOB" --set-env-vars "WMSCRAPER_ARGS=$1" -o none
  EXEC=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv)
  mkdir -p evidence; echo "$TS started $JOB execution $EXEC: wmscraper $1" | tee -a evidence/executions.log
  echo "Runs in Azure now (this machine can be switched off). Later: $0 $SUB $RG status | collect $EXEC"
}

case "$WHAT" in
  check) start "status" ;;
  selfcheck) start "selfcheck" ;;
  probe) start "--budget probe:10 verify-store --location $STORE --max-requests 10" ;;
  budget) start "budget-status --name ${4:?budget name}" ;;
  run)
    NAME=${4:?budget name for this approved test}; CAP=${5:?client-approved total request cap}
    [[ "$CAP" =~ ^[1-9][0-9]*$ ]] || { echo "cap must be a positive integer"; exit 1; }
    shift 5; start "--budget $NAME:$CAP run --location $STORE --max-requests $CAP $*" ;;
  stop)
    EXEC=$(last_exec)
    az containerapp job stop -g "$RG" -n "$JOB" --job-execution-name "$EXEC" -o none
    mkdir -p evidence; echo "$TS FORCED STOP of execution $EXEC (hard-stop/resume test)" | tee -a evidence/executions.log ;;
  status)
    az containerapp job execution list -g "$RG" -n "$JOB" \
      --query "[].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}" -o table ;;
  collect)
    EXEC=${4:-$(last_exec)}; OUT="evidence/azure-$EXEC-$TS"; mkdir -p "$OUT"
    az containerapp job show -g "$RG" -n "$JOB" \
      --query "{name:name,trigger:properties.configuration.triggerType,retryLimit:properties.configuration.replicaRetryLimit,image:properties.template.containers[0].image}" \
      -o json > "$OUT/job.json"
    az containerapp job execution show -g "$RG" -n "$JOB" --job-execution-name "$EXEC" -o json > "$OUT/execution.json"
    WS=$(az monitor log-analytics workspace list -g "$RG" --query "[?contains(name,'wmscraper')].customerId | [0]" -o tsv)
    az monitor log-analytics query -w "$WS" --analytics-query "
ContainerAppConsoleLogs_CL | where ContainerJobName_s == '$JOB' and ContainerGroupName_s startswith '$EXEC'
| project TimeGenerated, ContainerGroupName_s, Log_s | order by TimeGenerated asc" -o json > "$OUT/console-log.json"
    SA=$(az storage account list -g "$RG" --query "[?starts_with(name,'wmscraper')].name | [0]" -o tsv)
    KEY=$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)
    az storage blob list --account-name "$SA" --account-key "$KEY" -c walmart-scraper --prefix "$STORE/" \
      --query "[].{name:name,size:properties.contentLength,modified:properties.lastModified}" -o table > "$OUT/blobs.txt"
    for f in latest/manifest.json latest/report.json state.json; do
      az storage blob download --account-name "$SA" --account-key "$KEY" -c walmart-scraper -n "$STORE/$f" \
        -f "$OUT/$(echo "$f" | tr / -)" -o none 2>/dev/null || true
    done
    cp evidence/executions.log "$OUT/" 2>/dev/null || true
    ( cd "$OUT" && find . -type f ! -name SHA256SUMS.txt | sort | xargs sha256sum > SHA256SUMS.txt )
    ST=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['properties']['status'])" "$OUT/execution.json")
    if [ "$ST" != "Running" ]; then
      az containerapp job update -g "$RG" -n "$JOB" --set-env-vars "WMSCRAPER_ARGS=status" -o none
    fi
    echo "evidence written to $OUT (execution status: $ST)" ;;
  *) echo "unknown action: $WHAT"; exit 1 ;;
esac
