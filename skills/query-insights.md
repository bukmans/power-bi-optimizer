---
name: query-insights
description: Analyse Fabric Query Insights and Query Activity telemetry to identify slow queries, high-CU patterns, and coach query rewrites
---

# Query Insights & Performance Analysis Skill

Use this skill when asked to analyse query performance data from Fabric Warehouse Query Insights or Power BI query telemetry.

## Data Sources

### Query Insights (30-day historical)
Available in Fabric via: `Workspace > SQL Analytics Endpoint > System Tables`
```sql
-- Top 10 slowest query shapes (last 30 days)
SELECT
    distributed_statement_id,
    login_name,
    status,
    total_elapsed_time_ms,
    rows_returned,
    command,
    start_time
FROM queryinsights.exec_requests_history
WHERE total_elapsed_time_ms > 30000   -- > 30 seconds
ORDER BY total_elapsed_time_ms DESC
LIMIT 10;

-- Frequent slow queries (high impact shapes)
SELECT
    LEFT(command, 100) AS query_shape,
    COUNT(*) AS execution_count,
    AVG(total_elapsed_time_ms) AS avg_ms,
    MAX(total_elapsed_time_ms) AS max_ms,
    SUM(total_elapsed_time_ms) AS total_ms
FROM queryinsights.exec_requests_history
WHERE status = 'Succeeded'
GROUP BY LEFT(command, 100)
HAVING COUNT(*) > 5
ORDER BY total_ms DESC;
```

### Query Activity (live/running)
```sql
-- Currently running queries
SELECT * FROM queryinsights.exec_sessions_history
WHERE status = 'Running'
ORDER BY login_time DESC;
```

## Performance Analysis Framework

When given query telemetry, identify:

### 1. Long-Running Query Patterns
- Queries > 30s: investigate join types, predicate sargability, statistics health
- Queries 10–30s: look for full table scans, implicit conversions, missing statistics

### 2. Sargability Issues (non-sargable predicates)
```sql
-- Bad: function on column prevents index use
WHERE YEAR(OrderDate) = 2024

-- Good: use range predicate
WHERE OrderDate >= '2024-01-01' AND OrderDate < '2025-01-01'

-- Bad: implicit type conversion on join
WHERE CustomerID = '12345'  -- CustomerID is INT, comparing to VARCHAR

-- Good: match types explicitly
WHERE CustomerID = 12345
```

### 3. Statistics Hygiene (Fabric Warehouse)
```sql
-- Check statistics freshness
SELECT
    name,
    stats_id,
    last_updated,
    rows,
    rows_sampled
FROM sys.stats s
JOIN sys.objects o ON s.object_id = o.object_id
WHERE o.type = 'U'
ORDER BY last_updated ASC;

-- Update stale stats (run after large loads)
UPDATE STATISTICS [dbo].[FactSales];
```

### 4. Timestamp Filtering Caveats (Fabric-specific)
Fabric Warehouse stores timestamps in UTC. Be explicit:
```sql
-- Risky: assumes local timezone
WHERE OrderDate = GETDATE()

-- Safe: always use UTC and explicit casting
WHERE OrderDate >= CAST(GETUTCDATE() AS DATE)
  AND OrderDate <  DATEADD(DAY, 1, CAST(GETUTCDATE() AS DATE))
```

### 5. Join Type Parity
```sql
-- Avoid: joining INT to VARCHAR causes implicit conversion scan
SELECT * FROM Orders o
JOIN Customers c ON o.CustID = c.CustID_Str  -- type mismatch

-- Fix: ensure both sides are same type, or CAST explicitly and accept the cost
```

## Query Rewrite Coaching

When asked to improve a slow query, follow this process:
1. Identify the bottleneck (full scan? bad join? function on predicate?)
2. Check execution plan or stats if available
3. Apply the smallest fix first
4. Provide before/after with explanation of why it helps

## Output Format

```
QUERY PERFORMANCE ANALYSIS
Data window: [date range]

SUMMARY:
- Total queries analysed: N
- Long-running (>30s): N (X%)
- Average duration: Xs
- Total CU consumed: N

TOP SLOW QUERIES:
1. [Query shape truncated to 80 chars]
   Avg: Xs | Runs: N | Total time: Xs
   Root cause: [diagnosis]
   Fix: [specific rewrite recommendation]

REFRESH TIMING:
- Peak query load window: [time range]
- Recommended refresh window: [time range] (avoids throttling)

CAPACITY CORRELATION:
- Throttling events: N
- Queries during throttle: N%
- Recommendation: [shift/reduce/schedule]
```
