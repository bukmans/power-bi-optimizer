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

Full CI/CD: every push to `main` builds and deploys automatically.

### Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) installed
- An active Azure subscription
- A GitHub repository with Actions enabled

### Step 1 — Provision Azure infrastructure (one time)

```bash
az login
bash deploy/azure-setup.sh
```

The script creates:
- A Resource Group (`rg-pbi-optimizer`)
- An Azure Container Registry (Basic SKU)
- A Container Apps Environment

At the end it prints the values you need for the next step.

### Step 2 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**.

| Secret name | Where to find it |
|---|---|
| `AZURE_CREDENTIALS` | `az ad sp create-for-rbac --role contributor --scopes /subscriptions/<id> --sdk-auth` |
| `REGISTRY_LOGIN_SERVER` | Printed by azure-setup.sh (e.g. `pbioptimizer12345.azurecr.io`) |
| `REGISTRY_USERNAME` | Printed by azure-setup.sh (ACR admin username) |
| `REGISTRY_PASSWORD` | `az acr credential show --name <acr-name> --query passwords[0].value -o tsv` |
| `PBI_TENANT_ID` | Azure portal → Microsoft Entra ID → Overview → Tenant ID |
| `PBI_CLIENT_ID` | Azure portal → App registrations → your app → Application (client) ID |
| `PBI_CLIENT_SECRET` | Azure portal → App registrations → your app → Certificates & secrets |

Then set the API key as a Container App secret (the app refuses to start without it):

```bash
az containerapp secret set --name power-bi-optimizer --resource-group rg-pbi-optimizer   --secrets optimizer-api-key=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

### Step 3 — Deploy

Push any commit to `main` (or trigger manually via **Actions → Run workflow**).

GitHub Actions will:
1. Build the Docker image and push it to ACR (tagged with git SHA and `latest`).
2. Deploy the new image to Azure Container Apps with external ingress on port 8000.

The public URL is shown in the Azure portal under Container Apps → your app → Application URL.

### Security note

The service principal created in Step 2 should follow least-privilege. Grant it only
`Contributor` on the specific resource group (`rg-pbi-optimizer`), not on the whole
subscription. The Power BI service principal needs only `Viewer` access to the
workspaces it must read — never `Admin`.

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
