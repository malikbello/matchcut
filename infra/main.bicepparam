using './main.bicep'

// Secrets come from the environment of whoever deploys (or the CI secret store), never from git.
param foundryName = readEnvironmentVariable('MATCHCUT_FOUNDRY_NAME', 'matchcut-ai-4e68')
param accessCodeSha256 = readEnvironmentVariable('MATCHCUT_ACCESS_CODE_SHA256')
param sessionSecret = readEnvironmentVariable('MATCHCUT_SESSION_SECRET')
param apiImageTag = readEnvironmentVariable('MATCHCUT_IMAGE_TAG', 'latest')
param recapImageTag = readEnvironmentVariable('MATCHCUT_IMAGE_TAG', 'latest')
param deployApps = bool(readEnvironmentVariable('MATCHCUT_DEPLOY_APPS', 'true'))
// JSON list of {"id": "<object id>", "type": "User" | "ServicePrincipal"}
param deployerPrincipalIds = json(readEnvironmentVariable('MATCHCUT_DEPLOYERS', '[]'))
// one warm Studio replica while the hackathon is judged (no cold start for a judge); 0 afterwards
param studioMinReplicas = int(readEnvironmentVariable('MATCHCUT_MIN_REPLICAS', '1'))
