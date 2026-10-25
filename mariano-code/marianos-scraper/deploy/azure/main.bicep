// Mariano's scraper – Azure environment inside ONE existing resource group (limited test access supported).
// Creates: Log Analytics, Storage (Blob: output + releases + run locks; Azure Files: checkpoints),
// Key Vault (Oxylabs credentials), user-assigned identity, Container Apps environment and (phase 2) the job –
// MANUAL by default: each execution runs MSCRAPER_ARGS (default budget-status = no provider requests).
//
// Limited access (resource-group Contributor only): deploy with assignRoles=false. The two role assignments the
// job identity needs are then printed by deploy.sh for the client's administrator (Contributor cannot assign roles).
// Two phases: deployJob=false creates the infrastructure; after the Key Vault secret and the roles exist,
// deployJob=true adds the scheduled job (a Key Vault reference to a missing secret would fail the deployment).

@description('Short prefix for resource names (lowercase letters/numbers).')
param prefix string = 'mscraper'
param location string = resourceGroup().location

@description('Tags required by the subscription policy, if any.')
param tags object = {}

@description('Twice-weekly schedule in UTC (Tue and Fri 07:00).')
param cronExpression string = '0 7 * * 2,5'

@description('Runtime image: public Python image that runs the versioned source package stored in Blob Storage.')
param image string = 'docker.io/library/python:3.12-slim'

@description('Blob (in the marianos-scraper container) holding the delivered source package the job runs.')
param releaseBlob string = 'releases/marianos-scraper-1.1.2-src.zip'

@description('Create the job identity role assignments (needs Owner / User Access Administrator / RBAC Administrator).')
param assignRoles bool = false

@description('Phase 2: create the scheduled Container Apps Job (needs the Key Vault secret and the role assignments).')
param deployJob bool = false

@description('false = manual-start job only (no unattended schedule). Set true only after the client approves the schedule.')
param scheduleEnabled bool = false

@description('Oxylabs Web Scraper API integration: oxylabs_kroger = API key (Bearer, webapi.oxylabs.io); oxylabs_realtime = API user name + password (Basic, realtime.oxylabs.io).')
@allowed([ 'oxylabs_kroger', 'oxylabs_realtime' ])
param fetchProvider string = 'oxylabs_kroger'

@description('What a manual job execution runs (mscraper CLI arguments). Default budget-status = zero provider requests, so an accidental start costs nothing. Bounded tests set it per execution (deploy/azure/run_test.sh).')
param defaultArgs string = 'budget-status'

@description('Longest one execution may run, in seconds (default 24 h). A full run continues in the cloud with the developer PC off; if the replica stops early it is retried from its checkpoint (replicaRetryLimit).')
param replicaTimeoutSeconds int = 86400

@description('Automatic retries of a failed / stopped replica within one execution; each retry resumes from the checkpoint on Azure Files.')
param replicaRetryLimit int = 2

@description('Parallel provider requests (MSCRAPER_CONCURRENCY); set from the Test 2 measurement and the Oxylabs plan.')
param concurrency int = 4

@description('Optional: Oxylabs key to store in Key Vault. Leave empty when the client stores the secret itself.')
@secure()
param oxylabsWebApiKey string = ''

// Bootstrap: download the exact versioned source ZIP with the job's managed identity, install, run all enabled stores.
var bootstrap = '''
import io, os, subprocess, sys, zipfile
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "azure-storage-blob==12.31.0", "azure-identity==1.26.0"], check=True)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
cc = BlobServiceClient(os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential()).get_container_client("marianos-scraper")
zipfile.ZipFile(io.BytesIO(cc.download_blob(os.environ["RELEASE_BLOB"]).readall())).extractall("/tmp/app")
root = "/tmp/app/marianos-scraper"
print("release", os.environ["RELEASE_BLOB"], open(root + "/SOURCE_FINGERPRINT.txt").read().replace(chr(10), " "), flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "-r", root + "/requirements.lock"], check=True)
os.chdir(root)
import shlex
args = shlex.split(os.environ.get("MSCRAPER_ARGS") or "budget-status")
print("mscraper", args, "budget", os.environ.get("MSCRAPER_BUDGET", ""), flush=True)
sys.exit(subprocess.run([sys.executable, "-m", "mscraper", *args], env={**os.environ, "PYTHONPATH": root + "/src"}).returncode)
'''

var suffix = uniqueString(resourceGroup().id)
// Key Vault secret names the client's administrator sets (never sent to the developer; RG Contributor cannot read them)
var providerSecrets = fetchProvider == 'oxylabs_kroger' ? [ 'oxylabs-webapi-key' ] : [ 'oxylabs-username', 'oxylabs-password' ]
var providerEnv = fetchProvider == 'oxylabs_kroger' ? [
  { name: 'OXYLABS_WEBAPI_KEY', secretRef: 'oxylabs-webapi-key' }
] : [
  { name: 'OXYLABS_USERNAME', secretRef: 'oxylabs-username' }
  { name: 'OXYLABS_PASSWORD', secretRef: 'oxylabs-password' }
]
var storageName = take('${prefix}${suffix}', 24)
var kvName = take('${prefix}-kv-${suffix}', 24)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id'
  location: location
  tags: tags
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
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
  name: 'marianos-scraper'
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource stateShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'scraper-state'      // checkpoints survive container restarts -> interrupted runs resume
  properties: { shareQuota: 5 }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
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

var roles = {
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}
resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  scope: storage
  name: guid(storage.id, identity.id, roles.blobContributor)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor) }
}
resource raKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  scope: kv
  name: guid(kv.id, identity.id, roles.kvSecretsUser)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser) }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: env
  name: 'state'
  properties: {
    azureFile: { accountName: storage.name, accountKey: storage.listKeys().keys[0].value, shareName: stateShare.name, accessMode: 'ReadWrite' }
  }
}

resource job 'Microsoft.App/jobs@2024-03-01' = if (deployJob) {
  name: '${prefix}-job'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [ raBlob, raKv, sOxyKey ]
  properties: {
    environmentId: env.id
    configuration: {
      // Manual until the client approves days/time (measured runtime first); scheduleEnabled=true switches to the cron
      triggerType: scheduleEnabled ? 'Schedule' : 'Manual'
      scheduleTriggerConfig: scheduleEnabled ? { cronExpression: cronExpression, parallelism: 1, replicaCompletionCount: 1 } : null
      manualTriggerConfig: scheduleEnabled ? null : { parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: replicaTimeoutSeconds   // one execution covers a full run; unfinished work resumes from the checkpoint
      replicaRetryLimit: replicaRetryLimit
      secrets: [for n in providerSecrets: { name: n, keyVaultUrl: '${kv.properties.vaultUri}secrets/${n}', identity: identity.id }]
    }
    template: {
      volumes: [ { name: 'state', storageType: 'AzureFile', storageName: envStorage.name } ]
      containers: [
        {
          name: 'scraper'
          image: image
          command: [ 'python', '-c', bootstrap ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          volumeMounts: [ { volumeName: 'state', mountPath: '/state' } ]
          env: concat(providerEnv, [
            { name: 'MSCRAPER_FETCH_PROVIDER', value: fetchProvider }
            { name: 'MSCRAPER_CONCURRENCY', value: string(concurrency) }
            { name: 'MSCRAPER_ARGS', value: scheduleEnabled ? 'run-all' : defaultArgs }
            { name: 'MSCRAPER_OUTPUT_BACKEND', value: 'azure_blob' }
            { name: 'MSCRAPER_STATE_DIR', value: '/state' }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'RELEASE_BLOB', value: releaseBlob }
          ])
        }
      ]
    }
  }
}

output storageAccount string = storage.name
output keyVault string = kv.name
output identityPrincipalId string = identity.properties.principalId
output storageId string = storage.id
output keyVaultId string = kv.id
output jobName string = deployJob ? job.name : ''
