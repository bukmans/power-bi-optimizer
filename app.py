"""
Power BI Migration Optimizer – FastAPI Backend
Run:  python app.py
Then open:  http://localhost:8000
"""

import json
import os
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.scorer import score_dataset, DatasetInput, MigrationDecision
from engine.demo_data import DEMO_DATASETS
from engine.pbi_client import PBIClient

app = FastAPI(
    title="Power BI Migration Optimizer",
    version="1.0.0",
    description="Score Power BI semantic models for Microsoft Fabric migration readiness.",
)

# ── CORS — required for Copilot Studio custom connector ───────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://make.powerautomate.com", "https://copilotstudio.microsoft.com",
                   "https://*.azure-apim.net", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Key auth — used by the Copilot Studio custom connector ─────────────────
API_KEY = os.getenv("OPTIMIZER_API_KEY", "demo-key-change-in-production")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str = Security(api_key_header)):
    """Allow open access in demo mode; require key in live/production."""
    if API_KEY == "demo-key-change-in-production":
        return  # demo mode — no auth required
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

# ── In-memory state ────────────────────────────────────────────────────────────
_dataset_cache: dict[str, DatasetInput] = {}
_bpa_overrides: dict[str, dict] = {}  # dataset_id -> BPA metric overrides
_decisions: dict[str, str] = {}        # dataset_id -> owner decision override
_mode: str = "demo"  # "demo" or "live"


def _load_demo():
    global _dataset_cache, _mode
    _dataset_cache = {ds.dataset_id: ds for ds in DEMO_DATASETS}
    _mode = "demo"


_load_demo()


# ── Pydantic models ────────────────────────────────────────────────────────────
class ConnectionConfig(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str


class BPAUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}
    dataset_id: str
    bpa_critical_count: int = 0
    bpa_warning_count: int = 0
    bidirectional_rel_count: int = 0
    many_to_many_rel_count: int = 0
    high_cardinality_columns: int = 0
    has_circular_dependency: bool = False
    unused_columns_pct: float = 0.0
    avg_query_duration_sec: float = 0.0
    pct_queries_over_30s: float = 0.0
    iterator_measure_count: int = 0
    model_size_gb: float = 0.0
    table_count: int = 0
    column_count: int = 0
    active_users_30d: int = 0
    days_since_last_used: int = 0


class OwnerDecision(BaseModel):
    dataset_id: str
    decision: str  # "migrate" | "fix_migrate" | "retire"
    notes: str = ""


# ── Helper ────────────────────────────────────────────────────────────────────
def _score_all() -> list[dict]:
    results = []
    for ds_id, ds_inp in _dataset_cache.items():
        # Apply any BPA overrides posted via Semantic Link
        if ds_id in _bpa_overrides:
            ov = _bpa_overrides[ds_id]
            for k, v in ov.items():
                if hasattr(ds_inp.model_health, k):
                    setattr(ds_inp.model_health, k, v)
                if hasattr(ds_inp.query_performance, k):
                    setattr(ds_inp.query_performance, k, v)
                if hasattr(ds_inp.size_complexity, k):
                    setattr(ds_inp.size_complexity, k, v)
                if hasattr(ds_inp.usage, k):
                    setattr(ds_inp.usage, k, v)

        result = score_dataset(ds_inp)
        d = {
            "dataset_id": result.dataset_id,
            "dataset_name": result.dataset_name,
            "workspace_name": result.workspace_name,
            "owner": result.owner,
            "total_score": result.total_score,
            "decision": result.decision.value,
            "decision_color": result.decision_color,
            "migration_risk": result.migration_risk,
            "estimated_effort_days": result.estimated_effort_days,
            "model_size_gb": result.model_size_gb,
            "active_users_30d": result.active_users_30d,
            "last_modified": result.last_modified,
            "owner_decision": _decisions.get(ds_id),
            "dimensions": [
                {
                    "name": dim.name,
                    "score": dim.score,
                    "max_score": dim.max_score,
                    "pct": dim.pct,
                    "issues": dim.issues,
                    "recommendations": dim.recommendations,
                }
                for dim in result.dimensions
            ],
            "priority_fixes": result.priority_fixes,
        }
        results.append(d)

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results


# ── API Routes ─────────────────────────────────────────────────────────────────

@app.get("/api/status", dependencies=[Depends(require_api_key)])
def get_status():
    return {"mode": _mode, "dataset_count": len(_dataset_cache)}


@app.get("/api/datasets", dependencies=[Depends(require_api_key)])
def get_datasets(
    workspace: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    max_score: Optional[float] = Query(None),
):
    """Return all scored datasets with optional filters."""
    results = _score_all()

    if workspace:
        results = [r for r in results if workspace.lower() in r["workspace_name"].lower()]
    if decision:
        results = [r for r in results if decision.lower() in r["decision"].lower()]
    if min_score is not None:
        results = [r for r in results if r["total_score"] >= min_score]
    if max_score is not None:
        results = [r for r in results if r["total_score"] <= max_score]

    return results


@app.get("/api/datasets/{dataset_id}", dependencies=[Depends(require_api_key)])
def get_dataset(dataset_id: str):
    """Return full scoring detail for a single dataset."""
    if dataset_id not in _dataset_cache:
        raise HTTPException(status_code=404, detail="Dataset not found")
    result = score_dataset(_dataset_cache[dataset_id])
    return {
        "dataset_id": result.dataset_id,
        "dataset_name": result.dataset_name,
        "workspace_name": result.workspace_name,
        "owner": result.owner,
        "total_score": result.total_score,
        "decision": result.decision.value,
        "decision_color": result.decision_color,
        "migration_risk": result.migration_risk,
        "estimated_effort_days": result.estimated_effort_days,
        "model_size_gb": result.model_size_gb,
        "active_users_30d": result.active_users_30d,
        "owner_decision": _decisions.get(dataset_id),
        "dimensions": [
            {
                "name": dim.name,
                "score": dim.score,
                "max_score": dim.max_score,
                "pct": dim.pct,
                "issues": dim.issues,
                "recommendations": dim.recommendations,
            }
            for dim in result.dimensions
        ],
        "priority_fixes": result.priority_fixes,
    }


@app.get("/api/summary", dependencies=[Depends(require_api_key)])
def get_summary():
    """Return summary stats for the dashboard cards."""
    results = _score_all()
    total = len(results)
    migrate = sum(1 for r in results if "Migrate as-is" in r["decision"])
    fix = sum(1 for r in results if "Fix then" in r["decision"])
    refactor = sum(1 for r in results if "Major refactor" in r["decision"])
    retire = sum(1 for r in results if "decommission" in r["decision"])
    avg_score = round(sum(r["total_score"] for r in results) / total, 1) if total else 0

    # Effort distribution
    total_effort = sum(r["estimated_effort_days"] for r in results)

    # Workspace breakdown
    ws_counts: dict[str, int] = {}
    for r in results:
        ws_counts[r["workspace_name"]] = ws_counts.get(r["workspace_name"], 0) + 1

    return {
        "total": total,
        "migrate": migrate,
        "fix_migrate": fix,
        "major_refactor": refactor,
        "retire": retire,
        "avg_score": avg_score,
        "total_effort_days": total_effort,
        "workspaces": ws_counts,
        "mode": _mode,
        "high_risk": sum(1 for r in results if r["migration_risk"] == "High"),
    }


@app.post("/api/connect")
async def connect_to_pbi(config: ConnectionConfig):
    """Connect to Power BI REST API and load real datasets."""
    global _dataset_cache, _mode

    client = PBIClient(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
    )
    try:
        datasets = await client.fetch_all_datasets()
        if not datasets:
            raise HTTPException(status_code=400, detail="No datasets found. Check service principal workspace access.")
        _dataset_cache = {ds.dataset_id: ds for ds in datasets}
        _mode = "live"
        return {"status": "connected", "dataset_count": len(_dataset_cache)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/reset-demo")
def reset_demo():
    """Switch back to demo mode."""
    _load_demo()
    _bpa_overrides.clear()
    _decisions.clear()
    return {"status": "demo", "dataset_count": len(_dataset_cache)}


@app.post("/api/datasets/{dataset_id}/bpa-update", dependencies=[Depends(require_api_key)])
def update_bpa_metrics(dataset_id: str, update: BPAUpdate):
    """
    Accept BPA/memory/query metrics from a Semantic Link notebook or manual input.
    These override the defaults set during REST API discovery.
    """
    if dataset_id not in _dataset_cache:
        raise HTTPException(status_code=404, detail="Dataset not found")

    _bpa_overrides[dataset_id] = update.model_dump(exclude={"dataset_id"})
    return {"status": "updated", "dataset_id": dataset_id}


@app.post("/api/datasets/{dataset_id}/decision", dependencies=[Depends(require_api_key)])
def set_owner_decision(dataset_id: str, decision: OwnerDecision):
    """Record the owner's migration decision for a dataset."""
    if dataset_id not in _dataset_cache:
        raise HTTPException(status_code=404, detail="Dataset not found")
    _decisions[dataset_id] = decision.decision
    return {"status": "saved", "dataset_id": dataset_id, "decision": decision.decision}


@app.get("/api/workspaces", dependencies=[Depends(require_api_key)])
def get_workspaces():
    """Return distinct workspace names — used by the Copilot Studio agent menu."""
    results = _score_all()
    ws = sorted({r["workspace_name"] for r in results})
    return [{"workspace_name": w, "dataset_count": sum(1 for r in results if r["workspace_name"] == w)} for w in ws]


@app.get("/api/datasets/search", dependencies=[Depends(require_api_key)])
def search_datasets(q: str = Query(..., description="Partial dataset or workspace name")):
    """
    Fuzzy name search — called by the Copilot Studio agent when an analyst
    types a dataset name in conversation.
    Returns top 5 matches ranked by score descending.
    """
    results = _score_all()
    q_lower = q.lower()
    matches = [
        r for r in results
        if q_lower in r["dataset_name"].lower() or q_lower in r["workspace_name"].lower()
    ]
    matches = sorted(matches, key=lambda x: x["total_score"], reverse=True)[:5]
    if not matches:
        raise HTTPException(status_code=404, detail=f"No datasets matching '{q}' found.")
    return matches


@app.get("/api/export/csv")
def export_csv():
    """Export all scored datasets as CSV."""
    import csv
    import io

    results = _score_all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Dataset Name", "Workspace", "Owner", "Score", "Decision",
        "Risk", "Effort (days)", "Size (GB)", "Active Users (30d)",
        "Model Health %", "Query Perf %", "Refresh Eff %", "Usage %", "Size/Complexity %",
        "Owner Decision", "Top Fix 1", "Top Fix 2",
    ])

    for r in results:
        dims = {d["name"]: d["pct"] for d in r["dimensions"]}
        fixes = r["priority_fixes"]
        writer.writerow([
            r["dataset_name"], r["workspace_name"], r["owner"],
            r["total_score"], r["decision"], r["migration_risk"],
            r["estimated_effort_days"], r["model_size_gb"], r["active_users_30d"],
            dims.get("Model Health", ""),
            dims.get("Query Performance", ""),
            dims.get("Refresh Efficiency", ""),
            dims.get("Usage & Business Value", ""),
            dims.get("Size & Complexity", ""),
            r.get("owner_decision", ""),
            fixes[0] if len(fixes) > 0 else "",
            fixes[1] if len(fixes) > 1 else "",
        ])

    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=migration_readiness_report.csv"},
    )


# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  Power BI Migration Optimizer")
    print("  Open your browser: http://localhost:8000")
    print("=" * 60 + "\n")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
