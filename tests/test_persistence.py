import json
import os

import app as app_module


def _restart():
    """Simulate a process restart: reload state from disk and start in demo mode."""
    app_module._state = app_module._load_state()
    app_module._load_demo()


def _state_file():
    return app_module._state_path()


def test_decision_survives_restart(client):
    client.post("/api/datasets/ds-001/decision",
                json={"dataset_id": "ds-001", "decision": "retire", "notes": "Owner confirmed"})
    _restart()
    d = client.get("/api/datasets/ds-001").json()
    assert d["owner_decision"] == "retire"
    assert d["owner_decision_notes"] == "Owner confirmed"


def test_bpa_override_survives_restart(client):
    client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "model_size_gb": 12.5})
    _restart()
    assert client.get("/api/datasets/ds-001").json()["model_size_gb"] == 12.5


def test_cleared_decision_stays_cleared_after_restart(client):
    client.post("/api/datasets/ds-001/decision", json={"dataset_id": "ds-001", "decision": "migrate"})
    client.post("/api/datasets/ds-001/decision", json={"dataset_id": "ds-001", "decision": ""})
    _restart()
    assert client.get("/api/datasets/ds-001").json()["owner_decision"] is None


def test_reset_demo_clears_demo_but_keeps_live_state(client):
    # A live decision recorded earlier (live datasets are keyed by GUID)
    app_module._state["live"]["decisions"]["guid-1"] = {"decision": "migrate", "notes": "", "updated_at": "x"}
    client.post("/api/datasets/ds-001/decision", json={"dataset_id": "ds-001", "decision": "retire"})
    client.post("/api/reset-demo")
    _restart()
    assert client.get("/api/datasets/ds-001").json()["owner_decision"] is None
    assert app_module._state["live"]["decisions"]["guid-1"]["decision"] == "migrate"


def test_live_decisions_survive_reconnect(client, monkeypatch):
    from tests.test_pbi_client import _client
    monkeypatch.setattr(app_module, "PBIClient", lambda **kw: _client())
    creds = {"tenant_id": "t", "client_id": "c", "client_secret": "s"}
    client.post("/api/connect", json=creds)
    client.post("/api/datasets/d1/decision", json={"dataset_id": "d1", "decision": "fix_migrate"})
    client.post("/api/datasets/d1/bpa-update", json={"dataset_id": "d1", "active_users_30d": 40})
    _restart()                                   # back in demo mode after restart
    assert client.get("/api/status").json()["mode"] == "demo"
    client.post("/api/connect", json=creds)
    d = client.get("/api/datasets/d1").json()
    assert d["owner_decision"] == "fix_migrate"
    assert d["active_users_30d"] == 40


def test_file_is_valid_json_and_no_temp_left(client):
    client.post("/api/datasets/ds-001/decision", json={"dataset_id": "ds-001", "decision": "migrate"})
    path = _state_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["demo"]["decisions"]["ds-001"]["decision"] == "migrate"
    assert not os.path.exists(str(path) + ".tmp")


def test_corrupt_state_file_is_preserved_not_overwritten(client):
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    _restart()
    backups = list(path.parent.glob("state.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{ not json"
    # app still works with empty state
    assert client.get("/api/datasets/ds-001").json()["owner_decision"] is None


def test_missing_state_file_starts_empty(client):
    assert not _state_file().exists()
    assert client.get("/api/summary").status_code == 200
