# Azure preflight – 2026-10-25 03:41 UTC (Sat 24 Oct 22:41 CDT) – read-only, nothing was created or changed

Signed in as debugging.specialist@gmail.com (guest), tenant b6d4bd45-c947-4f69-9949-7e688a70561e, Azure CLI 2.x.

| Check | Result | File |
|---|---|---|
| Subscription febcf465-0d68-44e1-bc04-303bf48bf02d visible | yes ("Azure subscription 1", Enabled) | – |
| Resource group scraper-contest-asif-test | visible, westus2, no tags | group.json |
| My role on the group | **Contributor** (scope: scraper-contest-asif-test) | my-roles.json |
| Resources in the group | none (empty) | resources.json |
| Resource providers | Microsoft.App, Microsoft.OperationalInsights, Microsoft.Storage, Microsoft.KeyVault, Microsoft.ManagedIdentity: **all Registered** | providers.txt |
| Policy assignments on the group | none | policies.json |
| `az deployment group what-if` of phase 1 (infra) | Succeeded – a preview only; it would create: Log Analytics workspace, user-assigned identity, Storage account (Blob container + Azure Files share), Key Vault, Container Apps environment. Keys masked by Azure. | what-if-infra.json |

Not done: no deployment, no role assignment, no secret, no provider request.
