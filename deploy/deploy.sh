#!/usr/bin/env bash
# Matchcut infrastructure, from a workstation with Owner rights on the resource group.
# Releases (image builds and new revisions) run in GitHub Actions: .github/workflows/deploy.yml.
#
#   set -a; . ../inside-the-game/.secrets/matchcut-prod.env; set +a
#   bash deploy/deploy.sh
#
# 1. Applies infra/main.bicep. The Studio app and the render job are included once their
#    images are in the registry (the first release pushes them), so the first run creates
#    the base and later runs create or update everything.
# 2. Publishes the showcase bundle (match data plus the licensed animation library, which
#    never go in git) to private Blob Storage, where the release workflow fetches it.
#
# Optional: MATCHCUT_RG (default rg-matchcut-dev), MATCHCUT_IMAGE_TAG (default: latest),
# MATCHCUT_SHOWCASE=skip to leave the bundle as it is.
set -euo pipefail

rg="${MATCHCUT_RG:-rg-matchcut-dev}"
export MATCHCUT_IMAGE_TAG="${MATCHCUT_IMAGE_TAG:-latest}"
: "${MATCHCUT_ACCESS_CODE_SHA256:?set the SHA-256 of the Studio access code}"
: "${MATCHCUT_SESSION_SECRET:?set the session signing key}"
bundle_paths=(out/feeds out/insights out/calls out/media apps/studio/assets/private)

step() { printf '\n== %s\n' "$*"; }
output() { az deployment group show -g "$rg" -n matchcut --query "properties.outputs.$1.value" -o tsv; }
has_image() { az acr manifest show-metadata -r "$1" -n "$2:$MATCHCUT_IMAGE_TAG" -o none 2>/dev/null; }

registry=$(output registry 2>/dev/null || true)
apps=false
if [ -n "$registry" ] && has_image "${registry%%.*}" matchcut-api && has_image "${registry%%.*}" matchcut-recap; then
  apps=true
fi

step "infrastructure (apps: $apps, images: $MATCHCUT_IMAGE_TAG)"
MATCHCUT_DEPLOY_APPS=$apps az deployment group create -g "$rg" -n matchcut -p infra/main.bicepparam -o none
storage=$(output storageAccount)

if [ "${MATCHCUT_SHOWCASE:-publish}" != skip ]; then
  step "showcase bundle"
  tar -czf showcase.tar.gz "${bundle_paths[@]}"
  az storage blob upload --auth-mode login --account-name "$storage" -c showcase -n showcase.tar.gz \
    -f showcase.tar.gz --overwrite -o none
  rm -f showcase.tar.gz
fi

step "release settings for GitHub (variables, not secrets: none of these grant access alone)"
echo "AZURE_CLIENT_ID=$(output releaseClientId)"
echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)"
echo "MATCHCUT_REGISTRY=$(output registry)"
echo "MATCHCUT_STORAGE=$storage"
echo "MATCHCUT_RG=$rg"

if [ "$apps" = true ]; then
  url=$(output studioUrl)
  step "smoke test $url"
  for _ in $(seq 1 30); do
    if curl -fsS "$url/healthz" >/dev/null 2>&1; then
      echo "live: $url"
      exit 0
    fi
    sleep 10
  done
  echo "the Studio did not answer at $url/healthz" >&2
  exit 1
fi
echo "base ready: run the Deploy workflow to build and push the images, then run this script again"
