from engine.demo_data import DEMO_DATASETS
from engine.scorer import (
    DatasetInput, MigrationDecision, ModelHealthInput, QueryPerformanceInput,
    RefreshEfficiencyInput, SizeComplexityInput, UsageInput, score_dataset,
)


def _healthy(**overrides) -> DatasetInput:
    """A fully measured dataset with no issues; override sections to add problems."""
    parts = dict(
        model_health=ModelHealthInput(bpa_critical_count=0),
        query_performance=QueryPerformanceInput(avg_query_duration_sec=1.0),
        refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=0.0),
        usage=UsageInput(active_users_30d=60, days_since_last_used=1),
        size_complexity=SizeComplexityInput(model_size_gb=1.0),
    )
    parts.update(overrides)
    return DatasetInput(dataset_id="x", dataset_name="x", **parts)


def test_baseline_healthy_is_migrate():
    r = score_dataset(_healthy())
    assert r.decision == MigrationDecision.MIGRATE
    assert r.blockers == []


def test_unused_for_90_days_is_retire_even_with_high_score():
    # Previously: 80 points, "Migrate as-is", Low risk
    r = score_dataset(_healthy(usage=UsageInput(active_users_30d=0, days_since_last_used=200)))
    assert r.total_score >= 80
    assert r.decision == MigrationDecision.RETIRE
    assert any("No active users" in b for b in r.blockers)


def test_zero_users_recently_used_is_capped_at_fix():
    r = score_dataset(_healthy(usage=UsageInput(active_users_30d=0, days_since_last_used=20)))
    assert r.decision == MigrationDecision.FIX_MIGRATE
    assert any("confirm" in b.lower() for b in r.blockers)


def test_circular_dependency_forces_major_refactor_and_high_risk():
    # Previously: 95 points, "Migrate as-is", Low risk
    r = score_dataset(_healthy(model_health=ModelHealthInput(has_circular_dependency=True)))
    assert r.decision == MigrationDecision.MAJOR_REFACTOR
    assert r.migration_risk == "High"
    assert any("Circular dependency" in b for b in r.blockers)


def test_high_refresh_failure_caps_at_fix_and_high_risk():
    r = score_dataset(_healthy(refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=35.0)))
    assert r.total_score >= 80
    assert r.decision == MigrationDecision.FIX_MIGRATE
    assert r.migration_risk == "High"


def test_blocker_never_improves_a_worse_decision():
    r = score_dataset(_healthy(
        model_health=ModelHealthInput(bpa_critical_count=10, bidirectional_rel_count=5, many_to_many_rel_count=3),
        query_performance=QueryPerformanceInput(avg_query_duration_sec=45, pct_queries_over_30s=50, iterator_measure_count=5),
        refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=35.0, avg_refresh_duration_min=200),
        usage=UsageInput(active_users_30d=2, days_since_last_used=1),
    ))
    assert r.total_score < 40
    assert r.decision == MigrationDecision.RETIRE  # score-based, not raised to FIX by the cap


def test_unused_and_circular_retires_rather_than_refactors():
    r = score_dataset(_healthy(model_health=ModelHealthInput(has_circular_dependency=True),
                               usage=UsageInput(active_users_30d=0, days_since_last_used=365)))
    assert r.decision == MigrationDecision.RETIRE


def test_unknown_last_used_with_zero_users_is_not_retired():
    r = score_dataset(_healthy(usage=UsageInput(active_users_30d=0)))
    assert r.decision == MigrationDecision.FIX_MIGRATE


def test_api_exposes_blockers(client):
    for ds in DEMO_DATASETS:
        d = client.get(f"/api/datasets/{ds.dataset_id}").json()
        assert isinstance(d["blockers"], list)
