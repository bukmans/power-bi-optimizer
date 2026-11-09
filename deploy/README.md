# Deployment Guide — Power BI Migration Optimizer

Three ways to run the app. Pick the one that fits your situation.

---

## Option A — Local with Docker

The fastest way to get running on your own machine.

```bash
git clone <your-repo-url>
cd power-bi-optimizer
docker compose up --build
```

Open your browser at **http://localhost:8000**.

The container needs an API key: copy `.env.example` to `.env` and set `OPTIMIZER_API_KEY`
(the container refuses to start without one). The dashboard asks for the key once per browser tab.

---

## Option B — Team Shared Server

Ideal for small teams where everyone needs the same URL.

1. SSH into a VM (Linux, any cloud or on-prem).
2. Install Docker and Docker Compose.
3. Clone the repo and run:

```bash
docker compose up -d --build
```

Colleagues just need the VM's IP or hostname — no local setup required.
The `restart: unless-stopped` policy means the app survives reboots automatically.

---

## Option C — Azure Container Apps (Production)

Every push to `main` is tested, built and deployed by GitHub Actions. The scripts below are
easiest to run in **Azure Cloud Shell** (bash), which already has Azure CLI and openssl:
portal.azure.com → Cloud Shell → Bash, then `git clone` this repo.

### What you need

| Who | Access |
|---|---|
| You | **Contributor** on the resource group (or on the subscription, to create it) |
| Subscription owner, once | Register the `Microsoft.App`, `Microsoft.ContainerRegistry`, `Microsoft.OperationalInsights` and `Microsoft.Storage` resource providers |
| Entra admin, or you with **Application Developer** | Create two app registrations: the Power BI reader and the GitHub deployer |
| Owner / User Access Administrator on the resource group | One role assignment for the GitHub deployer (Step 2) |
| Fabric administrator | Enable *Service principals can use Fabric APIs* for a security group with the reader app in it (main README, "Connecting to Real Power BI Data") |
| Workspace admins | Add the reader app to each workspace as **Viewer** |
| GitHub repo admin | Add Actions secrets and variables |

### Step 1 — Provision Azure (one time)

```bash
az login                       # not needed in Cloud Shell
export LOCATION=eastus2        # a region your organisation allows
# Optional now, or add later (see "Changing secrets"): the Power BI reader app
export PBI_TENANT_ID=... PBI_CLIENT_ID=... PBI_CLIENT_SECRET=...
bash deploy/azure-setup.sh
```

The script creates (and on re-runs, keeps):
- Resource group `rg-pbi-optimizer`
- Container registry (Basic)
- Storage account + file share, mounted at `/app/data`, so owner decisions and BPA results
  survive redeploys
- Container Apps environment
- The Container App itself: its secrets (API key, Power BI credentials, registry password),
  external HTTPS ingress on port 8000, and **exactly one replica** (the state file supports
  one writer, and it avoids scale-to-zero restarts)

It prints the **API key** once (save it in a password manager or Key Vault) and three
GitHub **variables**: `ACR_NAME`, `RESOURCE_GROUP`, `APP_NAME`.

The app runs a placeholder image until the first deploy in Step 3.

### Step 2 — GitHub deployment identity (one time)

```bash
GITHUB_REPO=<owner>/<repo> bash deploy/github-oidc-setup.sh
```

This creates an app registration that trusts GitHub's sign-in tokens for pushes to `main`
(OIDC: no password to store or rotate) and gives it **Contributor on the resource group
only**. It prints `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`.

In GitHub → **Settings → Secrets and variables → Actions**:
- **Secrets**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
- **Variables**: `ACR_NAME`, `RESOURCE_GROUP`, `APP_NAME`

If an admin creates the identity for you instead, they need: an app registration with a
federated credential (issuer `https://token.actions.githubusercontent.com`, subject
`repo:<owner>/<repo>:ref:refs/heads/main`, audience `api://AzureADTokenExchange`) and
Contributor on the resource group.

### Step 3 — Deploy

Push to `main`, or **Actions → Deploy to Azure Container Apps → Run workflow** on `main`.
The workflow runs the tests, builds the image, pushes it to the registry, points the
Container App at it and waits until the new revision answers `/healthz`.

The URL is printed in the workflow log and shown in the portal (Container App → Application URL).

### Step 4 — Check it

```bash
curl https://<app-url>/healthz
curl -H "X-API-Key: <key>" https://<app-url>/api/status
```

`/api/status` → `"mode": "live"` and `"connection": {"state": "connected"}` means Power BI
was read. `"failed"` includes the error (most often: the tenant setting is off, the app is
in no workspace, or the client secret is wrong or expired).

### Changing secrets

Container App secrets only reach the app on a new revision, so restart after changing them:

```bash
RG=rg-pbi-optimizer; APP=power-bi-optimizer
# Add or replace the Power BI reader credentials
az containerapp secret set -n $APP -g $RG --secrets   pbi-tenant-id=<tenant> pbi-client-id=<client> pbi-client-secret=<secret>
az containerapp update -n $APP -g $RG --set-env-vars   PBI_TENANT_ID=secretref:pbi-tenant-id PBI_CLIENT_ID=secretref:pbi-client-id   PBI_CLIENT_SECRET=secretref:pbi-client-secret
# Rotate the API key (then update the Copilot Studio connection and notebook secret)
az containerapp secret set -n $APP -g $RG --secrets optimizer-api-key=$(openssl rand -hex 32)
az containerapp revision restart -n $APP -g $RG   --revision $(az containerapp show -n $APP -g $RG --query properties.latestRevisionName -o tsv)
```

Client secrets expire (24 months at most): note the date and rotate before then.

### Logs

```bash
az containerapp logs show -n power-bi-optimizer -g rg-pbi-optimizer --follow
```

### Security notes

- The GitHub identity has Contributor on the optimizer's resource group only, and only
  workflows on `main` can sign in as it.
- The Power BI reader needs no Entra API permissions, and only **Viewer** on the workspaces
  it must read, never Admin.
- The registry uses its admin account so the Container App can pull without a role
  assignment. If your policies disable registry admin accounts, give the Container App a
  managed identity with **AcrPull** instead (`az containerapp registry set --identity system`).
- The storage account uses an account key for the file share mount (required by Container
  Apps for Azure Files). If shared-key access is blocked by policy, ask for an exemption
  for this account.

---

## Comparison

| | Local (Docker) | Shared Server | Azure Container Apps |
|---|---|---|---|
| Setup time | ~2 minutes | ~10 minutes | ~20 minutes (one-time) |
| Cost | Free | VM cost | Pay-per-use (often free tier) |
| Team access | You only | Anyone with VM URL | Anyone with the app URL |
| Auto-deploy | No | No | Yes (on push to main) |
| TLS / HTTPS | No | Manual | Automatic |
| Best for | Local dev / demos | Small team pilots | Production / shared rollout |
