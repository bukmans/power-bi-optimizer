"""Keep the Copilot Studio connector, cards and topics in step with what the API returns."""
import json
from pathlib import Path

from engine.scorer import MigrationDecision

ROOT = Path(__file__).resolve().parent.parent / "copilot-studio"
SPEC = json.loads((ROOT / "custom-connector" / "openapi.json").read_text(encoding="utf-8"))


def test_decision_filter_values_match_real_decisions():
    param = next(p for p in SPEC["paths"]["/api/datasets"]["get"]["parameters"] if p["name"] == "decision")
    decisions = [d.value.lower() for d in MigrationDecision]
    for value in param["enum"]:
        # the API filters by case-insensitive substring
        assert any(value.lower() in d for d in decisions), value
    for d in MigrationDecision:
        assert any(v.lower() in d.value.lower() for v in param["enum"]), f"no filter value for {d.value}"


def test_no_stale_decision_labels_in_copilot_files():
    for f in ROOT.rglob("*"):
        if f.suffix in (".json", ".yaml"):
            assert "Major refactor needed" not in f.read_text(encoding="utf-8"), f


def test_score_card_colours_every_decision():
    card = (ROOT / "adaptive-cards" / "score-card.json").read_text(encoding="utf-8")
    for d in MigrationDecision:
        if d is not MigrationDecision.RETIRE:  # Retire is the 'Attention' fallback
            assert f"'{d.value}'" in card, d.value


def test_summary_schema_covers_api_fields(client):
    schema = set(SPEC["paths"]["/api/summary"]["get"]["responses"]["200"]["schema"]["properties"])
    missing = set(client.get("/api/summary").json()) - schema
    assert not missing, f"connector schema is missing summary fields: {missing}"


def test_dataset_schema_covers_api_fields(client):
    schema = set(SPEC["definitions"]["DatasetSummary"]["properties"])
    schema |= set(SPEC["definitions"]["DatasetDetail"]["allOf"][1]["properties"])
    missing = set(client.get("/api/datasets/ds-001").json()) - schema
    assert not missing, f"connector schema is missing dataset fields: {missing}"


def test_every_operation_documents_401():
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            assert "401" in op["responses"], f"{method.upper()} {path}"
