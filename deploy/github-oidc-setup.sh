#!/usr/bin/env bash
# deploy/github-oidc-setup.sh
# Creates the identity GitHub Actions uses to deploy, with no stored password: an Entra
# app registration that trusts tokens GitHub issues for pushes to one branch (OIDC
# federated credential), with Contributor on the optimizer's resource group only.
#
# Needs: rights to create app registrations (or the Application Developer role), and
# Owner / User Access Administrator / Role Based Access Control Administrator on the
# resource group. Run after deploy/azure-setup.sh. Safe to re-run.
#
#   GITHUB_REPO=owner/repo bash deploy/github-oidc-setup.sh
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:?Set GITHUB_REPO=owner/repo}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pbi-optimizer}"
APP_DISPLAY_NAME="${APP_DISPLAY_NAME:-github-deploy-power-bi-optimizer}"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
RG_ID=$(az group show --name "$RESOURCE_GROUP" --query id -o tsv)

echo "==> App registration $APP_DISPLAY_NAME"
CLIENT_ID=$(az ad app list --display-name "$APP_DISPLAY_NAME" --query "[0].appId" -o tsv)
if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID=$(az ad app create --display-name "$APP_DISPLAY_NAME" --query appId -o tsv)
fi
if [ -z "$(az ad sp list --filter "appId eq '$CLIENT_ID'" --query "[0].id" -o tsv)" ]; then
  az ad sp create --id "$CLIENT_ID" -o none
fi

echo "==> Federated credential for $GITHUB_REPO on branch $GITHUB_BRANCH"
CRED_NAME="github-${GITHUB_BRANCH//[^A-Za-z0-9-]/-}"
if [ -z "$(az ad app federated-credential list --id "$CLIENT_ID" --query "[?name=='$CRED_NAME'].name" -o tsv)" ]; then
  az ad app federated-credential create --id "$CLIENT_ID" --parameters "{
    \"name\": \"$CRED_NAME\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:$GITHUB_REPO:ref:refs/heads/$GITHUB_BRANCH\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" -o none
fi

echo "==> Contributor on $RESOURCE_GROUP (push images to the registry, update the Container App)"
# A new service principal can take a few seconds to be visible to role assignments
for attempt in 1 2 3 4 5 6; do
  if az role assignment create --assignee "$CLIENT_ID" --role Contributor --scope "$RG_ID" -o none 2>/dev/null; then
    break
  fi
  [ "$attempt" = 6 ] && { echo "!! Role assignment failed: do you have Owner or User Access Administrator on $RESOURCE_GROUP?"; exit 1; }
  sleep 10
done

cat <<EOF

============================================================
  Deployment identity ready.
============================================================

GitHub repository SECRETS (Settings > Secrets and variables > Actions > Secrets).
These are identifiers, not passwords:
  AZURE_CLIENT_ID        = $CLIENT_ID
  AZURE_TENANT_ID        = $TENANT_ID
  AZURE_SUBSCRIPTION_ID  = $SUBSCRIPTION_ID

Then push to $GITHUB_BRANCH, or run the workflow from the Actions tab.
EOF
