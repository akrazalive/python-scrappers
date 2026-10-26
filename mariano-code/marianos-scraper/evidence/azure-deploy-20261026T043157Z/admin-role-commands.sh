# Run by an administrator with role-assignment rights on resource group scraper-contest-asif-test (two scoped assignments):
# 1) blob data access limited to the designated test container, 2) secret read access limited to the test vault.
az role assignment create --assignee-object-id bb915f14-a28a-4ced-898d-fc3b070548ae --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope /subscriptions/febcf465-0d68-44e1-bc04-303bf48bf02d/resourceGroups/scraper-contest-asif-test/providers/Microsoft.Storage/storageAccounts/mscraperzwkzlg5qbam5a/blobServices/default/containers/marianos-scraper
az role assignment create --assignee-object-id bb915f14-a28a-4ced-898d-fc3b070548ae --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope /subscriptions/febcf465-0d68-44e1-bc04-303bf48bf02d/resourceGroups/scraper-contest-asif-test/providers/Microsoft.KeyVault/vaults/mscraper-kv-zwkzlg5qbam5
# Store the Oxylabs Web Scraper API user yourself (never in chat; you need "Key Vault Secrets Officer" on mscraper-kv-zwkzlg5qbam5).
# The developer's resource-group Contributor role cannot read Key Vault secrets.
az keyvault secret set --vault-name mscraper-kv-zwkzlg5qbam5 --name oxylabs-username --value "<API-USER-NAME>"
az keyvault secret set --vault-name mscraper-kv-zwkzlg5qbam5 --name oxylabs-password --value "<API-USER-PASSWORD>"
# Check (lists the two assignments):
az role assignment list --assignee bb915f14-a28a-4ced-898d-fc3b070548ae --all --query "[].{role:roleDefinitionName,scope:scope}" -o table
