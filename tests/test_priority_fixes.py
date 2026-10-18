from engine.demo_data import DEMO_DATASETS
from engine.scorer import (
    DatasetInput, ModelHealthInput, QueryPerformanceInput, RefreshEfficiencyInput,
    SizeComplexityInput, UsageInput, score_dataset,
)


def _ds(**parts) -> DatasetInput:
    base = dict(
        model_health=ModelHealthInput(bpa_critical_count=0),
        query_performance=QueryPerformanceInput(avg_query_duration_sec=1.0),
        refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=0.0),
        usage=UsageInput(active_users_30d=60, days_since_last_used=1),
        size_complexity=SizeComplexityInput(model_size_gb=1.0),
    )
    base.update(parts)
    return DatasetInput(dataset_id="x", **base)


def test_ranked_by_points_lost_not_dimension_order():
    r = score_dataset(_ds(
        model_health=ModelHealthInput(bpa_warning_count=1),             # -1
        query_performance=QueryPerformanceInput(avg_query_duration_sec=45),  # -10
    ))
    assert r.priority_fixes[0].startswith("Profile slow queries")
    assert r.priority_fixes[-1].startswith("Address BPA warnings")


def test_informational_notes_are_not_fixes():
    r = score_dataset(_ds(refresh_efficiency=RefreshEfficiencyInput(
        refresh_failure_rate_pct=0.0, uses_incremental_refresh=True)))
    assert r.priority_fixes == []
    refresh = next(d for d in r.dimensions if d.name == "Refresh Efficiency")
    assert any("good practice" in rec for rec in refresh.recommendations)  # still shown in the panel


def test_blockers_come_first():
    r = score_dataset(_ds(model_health=ModelHealthInput(has_circular_dependency=True, bpa_critical_count=4)))
    assert r.priority_fixes[0].startswith("Circular dependency")


def test_capped_at_five_and_unique():
    for ds in DEMO_DATASETS:
        fixes = score_dataset(ds).priority_fixes
        assert len(fixes) <= 5
        assert len(fixes) == len(set(fixes))


def test_unmeasured_dimensions_suggest_measuring():
    r = score_dataset(DatasetInput(dataset_id="x", refresh_efficiency=RefreshEfficiencyInput(refresh_failure_rate_pct=0.0)))
    assert any("enrich_scores.ipynb" in f for f in r.priority_fixes)


def test_every_recommendation_has_a_weight():
    for ds in DEMO_DATASETS:
        for d in score_dataset(ds).dimensions:
            assert len(d.rec_points) == len(d.recommendations), d.name
