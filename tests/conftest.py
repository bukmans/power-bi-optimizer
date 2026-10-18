import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set before importing app: it loads persisted state at import time, and tests
# must never read or write the real data/state.json.
os.environ["OPTIMIZER_STATE_FILE"] = str(Path(tempfile.mkdtemp()) / "state.json")

import app as app_module  # noqa: E402

TEST_API_KEY = "test-key-0123456789"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPTIMIZER_API_KEY", TEST_API_KEY)
    monkeypatch.delenv("OPTIMIZER_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("OPTIMIZER_STATE_FILE", str(tmp_path / "state.json"))
    app_module._state = app_module._load_state()
    app_module._load_demo()


@pytest.fixture
def client():
    """Authenticated client with fresh demo state for every test."""
    return TestClient(app_module.app, headers={"X-API-Key": TEST_API_KEY})


@pytest.fixture
def anon_client():
    """Client that sends no API key."""
    return TestClient(app_module.app)
