"""Run the enrichment notebook's own cells with Semantic Link stubbed and HTTP routed to the app.

This checks the notebook's payload logic and its use of the API, not the Semantic Link calls
themselves – those need a Fabric workspace.
"""
import json
import types
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import TEST_API_KEY

NOTEBOOK = Path(__file__).resolve().parent.parent / "notebooks" / "enrich_scores.ipynb"


def _cells():
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return {c["id"]: "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"}


class _Requests:
    """Minimal `requests` stand-in that forwards to the FastAPI TestClient."""
    class exceptions:
        ConnectionError = ConnectionError

    def __init__(self, client):
        self._c = client

    def post(self, url, json=None, headers=None, timeout=None):
        return self._c.post(url.replace("http://localhost:8000", ""), json=json, headers=headers or {})

    def get(self, url, headers=None, timeout=None):
        return self._c.get(url.replace("http://localhost:8000", ""), headers=headers or {})


def _fake_spf(fail_tables=False):
    def list_tables(dataset, workspace, extended=False):
        if fail_tables:
            raise RuntimeError("XMLA endpoint not enabled")
        return pd.DataFrame({"Name": ["Sales", "Date"], "Total Size": [3.0e9, 1.0e6]})

    def list_columns(dataset, workspace, extended=False):
        return pd.DataFrame({"Name": ["a", "b", "c"], "Cardinality": [5, 2_000_000, 10]})

    def list_relationships(dataset, workspace):
        return pd.DataFrame({"Cross Filtering Behavior": ["OneDirection", "BothDirections"],
                             "Multiplicity": ["m:1", "m:m"]})

    return types.SimpleNamespace(list_tables=list_tables, list_columns=list_columns,
                                 list_relationships=list_relationships)


def _run(anon_client, api_key, spf, has_labs=False):
    from fastapi.testclient import TestClient
    import app as app_module
    ns = {
        "requests": _Requests(TestClient(app_module.app)),
        "spf": spf, "pd": pd, "HAS_LABS": has_labs,
        "datasets_df": pd.DataFrame({"Dataset Id": ["ds-001"], "Dataset Name": ["Finance"]}),
    }
    cells = _cells()
    config = cells["config"].replace('os.environ.get("OPTIMIZER_API_KEY", "")', repr(api_key))
    for cid, src in (("config", config), ("audit", cells["audit"]), ("run_audit", cells["run_audit"])):
        exec(compile(src, f"notebook:{cid}", "exec"), ns)
    return ns["results"]


def test_notebook_posts_measured_metrics_with_key(client, anon_client):
    results = _run(anon_client, TEST_API_KEY, _fake_spf())
    assert results[0]["Status"] == "HTTP 200"
    d = client.get("/api/datasets/ds-001").json()
    assert d["model_size_gb"] == 3.0
    health = next(x for x in d["dimensions"] if x["name"] == "Model Health")
    assert any("bidirectional" in i for i in health["issues"])
    assert any("many-to-many" in i for i in health["issues"])
    assert any("high-cardinality" in i for i in health["issues"])


def test_failed_metrics_are_omitted_not_zeroed(client, anon_client):
    before = client.get("/api/datasets/ds-001").json()["model_size_gb"]
    _run(anon_client, TEST_API_KEY, _fake_spf(fail_tables=True))
    import app as app_module
    sent = app_module._bpa_overrides["ds-001"]
    assert "model_size_gb" not in sent and "table_count" not in sent
    assert client.get("/api/datasets/ds-001").json()["model_size_gb"] == before


def test_notebook_reports_missing_key(anon_client):
    results = _run(anon_client, "", _fake_spf())
    assert results[0]["Status"].startswith("401")
