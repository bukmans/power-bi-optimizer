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
