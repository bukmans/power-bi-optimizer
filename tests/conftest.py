import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402

TEST_API_KEY = "test-key-0123456789"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("OPTIMIZER_API_KEY", TEST_API_KEY)
    monkeypatch.delenv("OPTIMIZER_AUTH_DISABLED", raising=False)


@pytest.fixture
def client():
    """Authenticated client with fresh demo state for every test."""
    app_module._load_demo()
    app_module._bpa_overrides.clear()
    app_module._decisions.clear()
    return TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY})


@pytest.fixture
def anon_client():
    """Client that sends no API key."""
    return TestClient(app_module.app)
