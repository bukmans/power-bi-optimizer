#!/usr/bin/env bash
# deploy/azure-setup.sh
# One-time Azure provisioning for Power BI Migration Optimizer. Safe to re-run: existing
# resources are kept, and an existing Container App is left untouched.
#
# Creates: resource group, container registry, storage account + file share (for
# owner decisions), Container Apps environment, and the Container App itself with its
# secrets, the /app/data mount and exactly one replica.
#
# Run it in Azure Cloud Shell (bash), or anywhere with Azure CLI and openssl, after
# "az login". Everything can be overridden with environment variables, e.g.
#
#   export LOCATION=eastus2 RESOURCE_GROUP=rg-pbi-optimizer
#   export PBI_TENANT_ID=... PBI_CLIENT_ID=... PBI_CLIENT_SECRET=...   # optional, see below
#   bash deploy/azure-setup.sh
#
# Without PBI_* the app runs on demo data; add the Power BI service principal later
# (see deploy/README.md, "Changing secrets").
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pbi-optimizer}"
LOCATION="${LOCATION:-eastus2}"
ACA_ENV="${ACA_ENV:-pbi-optimizer-env}"
APP_NAME="${APP_NAME:-power-bi-optimizer}"
SHARE_NAME="${SHARE_NAME:-optimizer-data}"
ENV_STORAGE_NAME="statedata"   # name of the share as registered on the environment
# Placeholder until the first GitHub Actions deploy pushes the real image
BOOTSTRAP_IMAGE="mcr.microsoft.com/k8se/quickstart:latest"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
# Registry and storage names must be globally unique: derive a stable suffix from the
# subscription and resource group so re-runs find the same resources.
SUFFIX=$(printf '%s' "$SUBSCRIPTION_ID/$RESOURCE_GROUP" | sha1sum | cut -c1-8)
ACR_NAME="${ACR_NAME:-pbiopt${SUFFIX}}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-pbiopt${SUFFIX}}"

echo "Subscription : $(az account show --query name -o tsv) ($SUBSCRIPTION_ID)"
echo "Location     : $LOCATION"
echo "Resource grp : $RESOURCE_GROUP"
echo "Registry     : $ACR_NAME"
echo "Storage      : $STORAGE_ACCOUNT / $SHARE_NAME"
echo "Container App: $APP_NAME in $ACA_ENV"
echo ""

# ── 0. Resource providers (needs subscription-level rights; an admin may do this) ─
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights Microsoft.Storage; do
  state=$(az provider show --namespace "$ns" --query registrationState -o tsv 2>/dev/null || echo Unknown)
  if [ "$state" != "Registered" ]; then
    echo "==> Registering provider $ns"
    az provider register --namespace "$ns" --wait \
      || { echo "!! Could not register $ns. Ask a subscription owner to register it, then re-run."; exit 1; }
  fi
done

# ── 1. Resource group ─────────────────────────────────────────────────────────
echo "==> Resource group $RESOURCE_GROUP"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none

# ── 2. Container registry ─────────────────────────────────────────────────────
# Admin credentials let the Container App pull images without a role assignment
# (which would need Owner / User Access Administrator on the resource group).
echo "==> Container registry $ACR_NAME"
if ! az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az acr create --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" \
    --sku Basic --admin-enabled true -o none
fi
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)

# ── 3. Storage for owner decisions and BPA overrides (/app/data/state.json) ────
echo "==> Storage account $STORAGE_ACCOUNT and file share $SHARE_NAME"
if ! az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az storage account create --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false -o none
fi
STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" --query "[0].value" -o tsv)
if [ "$(az storage share-rm exists --storage-account "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
        --name "$SHARE_NAME" --query exists -o tsv)" != "true" ]; then
  az storage share-rm create --storage-account "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --name "$SHARE_NAME" --quota 1 -o none
fi

# ── 4. Container Apps environment + the share registered on it ───────────────
echo "==> Container Apps environment $ACA_ENV"
if ! az containerapp env show --name "$ACA_ENV" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az containerapp env create --name "$ACA_ENV" --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" -o none
fi
az containerapp env storage set --name "$ACA_ENV" --resource-group "$RESOURCE_GROUP" \
  --storage-name "$ENV_STORAGE_NAME" --access-mode ReadWrite \
  --azure-file-account-name "$STORAGE_ACCOUNT" --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name "$SHARE_NAME" -o none
ENV_ID=$(az containerapp env show --name "$ACA_ENV" --resource-group "$RESOURCE_GROUP" --query id -o tsv)

# ── 5. Container App ──────────────────────────────────────────────────────────
if az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  echo "==> Container App $APP_NAME already exists: left unchanged"
  echo "    (to change secrets, see deploy/README.md, 'Changing secrets')"
  API_KEY_NOTE="unchanged (already set on the app)"
else
  echo "==> Creating Container App $APP_NAME"
  ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
  ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)
  OPTIMIZER_API_KEY="${OPTIMIZER_API_KEY:-$(openssl rand -hex 32)}"

  # Single-quoted YAML scalar: the only escape needed is doubling single quotes
  q() { local v=${1//\'/\'\'}; printf "'%s'" "$v"; }

  secrets="      - name: acr-password
        value: $(q "$ACR_PASSWORD")
      - name: optimizer-api-key
        value: $(q "$OPTIMIZER_API_KEY")"
  envvars="          - name: OPTIMIZER_API_KEY
            secretRef: optimizer-api-key"
  if [ -n "${PBI_TENANT_ID:-}" ] && [ -n "${PBI_CLIENT_ID:-}" ] && [ -n "${PBI_CLIENT_SECRET:-}" ]; then
    secrets+="
      - name: pbi-tenant-id
        value: $(q "$PBI_TENANT_ID")
      - name: pbi-client-id
        value: $(q "$PBI_CLIENT_ID")
      - name: pbi-client-secret
        value: $(q "$PBI_CLIENT_SECRET")"
    envvars+="
          - name: PBI_TENANT_ID
            secretRef: pbi-tenant-id
          - name: PBI_CLIENT_ID
            secretRef: pbi-client-id
          - name: PBI_CLIENT_SECRET
            secretRef: pbi-client-secret"
  else
    echo "    PBI_TENANT_ID / PBI_CLIENT_ID / PBI_CLIENT_SECRET not all set: app will start on demo data"
  fi

  # The spec holds secrets: keep it private and delete it however the script exits
  SPEC=$(mktemp)
  chmod 600 "$SPEC"
  trap 'rm -f "$SPEC"' EXIT
  cat > "$SPEC" <<YAML
location: $LOCATION
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      targetPort: 8000
      transport: auto
      allowInsecure: false
    registries:
      - server: $ACR_LOGIN_SERVER
        username: $ACR_USERNAME
        passwordSecretRef: acr-password
    secrets:
$secrets
  template:
    containers:
      - name: $APP_NAME
        image: $BOOTSTRAP_IMAGE
        resources:
          cpu: 0.5
          memory: 1Gi
        env:
$envvars
        volumeMounts:
          - volumeName: state
            mountPath: /app/data
    # The state file supports one writer, and in-memory datasets would differ between
    # replicas, so run exactly one (this also stops scale-to-zero resets).
    scale:
      minReplicas: 1
      maxReplicas: 1
    volumes:
      - name: state
        storageType: AzureFile
        storageName: $ENV_STORAGE_NAME
        # The image runs as appuser (uid 1000); SMB shares are root-owned by default
        mountOptions: "uid=1000,gid=1000,dir_mode=0750,file_mode=0640"
YAML
  az containerapp create --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --yaml "$SPEC" -o none
  API_KEY_NOTE="$OPTIMIZER_API_KEY"
fi

FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

cat <<EOF

============================================================
  Infrastructure ready.
============================================================

App URL (returns an error until the first GitHub Actions deploy replaces the placeholder image):
  https://$FQDN

Optimizer API key (store it in a password manager / Key Vault now; it is not shown again):
  $API_KEY_NOTE

GitHub repository VARIABLES (Settings > Secrets and variables > Actions > Variables):
  ACR_NAME        = $ACR_NAME
  RESOURCE_GROUP  = $RESOURCE_GROUP
  APP_NAME        = $APP_NAME

Next: create the GitHub deployment identity (needs rights to create app registrations
and assign roles on $RESOURCE_GROUP):
  GITHUB_REPO=<owner>/<repo> RESOURCE_GROUP=$RESOURCE_GROUP bash deploy/github-oidc-setup.sh
EOF
