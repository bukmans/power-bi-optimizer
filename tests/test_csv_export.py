import csv
import io

import app as app_module


def _rows(client):
    return list(csv.reader(io.StringIO(client.get("/api/export/csv").text)))


def test_formula_like_values_are_neutralised(client):
    ds = app_module._dataset_cache["ds-001"]
    ds.dataset_name = '=HYPERLINK("http://evil.example","click")'
    ds.owner = "@SUM(A1)"
    ds.workspace_name = "+cmd"
    rows = _rows(client)
    row = next(r for r in rows if "HYPERLINK" in r[0])
    assert row[0].startswith("'=") and row[1] == "'+cmd" and row[2] == "'@SUM(A1)"


def test_negative_numbers_and_normal_text_unchanged(client):
    rows = _rows(client)
    header, first = rows[0], rows[1]
    assert header[0] == "Dataset Name"
    assert not first[0].startswith("'")
    assert float(first[3]) >= 0  # Score stays numeric


def test_csv_has_one_row_per_dataset(client):
    assert len(_rows(client)) == 1 + len(app_module._dataset_cache)


def test_owner_notes_exported_and_neutralised(client):
    client.post("/api/datasets/ds-001/decision",
                json={"dataset_id": "ds-001", "decision": "retire", "notes": "=1+1 approved"})
    rows = _rows(client)
    notes_col = rows[0].index("Owner Notes")
    row = next(r for r in rows if r[0].startswith("Finance"))
    assert row[notes_col] == "'=1+1 approved"
