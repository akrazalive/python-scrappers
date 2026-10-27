// Walmart scraper – Azure environment inside ONE existing resource group (resource-group Contributor is enough).
// Creates: Log Analytics, Storage (Blob container walmart-scraper: release package, output, checkpoints, run locks),
// an EMPTY Key Vault, a user-assigned managed identity, a Container Apps environment and (phase 2) the job.
//
// Two phases:
//   deployJob=false (phase 1, "infra"): no job, no schedule, no provider credential needed. The client's administrator
//     then applies the two scoped role assignments printed by deploy.sh and stores the Oxylabs credential in the vault.
//   deployJob=true  (phase 2, "job"): the job – trigger MANUAL, default command `status` (0 provider requests).
//     A Key Vault reference to a missing secret would fail, so phase 2 runs only after the secret and roles exist.
// Role assignments (only with assignRoles=true, i.e. a deployer with role-assignment rights):
//   Storage Blob Data Contributor on the walmart-scraper CONTAINER, Key Vault Secrets User on the vault.
// No container registry: the job runs the versioned source ZIP from Blob on the public Python image, so no AcrPull.

@description('Short prefix for resource names (lowercase letters/numbers).')
param prefix string = 'wmscraper'
param location string = resourceGroup().location

@description('Tags required by the subscription policy, if any.')
param tags object = {}

@description('Twice-weekly schedule in UTC (Mon and Thu 06:00), used only when scheduleEnabled=true.')
param cronExpression string = '0 6 * * 1,4'

@description('Runtime image: public Python image that runs the versioned source package stored in Blob Storage.')
param image string = 'docker.io/library/python:3.12-slim'

@description('Blob (in the walmart-scraper container) holding the delivered source package that the job runs.')
param releaseBlob string = 'releases/walmart-scraper-1.1.7-src.zip'

@description('Create the job identity role assignments (needs Owner / User Access Administrator / RBAC Administrator).')
param assignRoles bool = false

@description('Phase 2: create the Container Apps Job (needs the Key Vault secret and the role assignments).')
param deployJob bool = false

@description('false = manual-start job only (no unattended schedule). Set true only after the client approves the schedule.')
param scheduleEnabled bool = false

@description('Oxylabs integration: oxylabs_webapi = API key (Bearer, webapi.oxylabs.io/v1/scrape/walmart); oxylabs = API user name + password (Basic, realtime.oxylabs.io).')
@allowed([ 'oxylabs_webapi', 'oxylabs' ])
param fetchProvider string = 'oxylabs_webapi'

@description('What a manual execution runs (wmscraper CLI arguments). Default status = zero provider requests, so an accidental start costs nothing. Approved tests set it per execution (deploy/azure/run_test.sh).')
param defaultArgs string = 'status'

@description('Longest one execution may run, in seconds (default 24 h). An unfinished run resumes from its checkpoint on the next execution.')
param replicaTimeoutSeconds int = 86400

@description('Automatic retries of a failed replica. 0 so that one execution can never send more than its --max-requests cap.')
param replicaRetryLimit int = 0

// Bootstrap: download the exact versioned source ZIP with the job's managed identity, install, run WMSCRAPER_ARGS.
var bootstrap = '''
import io, os, shlex, subprocess, sys, zipfile
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "azure-storage-blob==12.31.0", "azure-identity==1.26.0"], check=True)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
cc = BlobServiceClient(os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential()).get_container_client("walmart-scraper")
zipfile.ZipFile(io.BytesIO(cc.download_blob(os.environ["RELEASE_BLOB"]).readall())).extractall("/tmp/app")
root = "/tmp/app/walmart-scraper"
print("release", os.environ["RELEASE_BLOB"], open(root + "/SOURCE_FINGERPRINT.txt").read().replace(chr(10), " "), flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "-r", root + "/requirements.txt"], check=True)
os.chdir(root)
args = shlex.split(os.environ.get("WMSCRAPER_ARGS") or "status")
print("wmscraper", args, flush=True)
sys.exit(subprocess.run([sys.executable, "-m", "wmscraper", *args], env={**os.environ, "PYTHONPATH": root + "/src"}).returncode)
'''

var suffix = uniqueString(resourceGroup().id)
// Key Vault secret names the client's administrator sets (never sent to the developer; RG Contributor cannot read them)
var providerSecrets = fetchProvider == 'oxylabs_webapi' ? [ 'oxylabs-webapi-key' ] : [ 'oxylabs-username', 'oxylabs-password' ]
var providerEnv = fetchProvider == 'oxylabs_webapi' ? [
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
  // daily ingestion cap (client spending allowance): logs stop being collected for the day instead of costing more
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30, workspaceCapping: { dailyQuotaGb: json('0.03') } }
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
  name: 'walmart-scraper'
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

// ---- least-privilege role assignments for the job identity (normally applied by the client's administrator)
var roles = {
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}
// everything the job reads or writes (release, output, checkpoints, run locks) is in this one container
resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  scope: container
  name: guid(container.id, identity.id, roles.blobContributor)
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

resource job 'Microsoft.App/jobs@2024-03-01' = if (deployJob) {
  name: '${prefix}-job'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [ raBlob, raKv ]
  properties: {
    environmentId: env.id
    configuration: {
      // Manual until the client approves days/time; scheduleEnabled=true switches to the cron
      triggerType: scheduleEnabled ? 'Schedule' : 'Manual'
      scheduleTriggerConfig: scheduleEnabled ? { cronExpression: cronExpression, parallelism: 1, replicaCompletionCount: 1 } : null
      manualTriggerConfig: scheduleEnabled ? null : { parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: replicaTimeoutSeconds
      replicaRetryLimit: replicaRetryLimit
      secrets: [for n in providerSecrets: { name: n, keyVaultUrl: '${kv.properties.vaultUri}secrets/${n}', identity: identity.id }]
    }
    template: {
      containers: [
        {
          name: 'scraper'
          image: image
          command: [ 'python', '-c', bootstrap ]
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat(providerEnv, [
            { name: 'WMSCRAPER_FETCH_PROVIDER', value: fetchProvider }
            { name: 'WMSCRAPER_ARGS', value: scheduleEnabled ? 'run-all' : defaultArgs }
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

output storageAccount string = storage.name
output storageId string = storage.id
output containerName string = container.name
output containerId string = container.id
output keyVault string = kv.name
output keyVaultId string = kv.id
output keyVaultUri string = kv.properties.vaultUri
output identityName string = identity.name
output identityPrincipalId string = identity.properties.principalId
output identityClientId string = identity.properties.clientId
output identityId string = identity.id
output secretNames array = providerSecrets
output jobName string = deployJob ? job.name : ''
