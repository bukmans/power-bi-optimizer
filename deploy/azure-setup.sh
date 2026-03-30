#!/usr/bin/env bash
# deploy/azure-setup.sh
# One-time Azure infrastructure provisioning for Power BI Migration Optimizer.
# Prerequisites: Azure CLI installed and logged in ("az login").
# Usage: bash deploy/azure-setup.sh
set -e

# ── Variables ──────────────────────────────────────────────────────────────────
RESOURCE_GROUP="rg-pbi-optimizer"
LOCATION="uksouth"
# ACR names must be globally unique; append last 5 digits of current epoch time
ACR_NAME="pbioptimizer$(date +%s | tail -c 6)"
ACA_ENV="pbi-optimizer-env"
APP_NAME="power-bi-optimizer"

# ── 1. Resource Group ──────────────────────────────────────────────────────────
echo "==> Creating resource group: $RESOURCE_GROUP in $LOCATION"
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"

# ── 2. Azure Container Registry ───────────────────────────────────────────────
echo "==> Creating Azure Container Registry: $ACR_NAME (Basic SKU, admin enabled)"
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled true

# ── 3. Container Apps Environment ─────────────────────────────────────────────
echo "==> Creating Container Apps environment: $ACA_ENV"
az containerapp env create \
  --name "$ACA_ENV" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

# ── 4. Next steps ─────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Infrastructure provisioned successfully!"
echo "  Next step: Run the GitHub Actions workflow to build and"
echo "  deploy the application."
echo "============================================================"
echo ""

# ── 5. Print ACR login server ──────────────────────────────────────────────────
ACR_LOGIN_SERVER=$(az acr show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query loginServer \
  --output tsv)

ACR_USERNAME=$(az acr credential show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query username \
  --output tsv)

echo "Add the following as GitHub repository secrets:"
echo ""
echo "  REGISTRY_LOGIN_SERVER = $ACR_LOGIN_SERVER"
echo "  REGISTRY_USERNAME     = $ACR_USERNAME"
echo "  REGISTRY_PASSWORD     = <run: az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv>"
echo ""
echo "Also add your service principal and Power BI credentials:"
echo "  AZURE_CREDENTIALS     = <JSON from: az ad sp create-for-rbac --role contributor --scopes /subscriptions/<id>>"
echo "  PBI_TENANT_ID         = <your Entra tenant ID>"
echo "  PBI_CLIENT_ID         = <your service principal / app registration client ID>"
echo "  PBI_CLIENT_SECRET     = <your service principal client secret>"
