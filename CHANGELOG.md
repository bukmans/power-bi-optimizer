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
- **Priority fix list wasn't prioritised.** It returned the first 5 recommendations in dimension
  order (the code comment said 3) and could include the informational note "Incremental refresh is
  configured – good practice". Fixes are now ranked by the points each would recover, blockers
  come first, informational notes are excluded, duplicates removed, capped at 5.
  (`tests/test_priority_fixes.py`)
- **"No reports connected" was reported when the report count was unknown**, because the check
  was `report_count == 0` and the old default was 0. It now only fires when the count was measured.
- **Live mode misread the Power BI API** (`engine/pbi_client.py`, `tests/test_pbi_client.py`):
  - `uses_incremental_refresh` was set from `isRefreshable`, which only means a dataset *can* be
    refreshed – nearly every dataset got the incremental-refresh bonus and skipped the
    "frequent full refresh" penalty. Now left unmeasured (the REST API does not expose it).
  - Refresh failure rate counted in-progress ("Unknown"), cancelled and disabled refreshes as
    successes; only Completed/Failed are now counted.
  - History said "last 30 days" but used the last 30 refreshes of any age; now filtered to 30 days.
  - Timestamps without fractional seconds (or with 7-digit fractions) failed to parse and were
    silently dropped, giving 0-minute averages. Parsing is now tolerant.
  - No refresh history now means "not measured" instead of a perfect 0% failure rate.
  - A dataset with `endorsementDetails: null` crashed the whole connect.
  - Refresh history is fetched concurrently (max 8 in flight) over one HTTP client instead of
    sequentially with a new client per call.
- **`/api/connect` garbled its own errors.** Its "No datasets found" `HTTPException` was caught and
  re-wrapped by a broad `except`. Errors are now raised once with a clear message, and BPA
  overrides from the previous dataset set are cleared on connect.
- **Owner decisions accepted any string and dropped notes.** `decision` is now limited to
  `migrate` / `fix_migrate` / `retire` (422 otherwise), `""` clears a decision (what the
  dashboard's "Pending" option sends – previously stored as a decision), the body `dataset_id`
  must match the URL, and `notes` (max 2000 chars) are stored with a timestamp and returned as
  `owner_decision_notes`. The dashboard has a notes field and reports save failures.
  (`tests/test_owner_decision.py`)
- **Workspace filter gained duplicate entries** every time the dataset list reloaded (after each
  saved decision, connect or reset), and the reload discarded the user's active filters. The
  options are now rebuilt and the current filters re-applied.
- **Copilot Studio used the wrong label for refactor decisions.** The help topic and score card
  matched "Major refactor needed", but the API returns "Major refactor required", so refactor
  datasets showed the fallback 'Attention' colour. Labels corrected; "Needs assessment" and
  blockers added to the help topic, the programme summary and the card colours. The connector spec
  (`openapi.json`) gains the new response fields, the previously undocumented `workspaces` and
  `last_modified`, the "Needs assessment" filter value and a 401 response on every operation.
  `tests/test_copilot_contract.py` fails if the spec or cards drift from the API again.
- Usage now counts as measured only when `active_users_30d` is known; a last-used date alone no
  longer produces a usage score that reads the missing user count as zero users.

### Security
- **The deployed app ran with no authentication.** `require_api_key` skipped the check whenever
  `OPTIMIZER_API_KEY` was unset or still the placeholder, and the deploy workflow never set it –
  with external ingress. Auth now fails closed: missing/placeholder key → the app refuses to start
  (and any request gets 503); invalid key → 401 (was 403). Keys are compared with
  `secrets.compare_digest`. (`tests/test_auth.py`)
- **`/api/connect`, `/api/reset-demo` and `/api/export/csv` had no auth at all**, so anyone could
  download the full inventory or repoint the app at another tenant. All `/api/*` routes are now
  protected, and a test enumerates every `/api` route so new ones can't ship unprotected.
- `python app.py` now binds to `127.0.0.1` by default (was `0.0.0.0`); with no key it runs
  without auth on localhost only, and refuses to start on any other `HOST` without a key.
- CORS: `https://*.azure-apim.net` never matched (wildcards aren't supported in `allow_origins`);
  now `allow_origin_regex`. `allow_credentials` turned off (auth is a header, not a cookie);
  methods and headers narrowed to what the API uses.
- Deploy workflow passes `OPTIMIZER_API_KEY` from the `optimizer-api-key` Container App secret;
  setup script and `deploy/README.md` explain how to set it; `.env.example` includes it.
- **A local `.env` (with the Power BI client secret) was copied into the Docker image** by
  `COPY . .` – there was no `.dockerignore`. Added one that excludes `.env*`, `data/`, `.git`,
  the venv, tests and docs.

### Added
- **Owner decisions and BPA overrides are persisted** to `data/state.json`
  (`OPTIMIZER_STATE_FILE` to change). Previously all state was in memory and lost on every
  restart or redeploy. Writes are atomic (temp file + rename) under a lock; an unreadable file is
  moved aside as `state.json.corrupt-<timestamp>` rather than overwritten. Demo and live state
  are stored separately: "Switch back to demo data" clears only demo state, and live decisions
  survive reconnects. Docker image creates a writable `/app/data` volume and docker-compose mounts
  a named volume; `deploy/README.md` covers Azure Files for Container Apps (single replica).
  (`tests/test_persistence.py`)
- `GET /healthz` – unauthenticated liveness probe returning no data. The docker-compose
  healthcheck used `/api/status`, which now needs a key.
- Dashboard asks for the API key once per tab (kept in `sessionStorage`), sends it on every call,
  downloads the CSV through an authenticated request, and shows a clear message if no key is given.
- Decision **"Needs assessment"** (grey), issued when Model Health or Usage is not measured,
  with risk `Unknown` and no effort estimate. Each unmeasured dimension says how to collect it.
- API fields `data_coverage_pct`, `unmeasured_dimensions` and per-dimension `measured`;
  `needs_assessment` count in `/api/summary` (the average score now excludes these datasets);
  "Data Coverage %" column in the CSV export, with "Not measured" for missing dimensions.
- Dashboard: "Needs Assessment" card, decision and risk filters, hatched bars for unmeasured
  dimensions, "x% data" under partial scores; not-assessed datasets show "—" and sort last.
- `blockers` list in the API and a "Blockers" CSV column explaining any override; the detail
  panel shows them in a "Why this decision overrides the score" box, the table marks them with ⛔.
