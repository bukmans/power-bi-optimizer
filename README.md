# Power BI Migration Optimizer

> **Score your Power BI assets for Microsoft Fabric migration readiness — before you move a single dataset.**

A self-hosted platform that analyses your Power BI semantic models and produces a **Migration Readiness Score (0–100)** per dataset, driving an automated decision: **Migrate as-is · Fix then migrate · Major refactor · Retire**.

Built for analytics and platform teams running Power BI → Microsoft Fabric migration programmes.

---

## Screenshots

| Dashboard | Dataset Detail |
|---|---|
| Summary cards, sortable dataset table, score bars | 5-dimension breakdown, issue list, priority fix list |

> Run `python app.py` and open `http://localhost:8000` to see the live dashboard with demo data.

---

## The Problem This Solves

Migrating Power BI to Fabric without pre-assessment risks **lifting and shifting inefficiency** — slow queries, broken refreshes, and oversized models that cost more on Fabric than they did on Power BI Premium.

This platform gives your team a **systematic, evidence-based way** to answer three questions before migration begins:

1. Is this dataset healthy enough to migrate as-is?
2. What specifically needs fixing, and in what priority order?
3. Is this dataset worth migrating at all, or should it be retired?

---

## Scoring Framework

Every dataset is scored across **five dimensions** (total 100 points):

### 1. Model Health — 25 pts
Measures the structural quality of the semantic model.

| Issue | Deduction |
|---|---|
| Critical BPA violation | −3 each (max −12) |
| BPA warning | −1 each (max −5) |
| Bidirectional relationship | −2 each (max −6) |
| Many-to-many relationship | −3 each (max −6) |
| High-cardinality column (>1M unique values) | −2 each (max −4) |
| Circular dependency | −5 (hard block) |
| >30% unused columns | −2 |

### 2. Query Performance — 25 pts
Measures how efficiently the model serves queries.

| Issue | Deduction |
|---|---|
| Avg query duration >30s | −10 |
| Avg query duration 10–30s | −6 |
| Avg query duration 5–10s | −3 |
| >20% of queries exceed 30s | −5 |
| Iterator-heavy measures (SUMX/AVERAGEX) | −2 each (max −6) |
| Slow visuals (>10s render) | −2 each (max −4) |
| DirectQuery mode | −2 |

### 3. Refresh Efficiency — 20 pts
Measures how reliably and efficiently the data refreshes.

| Issue | Deduction |
|---|---|
| Refresh failure rate >20% | −8 |
| Refresh failure rate 10–20% | −4 |
| Avg refresh duration >2 hrs | −5 |
| Full refresh on large table (>10M rows) | −5 |
| >4x/day refresh without incremental | −3 |
| Incremental refresh configured | +2 bonus |

### 4. Usage & Business Value — 20 pts
Measures how much the dataset is actually being used.

| Active users (30 days) | Score |
|---|---|
| ≥50 | 20 |
| 20–49 | 16 |
| 10–19 | 12 |
| 5–9 | 8 |
| 1–4 | 5 |
| 0 | 0 |

Modifiers: −5 if not accessed in >90 days · +2 if certified · +2 if >5 connected reports

### 5. Size & Complexity — 10 pts

| Issue | Deduction |
|---|---|
| Model size >10 GB | −5 |
| Model size >5 GB | −3 |
| Table count >50 | −3 |
| Column count >500 | −2 |

---

## Migration Decisions

| Score | Decision | What happens next |
|---|---|---|
| **80–100** | ✅ Migrate as-is | Add to migration sprint, no remediation needed |
| **60–79** | 🔧 Fix then migrate | Resolve priority fix list (typically 2–10 days), rescore |
| **40–59** | ⚠️ Major refactor | Significant model redesign required before migration |
| **0–39** | ❌ Consider decommission | Validate business need; likely retire |
| — | ❔ Needs assessment | Model Health or Usage has not been measured yet; run the enrichment notebook / post usage data, then rescore |

**Blockers override the score.** The final decision is never better than these floors, and each
one is listed in `blockers` (and in the dataset detail panel):

| Condition | Minimum decision | Risk |
|---|---|---|
| Circular dependency | Major refactor | High |
| Refresh failure rate > 20% | Fix then migrate | High |
| 0 active users (30d) and unused ≥ 90 days | Consider decommission | – |
| 0 active users (30d), recently used or last use unknown | Fix then migrate (confirm need) | – |

Metrics that have not been measured are **excluded** from the score rather than treated as perfect.
The total is scaled to 100 over the dimensions that were measured, and `data_coverage_pct` in the
API (and "x% data" in the dashboard) shows how many of the 100 points are backed by real data.

---

## Quick Start

### Prerequisites
- Python 3.10 or later
- `pip`

### Run in demo mode (no Power BI credentials needed)
```bash
git clone https://github.com/bukmans/power-bi-optimizer.git
cd power-bi-optimizer

pip install -r requirements.txt

python app.py
```

Open your browser at **http://localhost:8000**

`python app.py` listens on localhost only and, if `OPTIMIZER_API_KEY` is not set, runs without
API authentication. Any other way of running it (Docker, `uvicorn`, a non-localhost `HOST`)
requires `OPTIMIZER_API_KEY`; the dashboard then asks for the key once per browser tab and sends
it as the `X-API-Key` header.

The platform launches immediately with **10 realistic demo datasets** across 8 workspaces, covering all four migration decisions.

---

## Connecting to Real Power BI Data

### Step 1 — Register an Azure AD app

1. Go to [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**
2. Name it `pbi-migration-optimizer`, leave defaults, click **Register**
3. Copy the **Application (client) ID** and **Directory (tenant) ID** from the Overview page
4. Go to **Certificates & secrets** → **New client secret** → copy the secret **value** immediately

### Step 2 — Grant Power BI API permissions

1. In your app registration → **API permissions** → **Add a permission**
2. Select **Power BI Service** → **Application permissions**
3. Add these permissions:
   - `Dataset.Read.All`
   - `Workspace.Read.All`
   - `Report.Read.All`
4. Click **Grant admin consent**

### Step 3 — Enable service principal access in Power BI

1. Power BI Admin portal → **Tenant settings**
2. Under **Developer settings** → enable **"Allow service principals to use Power BI APIs"**
3. In each relevant workspace → **Access** → add your app as **Viewer** or **Member**

### Step 4 — Connect

**Option A: Via the UI**
Click **Connect to Power BI** in the top navigation bar and enter your credentials.

**Option B: Via environment variables**
```bash
cp .env.example .env
# Edit .env and fill in your values
python app.py
```

`.env` format:
```env
PBI_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_CLIENT_SECRET=your-secret-value
```

---

## Enriching Scores with Semantic Link (BPA + Memory)

The Power BI REST API provides refresh history and report counts. For full model health scores (BPA violations, memory usage, relationship analysis), run a **Semantic Link notebook** in Fabric and POST the results to the platform.

### Example Fabric Notebook

```python
# Install: pip install semantic-link semantic-link-labs
import sempy.fabric as spf
import requests

OPTIMIZER_URL = "http://your-server:8000"

# List all datasets in a workspace
datasets = spf.list_datasets()

for _, ds in datasets.iterrows():
    dataset_id = ds['Dataset Id']
    dataset_name = ds['Dataset Name']

    # Run BPA via semantic-link-labs
    # https://github.com/microsoft/semantic-link-labs
    try:
        import sempy_labs as labs
        bpa = labs.run_model_bpa(dataset=dataset_name, workspace=ds['Workspace Name'])
        critical = len(bpa[bpa['Severity'] == 'Error'])
        warnings = len(bpa[bpa['Severity'] == 'Warning'])
    except Exception:
        critical, warnings = 0, 0

    # Get model memory info
    try:
        mem = spf.evaluate_dax(
            dataset=dataset_name,
            dax_string="SELECT [DIMENSION_NAME],[USED_SIZE] FROM $SYSTEM.DISCOVER_STORAGE_TABLES"
        )
        model_size_gb = round(mem['USED_SIZE'].sum() / 1e9, 2)
        col_count = len(mem)
    except Exception:
        model_size_gb, col_count = 0.0, 0

    # Post enriched metrics to the optimizer
    payload = {
        "dataset_id": dataset_id,
        "bpa_critical_count": critical,
        "bpa_warning_count": warnings,
        "model_size_gb": model_size_gb,
        "column_count": col_count,
    }
    r = requests.post(f"{OPTIMIZER_URL}/api/datasets/{dataset_id}/bpa-update", json=payload)
    print(f"Updated {dataset_name}: {r.status_code}")
```

Save this as `notebooks/enrich_scores.ipynb` in your Fabric workspace and run it after connecting the platform to Power BI.

---

## GitHub Copilot Agent Skills

The `skills/` folder contains **five Markdown skill files** for use with GitHub Copilot in VS Code. These teach the AI agent your team's specific migration standards and analysis patterns.

| Skill file | What it does |
|---|---|
| `migration-readiness.md` | Score any dataset using the full 5-dimension framework |
| `semantic-model-audit.md` | Audit BPA violations, DAX quality, relationships, memory |
| `query-insights.md` | Analyse Fabric Query Insights telemetry, coach SQL rewrites |
| `capacity-metrics.md` | Analyse CU burn, throttling, recommend refresh windows |
| `retire-decision.md` | Evaluate retire vs migrate with ROI framework |

### Installing in VS Code (GitHub Copilot)

**Option 1: Reference a skill directly in Copilot Chat**
```
#file:skills/migration-readiness.md

Score this dataset:
- BPA: 2 critical, 5 warnings
- Avg query: 8.5s, 3 iterator measures
- Refresh: 8% failure, 40 min avg, full refresh on 5M row table
- Users: 29 active (30d)
- Size: 1.8 GB, 22 tables
```

**Option 2: Use as slash commands**
```bash
# Copy skills to .github/skills/ in any repo
mkdir -p .github/skills
cp skills/*.md .github/skills/

# Then use in Copilot Chat:
# /migration-readiness
# /semantic-model-audit
# /query-insights
```

**Option 3: Install via Copilot CLI**
```bash
copilot plugin install https://github.com/bukmans/power-bi-optimizer
```

---

## API Reference

The platform exposes a REST API for integration with Fabric notebooks, Power Automate flows, or your own tooling.

### Base URL
```
http://localhost:8000
```

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/status` | Mode (demo/live) and dataset count |
| `GET` | `/api/summary` | Aggregate counts, avg score, workspace breakdown |
| `GET` | `/api/datasets` | All scored datasets (supports query filters) |
| `GET` | `/api/datasets/{id}` | Full detail for one dataset |
| `POST` | `/api/datasets/{id}/bpa-update` | Post BPA/metric enrichment from Semantic Link |
| `POST` | `/api/datasets/{id}/decision` | Save owner migration decision |
| `POST` | `/api/connect` | Connect to Power BI REST API |
| `POST` | `/api/reset-demo` | Switch back to demo data |
| `GET` | `/api/export/csv` | Download full migration report as CSV |

### Filter parameters for `GET /api/datasets`

```http
GET /api/datasets?workspace=Finance Analytics
GET /api/datasets?decision=Fix then migrate
GET /api/datasets?min_score=60&max_score=79
GET /api/datasets?min_score=0&max_score=39
```

### POST `/api/datasets/{id}/bpa-update`

```json
{
  "dataset_id": "your-dataset-guid",
  "bpa_critical_count": 2,
  "bpa_warning_count": 5,
  "bidirectional_rel_count": 1,
  "many_to_many_rel_count": 0,
  "high_cardinality_columns": 2,
  "has_circular_dependency": false,
  "unused_columns_pct": 18.0,
  "avg_query_duration_sec": 8.5,
  "pct_queries_over_30s": 6.0,
  "iterator_measure_count": 3,
  "model_size_gb": 1.8,
  "table_count": 22,
  "column_count": 185,
  "active_users_30d": 29,
  "days_since_last_used": 5
}
```

### POST `/api/datasets/{id}/decision`

```json
{
  "dataset_id": "your-dataset-guid",
  "decision": "migrate",
  "notes": "Approved by Sarah Mitchell, Finance lead"
}
```

Valid `decision` values: `migrate` · `fix_migrate` · `retire`, or `""` to clear. `notes` is optional (max 2000 characters).

---

## Project Structure

```
power-bi-optimizer/
│
├── app.py                        # FastAPI app — entry point, all API routes
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment variable template
│
├── engine/
│   ├── scorer.py                 # Core scoring algorithm (5 dimensions, 0–100)
│   ├── pbi_client.py             # Power BI REST API client (MSAL service principal)
│   └── demo_data.py              # 10 realistic demo datasets (all 4 decision zones)
│
├── static/
│   └── index.html                # Full dashboard SPA — Tailwind CSS, no build step
│
├── skills/                       # GitHub Copilot agent skill files
│   ├── migration-readiness.md    # Full scoring framework
│   ├── semantic-model-audit.md   # BPA, DAX, relationships, memory
│   ├── query-insights.md         # Fabric Query Insights analysis + SQL coaching
│   ├── capacity-metrics.md       # CU burn, throttling, refresh scheduling
│   └── retire-decision.md        # Retire vs migrate ROI framework
│
└── notebooks/
    └── enrich_scores.ipynb       # Fabric notebook: run BPA + POST to optimizer
```

---

## Migration Programme Phases

This platform supports the three-phase migration approach:

### Phase A — Pre-Fabric Assessment (Weeks 1–4)
- Connect to Power BI workspaces
- Run BPA/memory analysis via Semantic Link notebooks
- Score all datasets, generate readiness reports
- Agree migration list with dataset owners
- **Deliverable:** Migration scorecard, retire list, fix backlog

### Phase B — Fabric Pilot (Weeks 5–8)
- Migrate "Migrate as-is" datasets first
- Activate Fabric Warehouse telemetry in pilot workspaces
- Use Query Insights + Capacity Metrics skills to coach post-migration optimisation
- **Deliverable:** CU baseline, latency comparison, capacity recommendations

### Phase C — Scale (Ongoing)
- Extend to remaining workspaces
- Use platform as quality gate — no dataset migrates without score ≥ 60
- Track CU savings and score improvements over time
- **Deliverable:** Continuous governance, decommission tracking

---

## Security

- **Every `/api` endpoint requires the `X-API-Key` header** (including connect, reset and CSV
  export). The app refuses to start without `OPTIMIZER_API_KEY`, except `python app.py` on
  localhost. Keys are compared in constant time; missing/invalid keys get `401`.
- `/healthz` is the only unauthenticated endpoint besides the dashboard page; it returns no data.
- The platform uses a **service principal with least-privilege** access (`Dataset.Read.All`, `Workspace.Read.All`)
- Credentials are stored only in your `.env` file — never committed to source control (`.gitignore` excludes it)
- No data leaves your environment — all scoring happens locally
- BPA metrics are posted from within Fabric notebook execution context (within service boundaries)
- Query Activity live view requires workspace admin access; snapshot-based approach is used by default

---

## KPIs to Track

| KPI | Source | Target |
|---|---|---|
| % datasets scoring ≥80 | Platform `/api/summary` | >50% after Phase A fixes |
| Average score improvement post-remediation | Platform trend | +15 pts avg |
| p95 query latency reduction | Fabric Query Insights | −30% on pilot workspaces |
| Refresh failures eliminated | Refresh history | <5% failure rate across fleet |
| CU per successful query (normalised) | Capacity Metrics App | Trending down month-on-month |
| Owner decision turnaround | Platform `/api/datasets` | <5 business days per dataset |

---

## RACI

| Role | Responsibility |
|---|---|
| **Platform / Analytics Team** | Run the platform, score datasets, deliver reports, enforce migration gates |
| **Dataset Owners** | Validate business criticality, approve fixes, decide retire/migrate |
| **IT / Capacity Admin** | Install Capacity Metrics App, provision service principal, grant workspace access |

---

## Contributing

Issues and pull requests are welcome. When contributing:

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Keep the scoring algorithm changes backward-compatible (existing scores should not regress without a version bump)
4. Update `engine/demo_data.py` if adding new test scenarios
5. Open a PR with a clear description of what changed and why

---

## Roadmap

- [ ] **Teams / email notifications** — alert dataset owners when their dataset is scored
- [ ] **Power Automate connector** — trigger rescoring when a dataset refresh completes
- [ ] **Capacity Metrics ingestion** — pull CU data directly from the Capacity Metrics App API
- [ ] **Trend history** — track score changes over time (SQLite persistence)
- [ ] **Score threshold configuration** — customise decision thresholds per organisation
- [ ] **Multi-tenant support** — score datasets across multiple Power BI tenants
- [ ] **Purview integration** — write migration decisions to Purview lineage

---

## Licence

MIT — see [LICENSE](LICENSE)

---

*Concept and programme design: Abraham Olagundoye*
