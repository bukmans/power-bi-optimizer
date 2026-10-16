"""
Power BI Migration Optimizer – FastAPI Backend
Run:  python app.py
Then open:  http://localhost:8000
"""

import copy
import json
import os
import secrets
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.scorer import score_dataset, DatasetInput, MigrationDecision
from engine.demo_data import DEMO_DATASETS
from engine.pbi_client import PBIClient

# ── API Key auth — used by the dashboard and the Copilot Studio custom connector ─
# Fails closed: every /api route needs X-API-Key unless auth is explicitly disabled
# (OPTIMIZER_AUTH_DISABLED=true – only for a local, loopback-only run).
_PLACEHOLDER_KEYS = {"", "demo-key-change-in-production", "change-me"}
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configured_api_key() -> Optional[str]:
    key = os.getenv("OPTIMIZER_API_KEY", "").strip()
    return None if key in _PLACEHOLDER_KEYS else key


def _auth_disabled() -> bool:
    return os.getenv("OPTIMIZER_AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")


def check_auth_config() -> None:
    """Refuse to start without a real API key, unless auth was explicitly disabled."""
    if not _auth_disabled() and _configured_api_key() is None:
        raise RuntimeError(
            "OPTIMIZER_API_KEY is not set (or is a placeholder). Set a strong random key, "
            "e.g. python -c \"import secrets; print(secrets.token_urlsafe(32))\". "
            "For a local-only run, use `python app.py`, which binds to 127.0.0.1."
        )


def require_api_key(key: Optional[str] = Security(api_key_header)):
    if _auth_disabled():
        return
    expected = _configured_api_key()
    if expected is None:
        raise HTTPException(status_code=503, detail="Server API key is not configured")
    if not key or not secrets.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key",
                            headers={"WWW-Authenticate": "ApiKey"})


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    check_auth_config()
    yield


app = FastAPI(
    title="Power BI Migration Optimizer",
    version="1.0.0",
    description="Score Power BI semantic models for Microsoft Fabric migration readiness.",
    lifespan=_lifespan,
)

# ── CORS — required for Copilot Studio custom connector ───────────────────────
# Auth is a header, not a cookie, so credentials are not needed. Wildcard
# subdomains must go in allow_origin_regex; allow_origins only matches exactly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://make.powerautomate.com", "https://copilotstudio.microsoft.com",
                   "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_origin_regex=r"https://[a-z0-9-]+\.azure-apim\.net",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# ── State ──────────────────────────────────────────────────────────────────────
# Owner decisions and BPA overrides are persisted to a JSON file so they survive
# restarts and redeploys. Demo and live data are kept apart, so resetting the demo
# never touches decisions recorded against real datasets. The dataset list itself
# is not persisted: it is re-read from Power BI on connect.
_DEFAULT_STATE_FILE = Path(__file__).parent / "data" / "state.json"
_MODES = ("demo", "live")
_state_lock = threading.Lock()


def _state_path() -> Path:
    return Path(os.getenv("OPTIMIZER_STATE_FILE") or _DEFAULT_STATE_FILE)


def _load_state() -> dict:
    path = _state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state file is not a JSON object")
    except FileNotFoundError:
        data = {}
    except (ValueError, OSError) as e:
        # Keep the unreadable file for inspection instead of overwriting it on the next save
        backup = path.with_name(f"{path.name}.corrupt-{datetime.now():%Y%m%d%H%M%S}")
        try:
            path.replace(backup)
        except OSError:
            pass
        print(f"  ! Could not read {path} ({e}); moved to {backup.name}, starting with empty state",
              file=sys.stderr)
        data = {}
    for mode in _MODES:
        section = data.setdefault(mode, {})
        section.setdefault("overrides", {})   # dataset_id -> BPA metric overrides
        section.setdefault("decisions", {})   # dataset_id -> {"decision", "notes", "updated_at"}
    return data


def _save_state() -> None:
    """Write atomically (temp file + rename) so a crash never leaves a half-written file."""
    path = _state_path()
    with _state_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(_state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)


_state: dict = _load_state()
_dataset_cache: dict[str, DatasetInput] = {}
_bpa_overrides: dict[str, dict] = {}
_decisions: dict[str, dict] = {}
_mode: str = "demo"  # "demo" or "live"


def _use_mode(mode: str) -> None:
    """Point the working dicts at the persisted state for this mode."""
    global _mode, _bpa_overrides, _decisions
    _mode = mode
    _bpa_overrides = _state[mode]["overrides"]
    _decisions = _state[mode]["decisions"]


def _load_demo():
    global _dataset_cache
    # Deep copy so nothing done at runtime can alter the module-level demo data
    _dataset_cache = {ds.dataset_id: copy.deepcopy(ds) for ds in DEMO_DATASETS}
    _use_mode("demo")


_load_demo()


# ── Pydantic models ────────────────────────────────────────────────────────────
class ConnectionConfig(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str


class BPAUpdate(BaseModel):
    """Partial update: only fields present in the request body are applied."""
    model_config = {"protected_namespaces": ()}
    dataset_id: str
    bpa_critical_count: Optional[int] = Field(None, ge=0)
    bpa_warning_count: Optional[int] = Field(None, ge=0)
    bidirectional_rel_count: Optional[int] = Field(None, ge=0)
    many_to_many_rel_count: Optional[int] = Field(None, ge=0)
    high_cardinality_columns: Optional[int] = Field(None, ge=0)
    has_circular_dependency: Optional[bool] = None
    unused_columns_pct: Optional[float] = Field(None, ge=0, le=100)
    avg_query_duration_sec: Optional[float] = Field(None, ge=0)
    pct_queries_over_30s: Optional[float] = Field(None, ge=0, le=100)
    iterator_measure_count: Optional[int] = Field(None, ge=0)
    model_size_gb: Optional[float] = Field(None, ge=0)
    table_count: Optional[int] = Field(None, ge=0)
    column_count: Optional[int] = Field(None, ge=0)
    active_users_30d: Optional[int] = Field(None, ge=0)
    days_since_last_used: Optional[int] = Field(None, ge=0)


class OwnerDecision(BaseModel):
    dataset_id: str
    # "" clears a previously recorded decision (the dashboard's "Pending" option)
    decision: Literal["migrate", "fix_migrate", "retire", ""]
    notes: str = Field("", max_length=2000)


# ── Helper ────────────────────────────────────────────────────────────────────
def _effective_input(ds_id: str) -> DatasetInput:
    """Cached dataset with any BPA overrides applied, on a copy so the cache is never mutated."""
    ds_inp = copy.deepcopy(_dataset_cache[ds_id])
    for k, v in _bpa_overrides.get(ds_id, {}).items():
        for section in (ds_inp.model_health, ds_inp.query_performance,
                        ds_inp.size_complexity, ds_inp.usage):
            if hasattr(section, k):
                setattr(section, k, v)
    return ds_inp


def _score_one(ds_id: str) -> dict:
    result = score_dataset(_effective_input(ds_id))
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
        "last_modified": result.last_modified,
        "owner_decision": _decisions.get(ds_id, {}).get("decision"),
        "owner_decision_notes": _decisions.get(ds_id, {}).get("notes"),
        "dimensions": [
            {
                "name": dim.name,
                "score": dim.score,
                "max_score": dim.max_score,
                "pct": dim.pct,
                "issues": dim.issues,
                "recommendations": dim.recommendations,
                "measured": dim.measured,
            }
            for dim in result.dimensions
        ],
        "priority_fixes": result.priority_fixes,
        "data_coverage_pct": result.data_coverage_pct,
        "unmeasured_dimensions": result.unmeasured_dimensions,
        "blockers": result.blockers,
    }


def _score_all() -> list[dict]:
    results = [_score_one(ds_id) for ds_id in _dataset_cache]
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


# Must be declared before /api/datasets/{dataset_id}, otherwise "search" is
# captured as a dataset_id and every search returns 404.
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


@app.get("/api/datasets/{dataset_id}", dependencies=[Depends(require_api_key)])
def get_dataset(dataset_id: str):
    """Return full scoring detail for a single dataset."""
    if dataset_id not in _dataset_cache:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return _score_one(dataset_id)


@app.get("/api/summary", dependencies=[Depends(require_api_key)])
def get_summary():
    """Return summary stats for the dashboard cards."""
    results = _score_all()
    total = len(results)
    migrate = sum(1 for r in results if "Migrate as-is" in r["decision"])
    fix = sum(1 for r in results if "Fix then" in r["decision"])
    refactor = sum(1 for r in results if "Major refactor" in r["decision"])
    retire = sum(1 for r in results if "decommission" in r["decision"])
    needs_assessment = sum(1 for r in results if r["decision"] == MigrationDecision.NEEDS_ASSESSMENT.value)
    # Average only over datasets with enough data for a decision
    assessed = [r for r in results if r["decision"] != MigrationDecision.NEEDS_ASSESSMENT.value]
    avg_score = round(sum(r["total_score"] for r in assessed) / len(assessed), 1) if assessed else 0

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
        "needs_assessment": needs_assessment,
        "avg_score": avg_score,
        "total_effort_days": total_effort,
        "workspaces": ws_counts,
        "mode": _mode,
        "high_risk": sum(1 for r in results if r["migration_risk"] == "High"),
    }


@app.post("/api/connect", dependencies=[Depends(require_api_key)])
async def connect_to_pbi(config: ConnectionConfig):
    """Connect to Power BI REST API and load real datasets."""
    global _dataset_cache

    client = PBIClient(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
    )
    try:
        datasets = await client.fetch_all_datasets()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not load datasets from Power BI: {e}")
    if not datasets:
        raise HTTPException(status_code=400, detail="No datasets found. Check service principal workspace access.")
    _dataset_cache = {ds.dataset_id: ds for ds in datasets}
    _use_mode("live")  # live decisions/overrides persist across reconnects (keyed by dataset GUID)
    return {"status": "connected", "dataset_count": len(_dataset_cache)}


@app.post("/api/reset-demo", dependencies=[Depends(require_api_key)])
def reset_demo():
    """Switch back to demo mode and clear demo decisions/overrides (live ones are kept)."""
    _load_demo()
    _bpa_overrides.clear()
    _decisions.clear()
    _save_state()
    return {"status": "demo", "dataset_count": len(_dataset_cache)}


@app.post("/api/datasets/{dataset_id}/bpa-update", dependencies=[Depends(require_api_key)])
def update_bpa_metrics(dataset_id: str, update: BPAUpdate):
    """
    Accept BPA/memory/query metrics from a Semantic Link notebook or manual input.
    These override the defaults set during REST API discovery.
    """
    if dataset_id not in _dataset_cache:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Merge only the fields the caller actually sent, so a notebook posting just
    # BPA counts does not reset usage, size or query metrics to zero.
    changes = update.model_dump(exclude={"dataset_id"}, exclude_unset=True, exclude_none=True)
    _bpa_overrides.setdefault(dataset_id, {}).update(changes)
    _save_state()
    return {"status": "updated", "dataset_id": dataset_id, "fields_updated": sorted(changes)}


@app.post("/api/datasets/{dataset_id}/decision", dependencies=[Depends(require_api_key)])
def set_owner_decision(dataset_id: str, decision: OwnerDecision):
    """Record the owner's migration decision for a dataset."""
    if dataset_id not in _dataset_cache:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if decision.dataset_id != dataset_id:
        raise HTTPException(status_code=422, detail="dataset_id in body does not match the URL")
    if decision.decision == "":
        _decisions.pop(dataset_id, None)
        _save_state()
        return {"status": "cleared", "dataset_id": dataset_id, "decision": None}
    _decisions[dataset_id] = {
        "decision": decision.decision,
        "notes": decision.notes,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save_state()
    return {"status": "saved", "dataset_id": dataset_id, "decision": decision.decision}


@app.get("/api/workspaces", dependencies=[Depends(require_api_key)])
def get_workspaces():
    """Return distinct workspace names — used by the Copilot Studio agent menu."""
    results = _score_all()
    ws = sorted({r["workspace_name"] for r in results})
    return [{"workspace_name": w, "dataset_count": sum(1 for r in results if r["workspace_name"] == w)} for w in ws]


@app.get("/api/export/csv", dependencies=[Depends(require_api_key)])
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
        "Model Health %", "Query Perf %", "Refresh Eff %", "Usage %", "Size/Complexity %", "Data Coverage %",
        "Owner Decision", "Blockers", "Top Fix 1", "Top Fix 2",
    ])

    for r in results:
        dims = {d["name"]: (d["pct"] if d["measured"] else "Not measured") for d in r["dimensions"]}
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
            r["data_coverage_pct"],
            r["owner_decision"] or "",
            "; ".join(r["blockers"]),
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
@app.get("/healthz")
def healthz():
    """Unauthenticated liveness probe for Docker / Container Apps. Returns no data."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    if _configured_api_key() is None and not _auth_disabled():
        if host not in ("127.0.0.1", "localhost", "::1"):
            sys.exit(f"Refusing to listen on {host} without OPTIMIZER_API_KEY. "
                     "Set the key, or run on 127.0.0.1 for local use.")
        # Local, loopback-only convenience run: no key needed
        os.environ["OPTIMIZER_AUTH_DISABLED"] = "true"
        print("  ! No OPTIMIZER_API_KEY set: API auth disabled (listening on localhost only)")
    print("\n" + "=" * 60)
    print("  Power BI Migration Optimizer")
    print(f"  Open your browser: http://{host}:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("app:app", host=host, port=port, reload=True)
