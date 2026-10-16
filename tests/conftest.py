import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402


@pytest.fixture
def client():
    """Fresh demo state for every test."""
    app_module._load_demo()
    app_module._bpa_overrides.clear()
    app_module._decisions.clear()
    return TestClient(app_module.app)
