def test_search_finds_by_dataset_name(client):
    r = client.get("/api/datasets/search", params={"q": "finance"})
    assert r.status_code == 200
    body = r.json()
    assert 1 <= len(body) <= 5
    assert all("finance" in (d["dataset_name"] + d["workspace_name"]).lower() for d in body)


def test_search_no_match_returns_404_with_message(client):
    r = client.get("/api/datasets/search", params={"q": "zzz-no-such-thing"})
    assert r.status_code == 404
    assert "No datasets matching" in r.json()["detail"]


def test_dataset_by_id_still_works(client):
    r = client.get("/api/datasets/ds-001")
    assert r.status_code == 200
    assert r.json()["dataset_id"] == "ds-001"
