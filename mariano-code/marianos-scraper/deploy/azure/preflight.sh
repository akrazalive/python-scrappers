#!/usr/bin/env bash
# READ-ONLY check of the Azure test access before anything is deployed. Changes nothing.
#   ./deploy/azure/preflight.sh <subscription-id> <resource-group>
# Writes evidence/azure-preflight-<ts>/preflight.json and prints PASS / ACTION NEEDED lines.
set -uo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep /subscriptions/... resource ids unchanged
SUB=${1:?subscription id}; RG=${2:?resource group}
OUT="evidence/azure-preflight-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"
az account set --subscription "$SUB" || { echo "ACTION NEEDED: subscription $SUB not visible to this account"; exit 1; }

ME=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || az account show --query user.name -o tsv)
RG_JSON=$(az group show -n "$RG" -o json 2>/dev/null) || { echo "ACTION NEEDED: resource group $RG not visible"; exit 1; }
SCOPE=$(echo "$RG_JSON" | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
ROLES=$(az role assignment list --assignee "$ME" --scope "$SCOPE" --include-inherited --query "[].roleDefinitionName" -o json 2>/dev/null || echo "[]")

python - "$OUT" "$SUB" "$RG" "$RG_JSON" "$ROLES" <<'PY'
import json, shutil, subprocess, sys
out, sub, rg, rg_json, roles = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), json.loads(sys.argv[5] or "[]")
def az(*a):
    r = subprocess.run([shutil.which("az") or "az", *a, "-o", "json"], capture_output=True, text=True, shell=False)  # az.cmd on Windows
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
providers = {}
for ns in ("Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.Storage", "Microsoft.KeyVault", "Microsoft.ManagedIdentity"):
    p = az("provider", "show", "-n", ns, "--query", "registrationState")
    providers[ns] = p
can_deploy = any(r in roles for r in ("Owner", "Contributor"))
can_assign = any(r in roles for r in ("Owner", "User Access Administrator", "Role Based Access Control Administrator"))
existing = az("resource", "list", "-g", rg, "--query", "[].{type:type,name:name}") or []
res = {"subscription": sub, "resource_group": rg, "location": rg_json.get("location"), "tags": rg_json.get("tags"),
       "my_roles_on_rg": roles, "can_deploy_resources": can_deploy, "can_assign_roles": can_assign,
       "providers": providers, "existing_resources": existing}
json.dump(res, open(f"{out}/preflight.json", "w"), indent=2)
print(json.dumps(res, indent=2))
print("PASS  can deploy" if can_deploy else "ACTION NEEDED: Contributor (or Owner) on the resource group")
print("PASS  can assign roles" if can_assign else "NOTE: no role-assignment right -> deploy with assignRoles=false; admin runs evidence/.../admin-role-commands.sh")
for ns, st in providers.items():
    print(("PASS  " if st == "Registered" else "ACTION NEEDED: register ") + f"{ns} ({st})")
PY
echo "preflight written to $OUT (read-only, nothing was changed)"
