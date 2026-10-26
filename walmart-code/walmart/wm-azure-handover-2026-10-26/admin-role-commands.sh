# Run by an administrator with role-assignment rights on resource group scraper-contest-asif-test (two scoped assignments):
# 1) blob data access limited to the designated test container, 2) secret read access limited to the test vault.
az role assignment create --assignee-object-id 3705145d-855c-4330-978f-be6e229c49ac --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope /subscriptions/febcf465-0d68-44e1-bc04-303bf48bf02d/resourceGroups/scraper-contest-asif-test/providers/Microsoft.Storage/storageAccounts/wmscraperzwkzlg5qbam5a/blobServices/default/containers/walmart-scraper
az role assignment create --assignee-object-id 3705145d-855c-4330-978f-be6e229c49ac --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope /subscriptions/febcf465-0d68-44e1-bc04-303bf48bf02d/resourceGroups/scraper-contest-asif-test/providers/Microsoft.KeyVault/vaults/wmscraper-kv-zwkzlg5qbam
# Store the Oxylabs API user yourself (never in chat; you need "Key Vault Secrets Officer" on wmscraper-kv-zwkzlg5qbam).
# The developer's resource-group Contributor role cannot read Key Vault secrets.
az keyvault secret set --vault-name wmscraper-kv-zwkzlg5qbam --name oxylabs-username --value "<API-USER-NAME>"
az keyvault secret set --vault-name wmscraper-kv-zwkzlg5qbam --name oxylabs-password --value "<API-USER-PASSWORD>"
# Check (lists the two assignments):
az role assignment list --assignee 3705145d-855c-4330-978f-be6e229c49ac --all --query "[].{role:roleDefinitionName,scope:scope}" -o table
