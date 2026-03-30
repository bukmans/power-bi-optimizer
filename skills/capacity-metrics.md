---
name: capacity-metrics
description: Analyse Fabric Capacity Metrics App data to identify CU burn, throttling events, refresh inefficiencies, and recommend green refresh windows
---

# Capacity Metrics Analysis Skill

Use this skill when asked to analyse Microsoft Fabric Capacity Metrics App data, CU consumption, throttling events, or refresh scheduling.

## Key Metrics to Analyse

### CU (Capacity Unit) Consumption
- **Interactive operations**: visuals, queries — consume CU immediately; throttled if burst limit exceeded
- **Background operations**: dataset refreshes, dataflows — smoothed over 24hr window
- The Capacity Metrics App shows utilisation at 30-second intervals

### Throttling Thresholds (Fabric F-SKUs)
| SKU | CU/sec | 10min burst limit |
|-----|--------|-------------------|
| F2  | 2      | 1,200 CU          |
| F4  | 4      | 2,400 CU          |
| F8  | 8      | 4,800 CU          |
| F16 | 16     | 9,600 CU          |
| F32 | 32     | 19,200 CU         |
| F64 | 64     | 38,400 CU         |

When utilisation exceeds 100% for a sustained period, Fabric queues (throttles) operations.

## Analysis Patterns

### 1. Identifying CU Waste
Look for:
- Refreshes running during peak interactive hours (9am–6pm) — move to off-peak
- Semantic models refreshing more frequently than data actually changes
- Multiple workspaces refreshing the same source table independently
- Reports with many hidden calculations running on page load

### 2. Finding the Green Refresh Window
```
Process:
1. From Capacity Metrics App, export the "CU by Operation" chart data
2. Calculate average CU per 30-min slot across the week
3. Identify slots where average CU < 60% of SKU capacity
4. Prefer windows: 11pm–5am (lowest interactive load)
5. Stagger refreshes: don't start all datasets at same time
```

### 3. Refresh Efficiency Score
For each dataset:
```
Refresh Efficiency = (Data freshness requirement met?) × (CU used per refresh) × (Failure rate)

Good:   < 10 min refresh, < 5% failure, runs off-peak
Okay:   10–60 min, < 10% failure, some peak overlap
Poor:   > 60 min, > 10% failure, or runs during peak CU hours
```

### 4. Throttling Root Cause Analysis
When throttling is detected:
1. Check if it's driven by interactive or background operations
2. Identify the top 3 operations by CU at the throttle point
3. Check if a large refresh coincides with peak dashboard usage
4. Recommend either: SKU upgrade, refresh rescheduling, or query optimisation

## Recommendations Framework

### Refresh Scheduling
```
Priority 1 — Operational dashboards (real-time need):
  → Use incremental refresh to minimise CU per cycle
  → Schedule every 15–30 min on small partition only

Priority 2 — Daily business reports:
  → Schedule between 5am–7am (before business hours)
  → Stagger by 15 min between large datasets

Priority 3 — Weekly/monthly reports:
  → Weekend off-peak (Sat/Sun 1am–4am)
  → Consider on-demand refresh triggered by pipeline completion

Do NOT refresh: datasets with 0 active users in 30 days
```

### Cost Optimisation Signals
Flag for owner review if:
- Dataset uses >X% of daily capacity budget with <5 active users
- Refresh frequency > 2x per day but last_used_date is stale
- Model size >5 GB on datasets with <10 users
- Full refresh running on datasets that have ≥6 months of unchanged historical data

## Output Format

```
CAPACITY METRICS ANALYSIS
Capacity: [SKU] | Analysis window: [dates]

UTILISATION SUMMARY:
- Average daily CU: X% of capacity
- Peak utilisation: X% at [time/day]
- Throttling events: N (last 30 days)
- Estimated CU waste from inefficient refreshes: N CU/day

TOP CU CONSUMERS:
1. [Dataset/Operation] — X CU/day (X% of total)
2. ...

THROTTLING ANALYSIS:
- Root cause: [interactive burst / background accumulation]
- Affected operations: [list]
- Fix: [specific action]

REFRESH SCHEDULE RECOMMENDATIONS:
┌──────────────────────────┬─────────────┬──────────────────┐
│ Dataset                  │ Current     │ Recommended      │
├──────────────────────────┼─────────────┼──────────────────┤
│ Finance KPI Dashboard    │ 6x/day      │ 4x/day + incr.   │
│ Legacy CRM Report        │ Daily 9am   │ Off-peak / Retire│
└──────────────────────────┴─────────────┴──────────────────┘

ESTIMATED CU SAVINGS: X CU/day (X% reduction)
```
