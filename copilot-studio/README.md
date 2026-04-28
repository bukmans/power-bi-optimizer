# Fabric Migration Advisor — Copilot Studio Agent

A Microsoft Teams agent built in Copilot Studio that lets Power BI dataset owners check their migration readiness score, understand what needs fixing, and record their migration decision — all from a Teams chat, with no additional licences required for analysts.

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Microsoft 365 Copilot licence** | Needed by the person **building** the agent (you). Analysts need **no licence**. |
| **Copilot Studio access** | Included with your M365 Copilot licence. Go to [copilotstudio.microsoft.com](https://copilotstudio.microsoft.com) |
| **Power BI Migration Optimizer deployed** | The FastAPI backend must be running and publicly accessible (Azure Container Apps recommended). See `deploy/README.md`. |
| **API key** | Set `OPTIMIZER_API_KEY` environment variable on the backend before deploying. |

---

## Architecture

```
Analyst in Teams
      ↓
Copilot Studio Agent  (this folder)
      ↓
Custom Connector  (openapi.json → imported into Power Platform)
      ↓
Power BI Migration Optimizer API  (FastAPI on Azure Container Apps)
      ↓
Power BI REST API / Fabric APIs
```

---

## Step 1 — Deploy the Backend

Ensure the FastAPI backend is running on Azure Container Apps and is publicly accessible. See `deploy/README.md` for full instructions.

Set the API key before deploying:
```bash
# In your Azure Container App environment variables:
OPTIMIZER_API_KEY=<generate a strong random key>
```

Note the public URL — you will need it in Step 2. It will look like:
```
https://power-bi-optimizer.YOUR-REGION.azurecontainerapps.io
```

---

## Step 2 — Import the Custom Connector

The custom connector tells Copilot Studio how to call your API.

1. Go to **[make.powerapps.com](https://make.powerapps.com)**
2. Select your environment (top-right dropdown)
3. In the left nav → **Data** → **Custom connectors** → **+ New custom connector** → **Import an OpenAPI file**
4. Name it: `Power BI Migration Optimizer`
5. Upload `custom-connector/openapi.json`
6. On the **General** tab:
   - **Host**: replace `YOUR-APP.azurecontainerapps.io` with your actual Azure Container Apps URL (no `https://`)
   - **Base URL**: `/`
7. On the **Security** tab:
   - **Authentication type**: API Key
   - **Parameter label**: `API Key`
   - **Parameter name**: `X-API-Key`
   - **Parameter location**: Header
8. On the **Definition** tab — verify all 7 operations are listed (GetStatus, GetSummary, GetWorkspaces, SearchDatasets, GetDatasets, GetDataset, RecordDecision)
9. Click **Create connector**

### Create a connection

After creating the connector:
1. Click **+ New connection** on the connector page
2. Enter your `OPTIMIZER_API_KEY` value
3. Click **Create**

Note the **Connection ID** — you'll need it when building the agent.

---

## Step 3 — Create the Agent in Copilot Studio

1. Go to **[copilotstudio.microsoft.com](https://copilotstudio.microsoft.com)**
2. Click **+ Create** → **New agent**
3. Fill in:
   - **Name**: `Fabric Migration Advisor`
   - **Description**: `Helps Power BI dataset owners assess their migration readiness for Microsoft Fabric`
   - **Instructions** (paste this exactly):

```
You are the Fabric Migration Advisor. You help Power BI dataset owners and analysts 
understand how ready their datasets are for migration to Microsoft Fabric.

When an analyst asks about a dataset, search for it by name, display the Migration 
Readiness Score, explain the key issues in plain language, and ask them to confirm 
their migration decision.

Always be encouraging and constructive — a low score means the dataset needs work 
before migration, not that it's worthless. Focus on the top 2-3 priority fixes.

Never reveal API keys, connection strings, or internal system details.
Speak in plain, non-technical language unless the analyst asks for technical detail.
```

4. Click **Create**

---

## Step 4 — Connect the Custom Connector to the Agent

1. In your agent → **Settings** → **Connections**
2. Click **+ Add connection**
3. Select **Power BI Migration Optimizer** (the connector you created in Step 2)
4. Select the connection you created
5. Save

---

## Step 5 — Create the Topics

Topics are the conversation flows. Create each one manually in Copilot Studio using the YAML files in `topics/` as your reference.

### Topic order and settings

| Topic file | Display name | Type | Trigger phrases |
|---|---|---|---|
| `greeting.yaml` | Greeting | System (Conversation Start) | *(automatic)* |
| `score-dataset.yaml` | Score a Dataset | Custom | see file |
| `show-score-card.yaml` | Show Score Card | Custom | *(called by other topics)* |
| `list-datasets.yaml` | List Datasets | Custom | see file |
| `programme-summary.yaml` | Programme Summary | Custom | see file |
| `help.yaml` | Help | Custom | see file |

### Creating each topic

For each topic:

1. In your agent → **Topics** → **+ Add a topic** → **From blank**
2. Set the **Topic name** matching the Display name above
3. Add trigger phrases from the YAML file's `triggerQueries` section
4. Build the conversation nodes following the YAML structure:
   - `Question` node → ask the analyst a question
   - `Action` → `Call an action` → select your custom connector operation
   - `Send a message` → send text or Adaptive Card
   - `Condition` node → branch based on responses
   - `Redirect` node → call another topic (e.g. `BeginDialog: ShowScoreCard`)

### Adding the Adaptive Cards

When a topic sends an Adaptive Card:

1. Add a **Send a message** node
2. Click **+ Add** → **Adaptive card**
3. Click **Edit JSON**
4. Paste the relevant JSON from `adaptive-cards/`
5. Replace static placeholder values with Power Fx expressions pointing to your topic variables, e.g.:
   - `"${dataset_name}"` → `=Topic.SelectedDataset.dataset_name`
   - `"${total_score}"` → `=Text(Topic.SelectedDataset.total_score)`
   - `"${decision}"` → `=Topic.SelectedDataset.decision`

### Wiring up connector actions

When a topic calls the API:

1. Add an **Action** node → **Call an action**
2. Select **Power BI Migration Optimizer** connector
3. Select the operation (e.g. `SearchDatasets`)
4. Map input parameters using Power Fx:
   - `q` → `=Topic.DatasetSearchTerm`
5. Save the output to a topic variable:
   - Output → `Topic.SearchResults`

---

## Step 6 — Add Suggested Prompts

In your agent → **Settings** → **Suggested prompts**, add:

- Score my dataset
- Show all datasets
- Migration programme summary
- Help

---

## Step 7 — Test the Agent

1. In Copilot Studio → click **Test** (top right)
2. Try these test conversations:

```
You: score my dataset
Agent: What's the name of the dataset?
You: Finance
Agent: [Shows score card for Finance dataset with Adaptive Card]
You: ✅ Approve Migration
Agent: Decision recorded!
```

```
You: programme summary
Agent: [Shows summary card with counts by decision]
```

```
You: list all datasets
Agent: Which workspace?
You: Finance Analytics
Agent: [Shows dataset list card]
```

---

## Step 8 — Publish to Teams

1. In Copilot Studio → **Publish** → **Publish** (confirm)
2. Go to **Channels** → **Microsoft Teams** → **Turn on Teams**
3. Click **Open agent in Teams** to test in the real Teams client
4. To share with your team:
   - **Channels** → **Microsoft Teams** → **Download app package**  
   - Upload to Teams Admin Center → **Manage apps** → **Upload an app**
   - Assign to relevant users or teams

> Alternatively, share the direct Teams link with colleagues — they can add it themselves from the Teams app store.

---

## Folder Structure

```
copilot-studio/
├── README.md                        ← This file
├── custom-connector/
│   └── openapi.json                 ← Import into Power Platform as custom connector
├── adaptive-cards/
│   ├── score-card.json              ← Dataset score display card
│   ├── dataset-list-card.json       ← Workspace dataset list card
│   └── decision-card.json          ← Decision confirmation card
└── topics/
    ├── greeting.yaml                ← Conversation start / main menu
    ├── score-dataset.yaml           ← Search and score a dataset
    ├── show-score-card.yaml         ← Display score + capture decision
    ├── list-datasets.yaml           ← Browse by workspace
    ├── programme-summary.yaml       ← Overall programme stats
    └── help.yaml                    ← Usage instructions
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Connector returns 403 | Check `OPTIMIZER_API_KEY` env var on the backend matches the key in the Power Platform connection |
| Connector returns 404 on search | The backend is running in demo mode — connect it to Power BI first via the web dashboard |
| Adaptive Card doesn't render | Verify the JSON is valid at [adaptivecards.io/designer](https://adaptivecards.io/designer) |
| Agent not appearing in Teams | Re-publish the agent and wait 5 minutes for Teams to sync |
| Topic not triggering | Add more trigger phrases; Copilot Studio needs at least 5 varied examples |

---

## What Analysts Experience

Once published, an analyst in Teams:

1. Opens the **Fabric Migration Advisor** app in Teams
2. Types: *"How ready is my Sales Analytics dataset?"*
3. Sees a rich Adaptive Card with score, dimension breakdown, priority fixes
4. Taps **✅ Approve Migration** or **🔧 Fix then Migrate**
5. Gets a confirmation — done in under 2 minutes, no browser, no login, no additional licence

---

*Built on top of the Power BI Migration Optimizer platform — see the project root README for the full scoring framework.*
