import pytest


def _post(client, decision, notes=None, ds="ds-001"):
    body = {"dataset_id": ds, "decision": decision}
    if notes is not None:
        body["notes"] = notes
    return client.post(f"/api/datasets/{ds}/decision", json=body)


@pytest.mark.parametrize("decision", ["migrate", "fix_migrate", "retire"])
def test_valid_decisions_saved(client, decision):
    assert _post(client, decision).status_code == 200
    assert client.get("/api/datasets/ds-001").json()["owner_decision"] == decision


@pytest.mark.parametrize("bad", ["yes", "MIGRATE", "delete everything", "<script>"])
def test_invalid_decision_rejected(client, bad):
    assert _post(client, bad).status_code == 422
    assert client.get("/api/datasets/ds-001").json()["owner_decision"] is None


def test_notes_are_kept(client):
    _post(client, "migrate", notes="Approved by Finance lead")
    d = client.get("/api/datasets/ds-001").json()
    assert d["owner_decision_notes"] == "Approved by Finance lead"


def test_empty_decision_clears(client):
    _post(client, "retire", notes="x")
    assert _post(client, "").status_code == 200
    d = client.get("/api/datasets/ds-001").json()
    assert d["owner_decision"] is None
    assert d["owner_decision_notes"] is None


def test_body_dataset_id_must_match_path(client):
    r = client.post("/api/datasets/ds-001/decision", json={"dataset_id": "ds-002", "decision": "migrate"})
    assert r.status_code == 422


def test_notes_length_limited(client):
    assert _post(client, "migrate", notes="x" * 2001).status_code == 422


def test_csv_includes_owner_decision(client):
    _post(client, "retire")
    csv = client.get("/api/export/csv").text
    line = next(l for l in csv.splitlines() if l.startswith("Finance"))
    assert ",retire," in line
