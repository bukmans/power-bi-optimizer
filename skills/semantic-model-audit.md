---
name: semantic-model-audit
description: Audit a Power BI semantic model for BPA violations, DAX quality issues, relationship problems, and memory usage before Fabric migration
---

# Semantic Model Audit Skill

Use this skill when asked to audit a Power BI semantic model. This covers Best Practice Analyzer (BPA) rules, DAX quality, relationship health, and memory footprint — all critical inputs to the migration readiness score.

## BPA Rule Categories to Check

### Critical (block migration)
- **AVOID_FLOATING_POINT_NUMERIC_TYPE** — Use Fixed Decimal Number instead of Decimal where precision matters
- **AVOID_CALCULATED_COLUMNS_THAT_REFERENCE_OTHER_CALCULATED_COLUMNS** — Causes refresh chain issues
- **NO_CALCULATED_TABLES** — Calculated tables increase model complexity and memory
- **AVOID_ROWS_COLUMNS_IN_ROLES** — Use object-level security instead
- **INTEGER_FORMATTING** — Large integers without formatting cause visual errors

### High Priority (fix before migration)
- **AVOID_BIDIRECTIONAL_RELATIONSHIPS_ONE_TO_MANY** — CrossFilter overhead at Fabric scale
- **MANY_TO_MANY_RELATIONSHIPS** — Introduce bridge tables or restructure
- **INACTIVE_RELATIONSHIPS_SHOULD_NOT_BE_AMBIGUOUS** — Use USERELATIONSHIP explicitly in DAX
- **AVOID_USING_LONG_STRINGS_COLUMN** — High memory and compression cost

### DAX Quality Checks
When reviewing measures, flag:
1. **Iterator overuse** — SUMX/AVERAGEX over large tables without variable caching
   ```dax
   -- Bad: evaluates for every row
   Sales Amount = SUMX(Orders, Orders[Qty] * Orders[UnitPrice])

   -- Better: use pre-computed column or
   Sales Amount = SUMX(Orders, Orders[LineTotal])
   ```
2. **CALCULATE without REMOVEFILTERS** — Can cause incorrect totals
3. **DIVIDE()** not used for division — Use DIVIDE(a, b, 0) not a/b
4. **Missing VAR/RETURN** pattern in multi-step measures
5. **ALL() vs REMOVEFILTERS()** — Prefer REMOVEFILTERS for clarity in Fabric

### Relationship Audit
For each relationship, check:
- Is it single-direction? (prefer)
- Is the cardinality correct? (1:M is ideal; flag M:M)
- Is the cross-filter direction set to "Both"? (flag for removal)
- Are there inactive relationships that need USERELATIONSHIP in measures?

### Memory Usage Assessment (via Semantic Link)
Run in a Fabric notebook:
```python
from sempy import fabric
import sempy.fabric as spf

# Get model memory usage
model = spf.FabricDataFrame(
    spf.evaluate_dax(dataset="Your Dataset", dax_string="""
    SELECT
        [DIMENSION_NAME],
        [ATTRIBUTE_NAME],
        [DICTIONARY_SIZE],
        [USED_SIZE]
    FROM $SYSTEM.DISCOVER_STORAGE_TABLES
    ORDER BY [USED_SIZE] DESC
    """)
)
print(model.head(20))
```
Flag any column with USED_SIZE > 100 MB that is not referenced in measures or visuals.

## Output Format

When completing a semantic model audit, provide:

```
SEMANTIC MODEL AUDIT: [Dataset Name]
Audit Date: [Date]

BPA SUMMARY:
- Critical violations: N
- High-priority warnings: N
- Total rules checked: N

TOP ISSUES:
1. [Issue] — Impact: [High/Med/Low] — Fix: [specific action]
2. ...

DAX QUALITY:
- Iterator-heavy measures: [list names]
- Missing DIVIDE(): [list measures]
- Suggested rewrites: [specific examples]

RELATIONSHIP HEALTH:
- Total relationships: N
- Bidirectional: N (flag if > 0)
- Many-to-many: N (flag if > 0)

MEMORY HOTSPOTS:
- Top 3 columns by memory: [name, size]
- Recommended removals: [list]

MIGRATION READINESS CONTRIBUTION:
Model Health score: X / 25
```
