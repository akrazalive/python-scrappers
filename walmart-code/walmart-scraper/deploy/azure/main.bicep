// Walmart scraper – complete Azure environment.
// Creates: Log Analytics, Container Registry, Storage (output + checkpoints + locks),
// Key Vault (provider secrets), user-assigned identity with least-privilege roles,
// Container Apps environment and a scheduled Container Apps Job (twice weekly).

@description('Short prefix for resource names (lowercase letters/numbers).')
param prefix string = 'wmscraper'
param location string = resourceGroup().location

@description('Twice-weekly schedule in UTC (Mon and Thu 06:00).')
param cronExpression string = '0 6 * * 1,4'

@description('Runtime image. Default: public Python image that runs the versioned source package from Blob Storage.')
param image string = 'docker.io/library/python:3.12-slim'

@description('Blob (in the walmart-scraper container) holding the delivered source package that the job runs.')
param releaseBlob string = 'releases/walmart-scraper-1.0.0-src.zip'

@description('true only when image is built into this ACR (needs ACR Tasks or a CI pipeline).')
param useAcrImage bool = false

// Bootstrap: download the exact versioned source ZIP with the job's managed identity, install, run all locations.
var bootstrap = '''
import io, os, subprocess, sys, zipfile
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "azure-storage-blob", "azure-identity"], check=True)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
cc = BlobServiceClient(os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential()).get_container_client("walmart-scraper")
zipfile.ZipFile(io.BytesIO(cc.download_blob(os.environ["RELEASE_BLOB"]).readall())).extractall("/tmp/app")
root = "/tmp/app/walmart-scraper"
print("release", os.environ["RELEASE_BLOB"], open(root + "/SOURCE_FINGERPRINT.txt").read().replace(chr(10), " "), flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "-r", root + "/requirements.txt"], check=True)
os.chdir(root)
sys.exit(subprocess.run([sys.executable, "-m", "wmscraper", "run-all"], env={**os.environ, "PYTHONPATH": root + "/src"}).returncode)
'''

@description('Provider credentials – stored in Key Vault, never in code or image.')
@secure()
param oxylabsWebApiKey string = ''
@secure()
param oxylabsUsername string = ''
@secure()
param oxylabsPassword string = ''
@secure()
param zyteApiKey string = ''

var suffix = uniqueString(resourceGroup().id)
var storageName = take('${prefix}${suffix}', 24)
var kvName = take('${prefix}-kv-${suffix}', 24)
var acrName = take('${prefix}acr${suffix}', 50)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id'
  location: location
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false, supportsHttpsTrafficOnly: true }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: { deleteRetentionPolicy: { enabled: true, days: 14 }, isVersioningEnabled: true }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'walmart-scraper'
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource sOxyKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(oxylabsWebApiKey)) {
  parent: kv
  name: 'oxylabs-webapi-key'
  properties: { value: oxylabsWebApiKey }
}
resource sOxyUser 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(oxylabsUsername)) {
  parent: kv
  name: 'oxylabs-username'
  properties: { value: oxylabsUsername }
}
resource sOxyPass 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(oxylabsPassword)) {
  parent: kv
  name: 'oxylabs-password'
  properties: { value: oxylabsPassword }
}
resource sZyte 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(zyteApiKey)) {
  parent: kv
  name: 'zyte-api-key'
  properties: { value: zyteApiKey }
}

// ---- least-privilege role assignments for the job identity
var roles = {
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}
resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.blobContributor)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor) }
}
resource raKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, identity.id, roles.kvSecretsUser)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser) }
}
resource raAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, roles.acrPull)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull) }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

var kvSecrets = concat(
  empty(oxylabsWebApiKey) ? [] : [ { name: 'oxylabs-webapi-key', keyVaultUrl: '${kv.properties.vaultUri}secrets/oxylabs-webapi-key', identity: identity.id } ],
  empty(oxylabsUsername) ? [] : [ { name: 'oxylabs-username', keyVaultUrl: '${kv.properties.vaultUri}secrets/oxylabs-username', identity: identity.id } ],
  empty(oxylabsPassword) ? [] : [ { name: 'oxylabs-password', keyVaultUrl: '${kv.properties.vaultUri}secrets/oxylabs-password', identity: identity.id } ],
  empty(zyteApiKey) ? [] : [ { name: 'zyte-api-key', keyVaultUrl: '${kv.properties.vaultUri}secrets/zyte-api-key', identity: identity.id } ]
)
var secretEnv = concat(
  empty(oxylabsWebApiKey) ? [] : [ { name: 'OXYLABS_WEBAPI_KEY', secretRef: 'oxylabs-webapi-key' } ],
  empty(oxylabsUsername) ? [] : [ { name: 'OXYLABS_USERNAME', secretRef: 'oxylabs-username' } ],
  empty(oxylabsPassword) ? [] : [ { name: 'OXYLABS_PASSWORD', secretRef: 'oxylabs-password' } ],
  empty(zyteApiKey) ? [] : [ { name: 'ZYTE_API_KEY', secretRef: 'zyte-api-key' } ]
)

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-job'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [ raBlob, raKv, raAcr, sOxyKey, sOxyUser, sOxyPass, sZyte ]
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: { cronExpression: cronExpression, parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: 28800          // 8 h hard stop; an unfinished run resumes from its checkpoint next time
      replicaRetryLimit: 1
      registries: useAcrImage ? [ { server: acr.properties.loginServer, identity: identity.id } ] : []
      secrets: kvSecrets
    }
    template: {
      containers: [
        {
          name: 'scraper'
          image: image
          command: useAcrImage ? [ 'python', '-m', 'wmscraper' ] : [ 'python', '-c', bootstrap ]
          args: useAcrImage ? [ 'run-all' ] : []
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat(secretEnv, [
            { name: 'WMSCRAPER_OUTPUT_BACKEND', value: 'azure_blob' }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'LOG_LEVEL', value: 'INFO' }
            { name: 'RELEASE_BLOB', value: releaseBlob }
          ])
        }
      ]
    }
  }
}

output acrLoginServer string = acr.properties.loginServer
output storageAccount string = storage.name
output keyVault string = kv.name
output jobName string = job.name
