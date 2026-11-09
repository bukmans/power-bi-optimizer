"""Live data is reloaded from the server's own credentials: on startup and via an empty /api/connect."""
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module
from conftest import TEST_API_KEY
from engine.pbi_client import PBIClient
from test_pbi_client import _mock_api


@pytest.fixture
def server_creds(monkeypatch):
    monkeypatch.setenv("PBI_TENANT_ID", "tenant")
    monkeypatch.setenv("PBI_CLIENT_ID", "client")
    monkeypatch.setenv("PBI_CLIENT_SECRET", "secret")


@pytest.fixture
def mock_pbi(monkeypatch):
    """Real PBIClient (so the PBI_* fallback is exercised) against a mocked Power BI API."""
    made = []

    def factory(**kw):
        c = PBIClient(transport=httpx.MockTransport(_mock_api), **kw)
        c._get_token = lambda: "token"
        made.append(c)
        return c
    monkeypatch.setattr(app_module, "PBIClient", factory)
    return made


def _wait_for_status(c, state, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = c.get("/api/status").json()
        if s["connection"]["state"] == state:
            return s
        time.sleep(0.05)
    raise AssertionError(f"connection never reached {state!r}: {s}")


# ── /api/connect with server credentials ─────────────────────────────────────
def test_empty_connect_uses_server_credentials(client, server_creds, mock_pbi):
    r = client.post("/api/connect")
    assert r.status_code == 200, r.text
    assert r.json()["dataset_count"] == 2
    assert mock_pbi[-1].client_secret == "secret"  # came from PBI_CLIENT_SECRET
    s = client.get("/api/status").json()
    assert s["mode"] == "live"
    assert s["server_credentials"] is True
    assert s["connection"]["state"] == "connected" and s["connection"]["source"] == "api"


def test_blank_fields_also_use_server_credentials(client, server_creds, mock_pbi):
    r = client.post("/api/connect", json={"tenant_id": " ", "client_id": "", "client_secret": ""})
    assert r.status_code == 200, r.text


def test_empty_connect_without_server_credentials_is_rejected(client, mock_pbi):
    r = client.post("/api/connect", json={})
    assert r.status_code == 400
    assert "PBI_TENANT_ID" in r.json()["detail"]
    assert client.get("/api/status").json()["mode"] == "demo"


def test_partial_credentials_are_rejected(client, server_creds, mock_pbi):
    r = client.post("/api/connect", json={"tenant_id": "t", "client_id": "c", "client_secret": ""})
    assert r.status_code == 422
    assert not mock_pbi  # never mixed with the server's secret


def test_failed_connect_is_reported_in_status(client, monkeypatch):
    class Broken:
        is_configured = False

        async def fetch_all_datasets(self):
            raise httpx.ConnectError("boom")
    monkeypatch.setattr(app_module, "PBIClient", lambda **kw: Broken())
    r = client.post("/api/connect", json={"tenant_id": "t", "client_id": "c", "client_secret": "s"})
    assert r.status_code == 400
    s = client.get("/api/status").json()
    assert s["mode"] == "demo"
    assert s["connection"]["state"] == "failed" and "boom" in s["connection"]["error"]


# ── Startup ──────────────────────────────────────────────────────────────────
def test_startup_loads_live_data_in_background(server_creds, mock_pbi):
    with TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY}) as c:
        assert c.get("/healthz").status_code == 200
        s = _wait_for_status(c, "connected")
        assert s["mode"] == "live" and s["dataset_count"] == 2
        assert s["connection"]["source"] == "startup"


def test_startup_failure_keeps_serving_demo(server_creds, monkeypatch):
    class Broken:
        is_configured = True

        async def fetch_all_datasets(self):
            raise RuntimeError("Token error: invalid client secret")
    monkeypatch.setattr(app_module, "PBIClient", lambda **kw: Broken())
    with TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY}) as c:
        s = _wait_for_status(c, "failed")
        assert s["mode"] == "demo"
        assert "invalid client secret" in s["connection"]["error"]
        assert c.get("/api/datasets").status_code == 200


def test_startup_without_credentials_stays_in_demo(mock_pbi):
    with TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY}) as c:
        s = c.get("/api/status").json()
    assert s["mode"] == "demo" and s["connection"]["state"] == "idle"
    assert s["server_credentials"] is False


def test_auto_connect_can_be_turned_off(server_creds, mock_pbi, monkeypatch):
    monkeypatch.setenv("OPTIMIZER_AUTO_CONNECT", "false")
    with TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY}) as c:
        s = c.get("/api/status").json()
    assert s["mode"] == "demo" and s["connection"]["state"] == "idle"
