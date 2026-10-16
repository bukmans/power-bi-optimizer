"""
Migration Readiness Scoring Engine
Scores Power BI datasets 0-100 across five dimensions to determine
whether they should be migrated as-is, fixed then migrated, or retired.
"""

from dataclasses import dataclass, field, fields, replace
from typing import Optional
from enum import Enum


class MigrationDecision(str, Enum):
    MIGRATE = "Migrate as-is"
    FIX_MIGRATE = "Fix then migrate"
    MAJOR_REFACTOR = "Major refactor required"
    RETIRE = "Consider decommission"
    NEEDS_ASSESSMENT = "Needs assessment"


# Every metric below defaults to None, meaning "not measured". A dimension with no
# measured metrics is excluded from the total rather than scored as perfect.
@dataclass
class ModelHealthInput:
    bpa_critical_count: Optional[int] = None        # Critical BPA rule violations
    bpa_warning_count: Optional[int] = None         # Warning BPA rule violations
    bidirectional_rel_count: Optional[int] = None   # Bidirectional relationships
    many_to_many_rel_count: Optional[int] = None    # Many-to-many relationships
    high_cardinality_columns: Optional[int] = None  # Columns with >1M unique values
    has_circular_dependency: Optional[bool] = None
    unused_columns_pct: Optional[float] = None    # % of unused columns


@dataclass
class QueryPerformanceInput:
    avg_query_duration_sec: Optional[float] = None   # Average query duration in seconds
    pct_queries_over_30s: Optional[float] = None     # % of queries exceeding 30s
    iterator_measure_count: Optional[int] = None       # SUMX/AVERAGEX/FILTER iterators
    slow_visual_count: Optional[int] = None            # Visuals with >10s render time
    direct_query_mode: Optional[bool] = None       # Is DirectQuery (vs Import)


@dataclass
class RefreshEfficiencyInput:
    refresh_failure_rate_pct: Optional[float] = None   # % of refreshes that failed (last 30 days)
    avg_refresh_duration_min: Optional[float] = None   # Average refresh time in minutes
    uses_incremental_refresh: Optional[bool] = None   # Has incremental refresh configured
    refresh_frequency_per_day: Optional[float] = None  # How many times refreshed per day
    largest_table_row_count: Optional[int] = None        # Row count of largest table
    full_refresh_on_large_table: Optional[bool] = None  # Full refresh on table >10M rows


@dataclass
class UsageInput:
    active_users_30d: Optional[int] = None         # Unique users in last 30 days
    report_count: Optional[int] = None             # Number of reports connected
    days_since_last_used: Optional[int] = None     # Days since any user accessed
    is_certified: Optional[bool] = None        # Has been certified/endorsed
    is_shared_externally: Optional[bool] = None # Shared outside the org


@dataclass
class SizeComplexityInput:
    model_size_gb: Optional[float] = None        # Dataset size in GB
    table_count: Optional[int] = None              # Number of tables
    column_count: Optional[int] = None             # Total columns across all tables
    measure_count: Optional[int] = None            # Number of measures
    relationship_count: Optional[int] = None       # Total relationships


@dataclass
class DatasetInput:
    dataset_id: str = ""
    dataset_name: str = ""
    workspace_id: str = ""
    workspace_name: str = ""
    model_health: ModelHealthInput = field(default_factory=ModelHealthInput)
    query_performance: QueryPerformanceInput = field(default_factory=QueryPerformanceInput)
    refresh_efficiency: RefreshEfficiencyInput = field(default_factory=RefreshEfficiencyInput)
    usage: UsageInput = field(default_factory=UsageInput)
    size_complexity: SizeComplexityInput = field(default_factory=SizeComplexityInput)
    owner: str = ""
    created_date: Optional[str] = None
    last_modified: Optional[str] = None


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    pct: float
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    measured: bool = True


@dataclass
class ScoringResult:
    dataset_id: str
    dataset_name: str
    workspace_name: str
    owner: str
    total_score: float
    decision: MigrationDecision
    decision_color: str
    dimensions: list[DimensionScore]
    priority_fixes: list[str]
    estimated_effort_days: int
    migration_risk: str  # Low / Medium / High
    last_modified: Optional[str] = None
    created_date: Optional[str] = None
    model_size_gb: Optional[float] = None
    active_users_30d: Optional[int] = None
    data_coverage_pct: float = 100.0              # share of the 100 points backed by real data
    unmeasured_dimensions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)  # conditions that overrode the score


def _is_measured(inp, keys: Optional[tuple[str, ...]] = None) -> bool:
    names = keys or tuple(f.name for f in fields(inp))
    return any(getattr(inp, n) is not None for n in names)


def _filled(inp):
    """Copy of an input section with unmeasured (None) metrics read as zero / False."""
    return replace(inp, **{
        f.name: (False if f.type == Optional[bool] else 0)
        for f in fields(inp) if getattr(inp, f.name) is None
    })


def _clamp(value: float, min_val: float = 0.0, max_val: float = None) -> float:
    if max_val is not None:
        return max(min_val, min(max_val, value))
    return max(min_val, value)


def score_model_health(inp: ModelHealthInput) -> DimensionScore:
    """Score model health out of 25."""
    inp = _filled(inp)
    MAX = 25.0
    score = MAX
    issues = []
    recommendations = []

    # BPA critical violations (-3 each, max -12)
    critical_penalty = min(inp.bpa_critical_count * 3, 12)
    if inp.bpa_critical_count > 0:
        score -= critical_penalty
        issues.append(f"{inp.bpa_critical_count} critical BPA rule violation(s)")
        recommendations.append("Resolve critical BPA violations before migration (use Tabular Editor BPA)")

    # BPA warnings (-1 each, max -5)
    warning_penalty = min(inp.bpa_warning_count * 1, 5)
    if inp.bpa_warning_count > 0:
        score -= warning_penalty
        issues.append(f"{inp.bpa_warning_count} BPA warning violation(s)")
        recommendations.append("Address BPA warnings to improve model health score")

    # Bidirectional relationships (-2 each, max -6)
    bidir_penalty = min(inp.bidirectional_rel_count * 2, 6)
    if inp.bidirectional_rel_count > 0:
        score -= bidir_penalty
        issues.append(f"{inp.bidirectional_rel_count} bidirectional relationship(s) – high Fabric performance risk")
        recommendations.append("Replace bidirectional relationships with single-direction + USERELATIONSHIP in DAX")

    # Many-to-many (-3 each, max -6)
    m2m_penalty = min(inp.many_to_many_rel_count * 3, 6)
    if inp.many_to_many_rel_count > 0:
        score -= m2m_penalty
        issues.append(f"{inp.many_to_many_rel_count} many-to-many relationship(s) – causes CrossFilter overhead at Fabric scale")
        recommendations.append("Resolve M:M relationships by introducing bridge tables or restructuring the model")

    # High cardinality (-2 each, max -4)
    card_penalty = min(inp.high_cardinality_columns * 2, 4)
    if inp.high_cardinality_columns > 0:
        score -= card_penalty
        issues.append(f"{inp.high_cardinality_columns} high-cardinality column(s) (>1M unique values)")
        recommendations.append("Consider hashing, bucketing, or removing high-cardinality columns not used in filters/visuals")

    # Circular dependency (-5, hard block)
    if inp.has_circular_dependency:
        score -= 5
        issues.append("Circular dependency detected – will block Fabric migration")
        recommendations.append("CRITICAL: Resolve circular dependencies before any migration attempt")

    # Unused columns (>30% = -2)
    if inp.unused_columns_pct > 30:
        score -= 2
        issues.append(f"{inp.unused_columns_pct:.0f}% of columns appear unused")
        recommendations.append("Remove unused columns to reduce model size and memory footprint")

    score = _clamp(score, 0, MAX)
    return DimensionScore(
        name="Model Health",
        score=score,
        max_score=MAX,
        pct=round(score / MAX * 100, 1),
        issues=issues,
        recommendations=recommendations,
    )


def score_query_performance(inp: QueryPerformanceInput) -> DimensionScore:
    """Score query performance out of 25."""
    inp = _filled(inp)
    MAX = 25.0
    score = MAX
    issues = []
    recommendations = []

    # Average query duration thresholds
    if inp.avg_query_duration_sec > 30:
        score -= 10
        issues.append(f"Average query duration {inp.avg_query_duration_sec:.1f}s – very slow (>30s)")
        recommendations.append("Profile slow queries using Performance Analyzer; rewrite iterator-heavy measures with variables")
    elif inp.avg_query_duration_sec > 10:
        score -= 6
        issues.append(f"Average query duration {inp.avg_query_duration_sec:.1f}s – slow (>10s)")
        recommendations.append("Review top slow measures; consider pre-aggregations or summary tables")
    elif inp.avg_query_duration_sec > 5:
        score -= 3
        issues.append(f"Average query duration {inp.avg_query_duration_sec:.1f}s – borderline (>5s)")
        recommendations.append("Monitor query performance post-migration; Fabric Warehouse may improve this")

    # % of queries over 30s
    if inp.pct_queries_over_30s > 20:
        score -= 5
        issues.append(f"{inp.pct_queries_over_30s:.0f}% of queries exceed 30s threshold")
        recommendations.append("Investigate frequent long-running query shapes in Query Insights; add aggregation tables")
    elif inp.pct_queries_over_30s > 10:
        score -= 3
        issues.append(f"{inp.pct_queries_over_30s:.0f}% of queries exceed 30s threshold")

    # Iterator-heavy measures (-2 each, max -6)
    iter_penalty = min(inp.iterator_measure_count * 2, 6)
    if inp.iterator_measure_count > 0:
        score -= iter_penalty
        issues.append(f"{inp.iterator_measure_count} iterator-heavy measure(s) (SUMX/AVERAGEX/FILTER)")
        recommendations.append("Rewrite iterators with CALCULATE+FILTER or aggregation columns where possible")

    # Slow visuals
    if inp.slow_visual_count > 0:
        score -= min(inp.slow_visual_count * 2, 4)
        issues.append(f"{inp.slow_visual_count} visual(s) with >10s render time")
        recommendations.append("Split large report pages; reduce visual query complexity; use bookmarks to defer loading")

    # DirectQuery mode (inherently slower, but not always bad)
    if inp.direct_query_mode:
        score -= 2
        issues.append("DirectQuery mode – performance depends on underlying source query speed")
        recommendations.append("Review DirectQuery compatibility with Fabric Warehouse; consider switching to Import or Dual mode")

    score = _clamp(score, 0, MAX)
    return DimensionScore(
        name="Query Performance",
        score=score,
        max_score=MAX,
        pct=round(score / MAX * 100, 1),
        issues=issues,
        recommendations=recommendations,
    )


def score_refresh_efficiency(inp: RefreshEfficiencyInput) -> DimensionScore:
    """Score refresh efficiency out of 20."""
    inp = _filled(inp)
    MAX = 20.0
    score = MAX
    issues = []
    recommendations = []

    # Refresh failure rate
    if inp.refresh_failure_rate_pct > 20:
        score -= 8
        issues.append(f"{inp.refresh_failure_rate_pct:.0f}% refresh failure rate (last 30 days) – unreliable")
        recommendations.append("URGENT: Investigate refresh failures; fix data source connectivity and timeout issues before migration")
    elif inp.refresh_failure_rate_pct > 10:
        score -= 4
        issues.append(f"{inp.refresh_failure_rate_pct:.0f}% refresh failure rate – unstable")
        recommendations.append("Review refresh error logs; fix intermittent source failures before migration")
    elif inp.refresh_failure_rate_pct > 5:
        score -= 2
        issues.append(f"{inp.refresh_failure_rate_pct:.0f}% refresh failure rate – occasional failures")

    # Refresh duration
    if inp.avg_refresh_duration_min > 120:
        score -= 5
        issues.append(f"Average refresh duration {inp.avg_refresh_duration_min:.0f} min – very long (>2hr)")
        recommendations.append("Implement incremental refresh partitioning; archive cold data to reduce full refresh scope")
    elif inp.avg_refresh_duration_min > 60:
        score -= 3
        issues.append(f"Average refresh duration {inp.avg_refresh_duration_min:.0f} min – slow (>1hr)")
        recommendations.append("Consider incremental refresh and partition pruning to reduce refresh window")
    elif inp.avg_refresh_duration_min > 30:
        score -= 1
        issues.append(f"Average refresh duration {inp.avg_refresh_duration_min:.0f} min")

    # Full refresh on large table
    if inp.full_refresh_on_large_table:
        score -= 5
        issues.append(f"Full refresh running on large table ({inp.largest_table_row_count:,} rows)")
        recommendations.append("Implement incremental refresh on large fact tables before migrating to Fabric")

    # Excessive refresh frequency without incremental
    if inp.refresh_frequency_per_day > 4 and not inp.uses_incremental_refresh:
        score -= 3
        issues.append(f"Refreshing {inp.refresh_frequency_per_day:.0f}x/day without incremental refresh")
        recommendations.append("High-frequency full refreshes will consume significant Fabric CU capacity; enable incremental refresh")

    # Reward incremental refresh
    if inp.uses_incremental_refresh:
        score = min(score + 2, MAX)
        recommendations.append("Incremental refresh is configured – good practice, verify it works correctly post-migration")

    score = _clamp(score, 0, MAX)
    return DimensionScore(
        name="Refresh Efficiency",
        score=score,
        max_score=MAX,
        pct=round(score / MAX * 100, 1),
        issues=issues,
        recommendations=recommendations,
    )


def score_usage(inp: UsageInput) -> DimensionScore:
    """Score usage & business value out of 20."""
    inp = _filled(inp)
    MAX = 20.0
    issues = []
    recommendations = []

    # Base score from active users
    if inp.active_users_30d >= 50:
        score = 20.0
    elif inp.active_users_30d >= 20:
        score = 16.0
    elif inp.active_users_30d >= 10:
        score = 12.0
    elif inp.active_users_30d >= 5:
        score = 8.0
    elif inp.active_users_30d >= 1:
        score = 5.0
    else:
        score = 0.0
        issues.append("No active users in the last 30 days – potential decommission candidate")
        recommendations.append("Confirm with dataset owner whether this dataset is still needed before migrating")

    # Stale dataset penalty
    if inp.days_since_last_used > 90:
        score -= 5
        issues.append(f"Not accessed in {inp.days_since_last_used} days – likely stale")
        recommendations.append(f"Dataset unused for {inp.days_since_last_used} days – validate business need before migration")
    elif inp.days_since_last_used > 60:
        score -= 3
        issues.append(f"Not accessed in {inp.days_since_last_used} days")

    # Report coverage bonus
    if inp.report_count > 5:
        score = min(score + 2, MAX)
    elif inp.report_count == 0:
        issues.append("No reports connected to this dataset")
        recommendations.append("Verify this dataset is still in use; no connected reports may indicate it can be retired")

    # Certified/endorsed bonus
    if inp.is_certified:
        score = min(score + 2, MAX)

    score = _clamp(score, 0, MAX)
    return DimensionScore(
        name="Usage & Business Value",
        score=score,
        max_score=MAX,
        pct=round(score / MAX * 100, 1),
        issues=issues,
        recommendations=recommendations,
    )


def score_size_complexity(inp: SizeComplexityInput) -> DimensionScore:
    """Score size & complexity out of 10."""
    inp = _filled(inp)
    MAX = 10.0
    score = MAX
    issues = []
    recommendations = []

    # Model size
    if inp.model_size_gb > 10:
        score -= 5
        issues.append(f"Model size {inp.model_size_gb:.1f} GB – very large; high migration effort and Fabric memory cost")
        recommendations.append("Reduce model size: remove unused columns, archive cold data, implement aggregations")
    elif inp.model_size_gb > 5:
        score -= 3
        issues.append(f"Model size {inp.model_size_gb:.1f} GB – large; significant Fabric capacity impact")
        recommendations.append("Review column-level memory usage in Model Memory Analyzer; optimize before migration")
    elif inp.model_size_gb > 2:
        score -= 1
        issues.append(f"Model size {inp.model_size_gb:.1f} GB – moderate")

    # Table count
    if inp.table_count > 50:
        score -= 3
        issues.append(f"{inp.table_count} tables – very complex model; high risk of relationship issues post-migration")
        recommendations.append("Simplify model schema where possible; document all relationships before migration")
    elif inp.table_count > 25:
        score -= 1
        issues.append(f"{inp.table_count} tables – complex model")

    # Column count
    if inp.column_count > 500:
        score -= 2
        issues.append(f"{inp.column_count} columns – wide model; likely contains many unused fields")
        recommendations.append("Run unused column analysis and remove columns not referenced by any measure or visual")
    elif inp.column_count > 200:
        score -= 1

    score = _clamp(score, 0, MAX)
    return DimensionScore(
        name="Size & Complexity",
        score=score,
        max_score=MAX,
        pct=round(score / MAX * 100, 1),
        issues=issues,
        recommendations=recommendations,
    )


def _estimate_effort(score: float, dimensions: list[DimensionScore]) -> int:
    """Estimate remediation effort in working days."""
    if score >= 80:
        return 0
    total_issues = sum(len(d.issues) for d in dimensions)
    base = max(0, int((80 - score) / 10))  # 1 day per 10 points below 80
    return base + (total_issues // 3)


def _migration_risk(score: float) -> str:
    if score >= 80:
        return "Low"
    if score >= 60:
        return "Medium"
    return "Medium" if score >= 40 else "High"


# Decisions from least to most severe. A blocker sets a floor: the final decision is
# the more severe of the score-based decision and every blocker's floor.
_SEVERITY = [MigrationDecision.MIGRATE, MigrationDecision.FIX_MIGRATE,
             MigrationDecision.MAJOR_REFACTOR, MigrationDecision.RETIRE]
_DECISION_COLOR = {
    MigrationDecision.MIGRATE: "green",
    MigrationDecision.FIX_MIGRATE: "blue",
    MigrationDecision.MAJOR_REFACTOR: "orange",
    MigrationDecision.RETIRE: "red",
    MigrationDecision.NEEDS_ASSESSMENT: "gray",
}


def _blockers(inp: DatasetInput) -> list[tuple[MigrationDecision, bool, str]]:
    """Conditions that override the score: (minimum decision, forces High risk, reason).

    Only measured values are considered – an unmeasured metric never triggers a blocker.
    """
    found = []
    health, refresh, usage = inp.model_health, inp.refresh_efficiency, inp.usage

    if health.has_circular_dependency:
        found.append((MigrationDecision.MAJOR_REFACTOR, True,
                      "Circular dependency – blocks Fabric migration until resolved"))
    if refresh.refresh_failure_rate_pct is not None and refresh.refresh_failure_rate_pct > 20:
        found.append((MigrationDecision.FIX_MIGRATE, True,
                      f"{refresh.refresh_failure_rate_pct:.0f}% refresh failure rate – "
                      "fix refresh reliability before migrating"))
    if usage.active_users_30d == 0:
        if usage.days_since_last_used is not None and usage.days_since_last_used >= 90:
            found.append((MigrationDecision.RETIRE, False,
                          f"No active users in 30 days and not used for {usage.days_since_last_used} days – "
                          "retire unless the owner confirms a business need"))
        else:
            found.append((MigrationDecision.FIX_MIGRATE, False,
                          "No active users in 30 days – confirm business need with the owner before migrating"))
    return found


# (input attribute, scorer, display name, max points, fields that count as "measured",
#  how to get the data when it is missing)
_DIMENSIONS = [
    ("model_health", score_model_health, "Model Health", 25.0, None,
     "Run notebooks/enrich_scores.ipynb (Semantic Link) to collect BPA and relationship metrics"),
    ("query_performance", score_query_performance, "Query Performance", 25.0, None,
     "Post avg_query_duration_sec / pct_queries_over_30s from Query Insights or Log Analytics via bpa-update"),
    ("refresh_efficiency", score_refresh_efficiency, "Refresh Efficiency", 20.0, None,
     "No refresh history available – check the dataset's refresh history in the Power BI service"),
    # Report count and endorsement alone don't show whether anyone uses the dataset
    ("usage", score_usage, "Usage & Business Value", 20.0, ("active_users_30d", "days_since_last_used"),
     "Post active_users_30d / days_since_last_used from the Power BI activity log or usage metrics via bpa-update"),
    ("size_complexity", score_size_complexity, "Size & Complexity", 10.0, None,
     "Run notebooks/enrich_scores.ipynb (Semantic Link) to collect model size, table and column counts"),
]

# A decision is only issued when these are measured: they decide whether a dataset
# should be retired or is blocked from migration.
_REQUIRED_FOR_DECISION = ("Model Health", "Usage & Business Value")


def _unmeasured(name: str, max_score: float, how_to_measure: str) -> DimensionScore:
    return DimensionScore(
        name=name, score=0.0, max_score=max_score, pct=0.0,
        issues=["Not measured – excluded from the score"],
        recommendations=[how_to_measure],
        measured=False,
    )


def score_dataset(inp: DatasetInput) -> ScoringResult:
    """Run all 5 scoring dimensions and produce a final migration readiness result."""
    dimensions = []
    for attr, scorer, name, max_score, keys, how_to_measure in _DIMENSIONS:
        section = getattr(inp, attr)
        if _is_measured(section, keys):
            dimensions.append(scorer(section))
        else:
            dimensions.append(_unmeasured(name, max_score, how_to_measure))

    measured = [d for d in dimensions if d.measured]
    measured_max = sum(d.max_score for d in measured)
    # Scale to 100 over what was actually measured, so missing data is neither
    # rewarded (scored as perfect) nor punished (scored as zero).
    total = round(sum(d.score for d in measured) / measured_max * 100, 1) if measured_max else 0.0
    unmeasured_names = [d.name for d in dimensions if not d.measured]

    blockers = _blockers(inp)
    needs_assessment = any(n in unmeasured_names for n in _REQUIRED_FOR_DECISION)

    if needs_assessment:
        decision = MigrationDecision.NEEDS_ASSESSMENT
    else:
        if total >= 80:
            decision = MigrationDecision.MIGRATE
        elif total >= 60:
            decision = MigrationDecision.FIX_MIGRATE
        elif total >= 40:
            decision = MigrationDecision.MAJOR_REFACTOR
        else:
            decision = MigrationDecision.RETIRE
        for floor, _, _ in blockers:
            if _SEVERITY.index(floor) > _SEVERITY.index(decision):
                decision = floor

    if any(high for _, high, _ in blockers):
        risk = "High"
    elif needs_assessment:
        risk = "Unknown"
    else:
        risk = _migration_risk(total)

    # Top 3 priority fixes across all dimensions
    all_recs = [r for d in dimensions for r in d.recommendations]
    priority_fixes = all_recs[:5]

    return ScoringResult(
        dataset_id=inp.dataset_id,
        dataset_name=inp.dataset_name,
        workspace_name=inp.workspace_name,
        owner=inp.owner,
        total_score=total,
        decision=decision,
        decision_color=_DECISION_COLOR[decision],
        dimensions=dimensions,
        priority_fixes=priority_fixes,
        estimated_effort_days=0 if needs_assessment else _estimate_effort(total, measured),
        migration_risk=risk,
        blockers=[reason for _, _, reason in blockers],
        last_modified=inp.last_modified,
        created_date=inp.created_date,
        model_size_gb=inp.size_complexity.model_size_gb,
        active_users_30d=inp.usage.active_users_30d,
        data_coverage_pct=measured_max,
        unmeasured_dimensions=unmeasured_names,
    )
