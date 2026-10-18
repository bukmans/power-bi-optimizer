import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app as app_module
from tests.conftest import TEST_API_KEY

API_ROUTES = sorted(
    (method, r.path)
    for r in app_module.app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")
    for method in r.methods
)


def _call(c: TestClient, method: str, path: str):
    path = path.replace("{dataset_id}", "ds-001")
    if method == "GET":
        return c.get(path, params={"q": "x"} if path.endswith("/search") else None)
    return c.post(path, json={})


@pytest.mark.parametrize("method,path", API_ROUTES)
def test_every_api_route_requires_key(anon_client, method, path):
    r = _call(anon_client, method, path)
    assert r.status_code == 401, f"{method} {path} is reachable without an API key"


@pytest.mark.parametrize("method,path", API_ROUTES)
def test_wrong_key_rejected(method, path):
    r = _call(TestClient(app_module.app, headers={"X-API-Key": "wrong"}), method, path)
    assert r.status_code == 401


def test_previously_open_routes_are_now_protected(anon_client):
    assert anon_client.get("/api/export/csv").status_code == 401
    assert anon_client.post("/api/reset-demo").status_code == 401
    assert anon_client.post("/api/connect", json={
        "tenant_id": "t", "client_id": "c", "client_secret": "s"}).status_code == 401


def test_valid_key_accepted(client):
    assert client.get("/api/status").status_code == 200


@pytest.mark.parametrize("placeholder", ["", "demo-key-change-in-production"])
def test_missing_or_placeholder_key_fails_closed(anon_client, monkeypatch, placeholder):
    monkeypatch.setenv("OPTIMIZER_API_KEY", placeholder)
    r = anon_client.get("/api/datasets")
    assert r.status_code == 503
    # and the old placeholder can't be used as a key
    r = TestClient(app_module.app, headers={"X-API-Key": "demo-key-change-in-production"}).get("/api/datasets")
    assert r.status_code == 503


def test_startup_refuses_without_key(monkeypatch):
    monkeypatch.delenv("OPTIMIZER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPTIMIZER_API_KEY"):
        with TestClient(app_module.app):
            pass


def test_startup_ok_with_key():
    with TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY}) as c:
        assert c.get("/api/status").status_code == 200


def test_explicitly_disabled_auth_allows_anonymous(anon_client, monkeypatch):
    monkeypatch.delenv("OPTIMIZER_API_KEY", raising=False)
    monkeypatch.setenv("OPTIMIZER_AUTH_DISABLED", "true")
    assert anon_client.get("/api/status").status_code == 200


def test_healthz_is_open_and_returns_no_data(anon_client):
    r = anon_client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_dashboard_page_loads_without_key(anon_client):
    assert anon_client.get("/").status_code == 200


@pytest.mark.parametrize("origin,allowed", [
    ("https://copilotstudio.microsoft.com", True),
    ("https://emea-01.azure-apim.net", True),
    ("https://evil.example.com", False),
    ("https://azure-apim.net.evil.com", False),
])
def test_cors(anon_client, origin, allowed):
    r = anon_client.options("/api/status", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-API-Key"})
    assert (r.headers.get("access-control-allow-origin") == origin) is allowed
    assert "access-control-allow-credentials" not in r.headers
