def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json()["mode"] == "demo"


def test_datasets_listed(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    assert len(r.json()) == 10
