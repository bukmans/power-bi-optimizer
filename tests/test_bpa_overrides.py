import app as app_module
from engine.demo_data import DEMO_DATASETS


def _detail(client, ds_id):
    return client.get(f"/api/datasets/{ds_id}").json()


def _list_entry(client, ds_id):
    return next(d for d in client.get("/api/datasets").json() if d["dataset_id"] == ds_id)


def test_partial_update_only_changes_posted_fields(client):
    before = _detail(client, "ds-001")
    r = client.post("/api/datasets/ds-001/bpa-update",
                    json={"dataset_id": "ds-001", "bpa_critical_count": 2})
    assert r.status_code == 200
    after = _detail(client, "ds-001")
    # Fields not posted must keep their original values
    assert after["model_size_gb"] == before["model_size_gb"]
    assert after["active_users_30d"] == before["active_users_30d"]
    health = next(d for d in after["dimensions"] if d["name"] == "Model Health")
    assert any("2 critical BPA" in i for i in health["issues"])


def test_successive_partial_updates_accumulate(client):
    client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "bpa_critical_count": 1})
    client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "model_size_gb": 12.0})
    d = _detail(client, "ds-001")
    assert d["model_size_gb"] == 12.0
    health = next(x for x in d["dimensions"] if x["name"] == "Model Health")
    assert any("1 critical BPA" in i for i in health["issues"])


def test_detail_and_list_agree_after_override(client):
    client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "bpa_critical_count": 4})
    assert _detail(client, "ds-001")["total_score"] == _list_entry(client, "ds-001")["total_score"]


def test_override_does_not_mutate_demo_source(client):
    original = DEMO_DATASETS[0].usage.active_users_30d
    client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "active_users_30d": 0})
    client.get("/api/datasets")
    assert DEMO_DATASETS[0].usage.active_users_30d == original


def test_reset_demo_restores_original_scores(client):
    baseline = _detail(client, "ds-001")
    client.post("/api/datasets/ds-001/bpa-update",
                json={"dataset_id": "ds-001", "active_users_30d": 0, "model_size_gb": 20})
    client.get("/api/summary")
    client.post("/api/reset-demo")
    assert _detail(client, "ds-001")["total_score"] == baseline["total_score"]
    assert app_module._bpa_overrides == {}


def test_negative_metrics_rejected(client):
    r = client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "bpa_critical_count": -1})
    assert r.status_code == 422


def test_explicit_null_is_ignored(client):
    before = _detail(client, "ds-001")["total_score"]
    r = client.post("/api/datasets/ds-001/bpa-update", json={"dataset_id": "ds-001", "model_size_gb": None})
    assert r.status_code == 200
    assert _detail(client, "ds-001")["total_score"] == before
