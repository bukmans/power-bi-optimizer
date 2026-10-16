# Changelog

All notable changes to this project are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Fixes from the October 2026 code review. Each entry links to the tests that cover it
(run with `pip install -r requirements-dev.txt && pytest`).

### Added
- Test suite under `tests/` and `requirements-dev.txt`.

### Fixed
- **Search endpoint always returned 404.** `GET /api/datasets/search` was declared after
  `GET /api/datasets/{dataset_id}`, so "search" was treated as a dataset id. Route moved
  above the parameterised route. Restores the Copilot Studio name search. (`tests/test_search.py`)
- **Partial BPA updates reset other metrics to zero.** `POST /api/datasets/{id}/bpa-update`
  defaulted every field to 0, so posting only BPA counts wiped active users, size and query
  metrics. Fields are now optional; only fields present in the body are applied, and
  successive posts accumulate. Negative values and percentages over 100 are rejected (422).
  The response now lists `fields_updated`. (`tests/test_bpa_overrides.py`)
- **Overrides permanently mutated the dataset cache and the demo data.** Overrides were
  written onto the cached objects with `setattr`, which were the same objects as
  `DEMO_DATASETS`, so `POST /api/reset-demo` could not restore the original demo. Overrides
  are now applied to a copy at scoring time and demo data is deep-copied on load.
- **Dataset detail ignored overrides.** `GET /api/datasets/{id}` scored the raw cached input
  while the list applied overrides, so the detail panel and the table could show different
  scores. Both now use one helper (`_score_one`).
- **Missing data was scored as perfect.** In live mode only refresh history and report count are
  collected, but model health, query performance and size defaulted to zero issues (full marks),
  so every live dataset landed around 80 – "Migrate as-is". All scorer metrics now default to
  `None` (not measured); a dimension with no measured metrics is excluded and the total is scaled
  to 100 over the measured dimensions. (`tests/test_unmeasured.py`)
- **Unused and blocked datasets could be "Migrate as-is".** The decision was purely score-based:
  a healthy dataset with zero users scored 80 ("Migrate as-is", Low risk) and one with a circular
  dependency scored 95 ("Migrate as-is", Low risk) despite its own "will block migration" message.
  Blocker rules now set a minimum decision – circular dependency → Major refactor + High risk;
  refresh failures > 20% → Fix then migrate + High risk (previously only flagged High when the
  score was already under 60); 0 users and unused ≥ 90 days → Consider decommission; 0 users
  otherwise → Fix then migrate. A blocker never improves a worse score-based decision.
  Demo decisions are unchanged. (`tests/test_blockers.py`)

### Added
- Decision **"Needs assessment"** (grey), issued when Model Health or Usage is not measured,
  with risk `Unknown` and no effort estimate. Each unmeasured dimension says how to collect it.
- API fields `data_coverage_pct`, `unmeasured_dimensions` and per-dimension `measured`;
  `needs_assessment` count in `/api/summary` (the average score now excludes these datasets);
  "Data Coverage %" column in the CSV export, with "Not measured" for missing dimensions.
- Dashboard: "Needs Assessment" card, decision and risk filters, hatched bars for unmeasured
  dimensions, "x% data" under partial scores; not-assessed datasets show "—" and sort last.
- `blockers` list in the API and a "Blockers" CSV column explaining any override; the detail
  panel shows them in a "Why this decision overrides the score" box, the table marks them with ⛔.
