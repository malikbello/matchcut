// Matchcut on Azure: the Studio API as a Container App and the fan-cut renderer as a
// queue-triggered Container Apps Job, with keyless access everywhere (ADR-0004, ADR-0005).
//
//   az deployment group create -g rg-matchcut-dev -p infra/main.bicepparam  (or: bash deploy/deploy.sh)
targetScope = 'resourceGroup'

@description('Short name used in every resource name')
param name string = 'matchcut'
param location string = resourceGroup().location
@description('Existing Foundry (AI Services) account that hosts the model and Speech')
param foundryName string
@description('Model deployment the analyst agent uses')
param modelDeployment string = 'gpt-5-mini'
@description('Image tags in the registry; set by CI from the commit')
param apiImageTag string = 'latest'
param recapImageTag string = 'latest'
@description('SHA-256 of the Studio access code (the code itself is never stored)')
@secure()
param accessCodeSha256 string
@description('Key that signs Studio session cookies')
@secure()
param sessionSecret string
@description('GitHub repository whose production environment may release (OIDC, no secrets), as GitHub names it in the token subject: owner@id/repo@id, so a re-created repository with the same name is not trusted')
param githubRepo string = 'malikbello@139644523/matchcut@1423646206'
@description('People and CI identities that publish the showcase bundle (blob data access)')
param deployerPrincipalIds array = []
@description('Deploy the apps (false on the first run, before images exist)')
param deployApps bool = true

var suffix = uniqueString(resourceGroup().id)
var tags = { project: 'matchcut', purpose: 'inside-the-game-hackathon' }

// ---------------------------------------------------------------- observability
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}-${suffix}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}-${suffix}'
  location: location
  kind: 'web'
  tags: tags
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id, DisableLocalAuth: false }
}

// ---------------------------------------------------------------- identity and registry
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
  tags: tags
}

// GitHub Actions releases as this identity through OpenID Connect: no client secret exists
resource releaser 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}-github'
  location: location
  tags: tags
}

resource releaserFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: releaser
  name: 'github-production'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepo}:environment:production'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${name}${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// ---------------------------------------------------------------- storage: the cut queue and films
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${name}${suffix}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource cutsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'cuts'
  properties: { publicAccess: 'None' }
}

// the showcase bundle: match data and the licensed animation library, which never go in git
resource showcaseContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'showcase'
  properties: { publicAccess: 'None' }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource cutsQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'cuts'
}

// ---------------------------------------------------------------- least-privilege roles for the identity
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  blobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  containerAppsContributor: '358470bc-b998-42bd-ab17-a7e34c199c0f'
  blobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  queueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  speechUser: 'f2dc8367-1007-4938-bd23-fe263f013447'
}

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryName
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, roles.acrPull)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull) }
}

resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.blobDataContributor)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataContributor) }
}

resource queueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.queueDataContributor)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.queueDataContributor) }
}

resource deployerBlobRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principal in deployerPrincipalIds: {
  scope: storage
  name: guid(storage.id, principal.id, roles.blobDataContributor)
  properties: { principalId: principal.id, principalType: principal.type, roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataContributor) }
}]

// the release identity: push images, read the showcase bundle, roll out new revisions
resource releasePush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, releaser.id, roles.acrPush)
  properties: { principalId: releaser.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush) }
}

resource releaseRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, releaser.id, roles.blobDataReader)
  properties: { principalId: releaser.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataReader) }
}

resource releaseApps 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, releaser.id, roles.containerAppsContributor)
  properties: { principalId: releaser.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.containerAppsContributor) }
}

resource modelRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, roles.openAiUser)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser) }
}

resource speechRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, roles.speechUser)
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.speechUser) }
}

// ---------------------------------------------------------------- Container Apps
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'cae-${name}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
    workloadProfiles: [ { name: 'Consumption', workloadProfileType: 'Consumption' } ]
  }
}

var commonEnv = [
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'MATCHCUT_STORAGE_ACCOUNT', value: storage.name }
  { name: 'AZURE_OPENAI_ENDPOINT', value: foundry.properties.endpoint }
  { name: 'AZURE_OPENAI_MODEL', value: modelDeployment }
  { name: 'AZURE_SPEECH_RESOURCE_ID', value: foundry.id }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
]

resource studio 'Microsoft.App/containerApps@2025-01-01' = if (deployApps) {
  name: 'ca-${name}-studio'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: true, targetPort: 8080, transport: 'auto', allowInsecure: false }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
      secrets: [
        { name: 'access-code-sha256', value: accessCodeSha256 }
        { name: 'session-secret', value: sessionSecret }
      ]
    }
    template: {
      containers: [
        {
          name: 'studio'
          image: '${registry.properties.loginServer}/matchcut-api:${apiImageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(commonEnv, [
            { name: 'MATCHCUT_ACCESS_CODE_SHA256', secretRef: 'access-code-sha256' }
            { name: 'MATCHCUT_SESSION_SECRET', secretRef: 'session-secret' }
          ])
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 10 }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2, rules: [ { name: 'http', http: { metadata: { concurrentRequests: '40' } } } ] }
    }
  }
  dependsOn: [ pull ]
}

resource recap 'Microsoft.App/jobs@2025-01-01' = if (deployApps) {
  name: 'caj-${name}-recap'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Event'
      replicaTimeout: 3600
      replicaRetryLimit: 0
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
      eventTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
        scale: {
          minExecutions: 0
          maxExecutions: 3
          pollingInterval: 15
          rules: [
            {
              name: 'cuts-queue'
              type: 'azure-queue'
              metadata: { accountName: storage.name, queueName: 'cuts', queueLength: '1' }
              identity: identity.id
            }
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: 'recap'
          image: '${registry.properties.loginServer}/matchcut-recap:${recapImageTag}'
          resources: { cpu: json('4'), memory: '8Gi' }
          env: concat(commonEnv, [ { name: 'MATCHCUT_FPS', value: '25' } ])
        }
      ]
    }
  }
  dependsOn: [ pull, queueRole, blobRole ]
}

output registry string = registry.properties.loginServer
output storageAccount string = storage.name
output studioUrl string = deployApps ? 'https://${studio!.properties.configuration.ingress.fqdn}' : ''
output identityClientId string = identity.properties.clientId
output releaseClientId string = releaser.properties.clientId
