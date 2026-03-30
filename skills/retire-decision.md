---
name: retire-decision
description: Evaluate whether a Power BI dataset or report should be retired rather than migrated to Fabric, using usage, cost, and business value signals
---

# Retire vs Migrate Decision Skill

Use this skill when asked to evaluate whether a dataset should be **retired (decommissioned)** instead of migrated to Fabric.

## The Retire Decision Framework

A dataset is a strong retire candidate if it meets **3 or more** of these signals:

### Hard Stop Signals (any one = immediate retire candidate)
- [ ] Migration readiness score < 40
- [ ] Zero active users in last 60 days
- [ ] Last accessed > 90 days ago with no scheduled consumers
- [ ] Circular dependency that owner has no capacity to fix
- [ ] Refresh failure rate > 50% for > 30 days with no remediation

### Soft Signals (accumulate weight)
- [ ] 1–3 active users AND migration effort > 10 days (ROI negative)
- [ ] Dataset is a point-in-time snapshot (e.g., FY2021 Budget, Q3 Analysis)
- [ ] Functionally duplicated by another certified dataset
- [ ] No connected reports or dashboards
- [ ] Owner is unknown or has left the organisation
- [ ] Created > 3 years ago with no meaningful update since
- [ ] Model is in a personal workspace (not shared/governed)
- [ ] Data is available from a better-governed dataset elsewhere

## Retire Decision Process

When evaluating a dataset for retirement:

1. **Check usage** — Pull 90-day active user count from Admin API or Capacity Metrics App
2. **Check business criticality** — Ask: "Is there a downstream process, pipeline, or SLA that depends on this?"
3. **Check duplicates** — Is the same data available in a certified model?
4. **Estimate migration cost** — Score × effort estimate vs. number of users served
5. **Engage the owner** — No dataset should be retired without owner sign-off (even if usage = 0)

## ROI Calculation for Borderline Cases

```
Migration ROI = (Users served per month × Business value per user) / Migration effort cost

If ROI < 1.0 → retire candidate
If ROI 1.0–2.0 → review with owner
If ROI > 2.0 → migrate

Example:
Dataset has 3 users, effort is 8 days, daily dev cost ~£400
Migration cost = 8 × £400 = £3,200
Users × value (assume £200/user/month) = £600/month
Break-even: 5.3 months

If dataset is retiring in < 6 months anyway → retire
If it's a long-lived operational dataset → migrate
```

## Communication Templates

### Retire Notification to Owner
```
Subject: [Dataset Name] – Migration Assessment: Retire Recommended

Hi [Owner],

As part of our Power BI → Fabric migration programme, we assessed
[Dataset Name] in [Workspace] and scored it [Score]/100.

Our recommendation is to retire this dataset rather than migrate it
to Fabric for the following reasons:
- [Top reason 1]
- [Top reason 2]

Action required: Please confirm by [date] whether this dataset can
be decommissioned, or provide a business justification for migration.

If you have no objection by [date], we will archive and remove
this dataset from the migration backlog.
```

### Retire Confirmed – Decommission Checklist
- [ ] Owner confirmed retirement in writing
- [ ] No downstream pipelines or alerts depend on this dataset
- [ ] Export final version to OneLake archive (parquet) if >1 year old
- [ ] Remove from all workspaces
- [ ] Update migration tracker to "Retired"
- [ ] Document reason in Purview lineage (when available)

## Output Format

When completing a retire evaluation:

```
RETIRE ASSESSMENT: [Dataset Name]

Score: X / 100
Hard stop signals triggered: N
Soft signals: N of 8

RECOMMENDATION: [Retire / Review with owner / Migrate]

RATIONALE:
- [Signal 1]: [evidence]
- [Signal 2]: [evidence]

ROI ANALYSIS:
- Active users (90d): N
- Est. migration effort: N days
- Break-even: N months
- Verdict: [retire/migrate]

NEXT STEPS:
1. [Specific action for platform team]
2. [Message to send to owner]
3. [Timeline]
```
