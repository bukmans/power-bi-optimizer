from engine.demo_data import DEMO_DATASETS
from engine.scorer import (
    DatasetInput, MigrationDecision, ModelHealthInput, QueryPerformanceInput,
    RefreshEfficiencyInput, SizeComplexityInput, UsageInput, score_dataset,
)


def _dim(result, name):
    return next(d for d in result.dimensions if d.name == name)


def test_empty_input_is_not_scored_as_perfect():
    r = score_dataset(DatasetInput(dataset_id="x"))
    assert r.decision == MigrationDecision.NEEDS_ASSESSMENT
    assert r.data_coverage_pct == 0
    assert r.total_score == 0
    assert r.migration_risk == "Unknown"
    assert all(not d.measured for d in r.dimensions)


def test_live_mode_shape_refresh_only_needs_assessment():
    """What /api/connect produces before any enrichment: refresh history + report count."""
    r = score_dataset(DatasetInput(
        dataset_id="x",
        refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=0.0, avg_refresh_duration_min=5.0),
        usage=UsageInput(report_count=3, is_certified=False),
    ))
    assert r.decision == MigrationDecision.NEEDS_ASSESSMENT
    assert r.data_coverage_pct == 20
    assert set(r.unmeasured_dimensions) == {
        "Model Health", "Query Performance", "Usage & Business Value", "Size & Complexity"}
    # Report count alone must not count as measured usage
    assert not _dim(r, "Usage & Business Value").measured


def test_total_is_scaled_over_measured_dimensions():
    r = score_dataset(DatasetInput(
        dataset_id="x",
        model_health=ModelHealthInput(bpa_critical_count=0),   # 25/25
        usage=UsageInput(active_users_30d=50),                 # 20/20
        refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=25.0),  # 12/20
    ))
    assert r.data_coverage_pct == 65
    assert r.total_score == round((25 + 20 + 12) / 65 * 100, 1)
    assert r.decision != MigrationDecision.NEEDS_ASSESSMENT
    assert "Query Performance" in r.unmeasured_dimensions


def test_unmeasured_dimension_explains_how_to_measure():
    r = score_dataset(DatasetInput(dataset_id="x"))
    health = _dim(r, "Model Health")
    assert "enrich_scores.ipynb" in health.recommendations[0]


def test_partially_measured_dimension_treats_missing_fields_as_zero():
    r = score_dataset(DatasetInput(
        dataset_id="x",
        model_health=ModelHealthInput(bpa_critical_count=2),
        query_performance=QueryPerformanceInput(avg_query_duration_sec=1.0),
        refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=0.0),
        usage=UsageInput(active_users_30d=60),
        size_complexity=SizeComplexityInput(model_size_gb=1.0),
    ))
    assert r.data_coverage_pct == 100
    assert _dim(r, "Model Health").score == 19


def test_demo_data_fully_measured():
    for ds in DEMO_DATASETS:
        r = score_dataset(ds)
        assert r.data_coverage_pct == 100, ds.dataset_name
        assert r.decision != MigrationDecision.NEEDS_ASSESSMENT


def test_api_exposes_coverage_and_summary_count(client):
    d = client.get("/api/datasets/ds-001").json()
    assert d["data_coverage_pct"] == 100
    assert d["unmeasured_dimensions"] == []
    assert all(dim["measured"] for dim in d["dimensions"])
    s = client.get("/api/summary").json()
    assert s["needs_assessment"] == 0


def test_unknown_report_count_does_not_flag_no_reports():
    r = score_dataset(DatasetInput(dataset_id="x", usage=UsageInput(active_users_30d=10)))
    usage = _dim(r, "Usage & Business Value")
    assert not any("No reports" in i for i in usage.issues)
    r = score_dataset(DatasetInput(dataset_id="x", usage=UsageInput(active_users_30d=10, report_count=0)))
    assert any("No reports" in i for i in _dim(r, "Usage & Business Value").issues)


def test_last_used_alone_does_not_count_as_measured_usage():
    r = score_dataset(DatasetInput(dataset_id="x", usage=UsageInput(days_since_last_used=3)))
    assert not _dim(r, "Usage & Business Value").measured
