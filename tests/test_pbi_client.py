import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from engine.pbi_client import PBIClient, _analyze_refresh_history, _parse_ts
from engine.scorer import MigrationDecision, score_dataset

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def _iso(dt, frac=True):
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + (".123Z" if frac else "Z")


def _refresh(status, days_ago, minutes=10, frac=True):
    start = NOW - timedelta(days=days_ago)
    r = {"status": status, "startTime": _iso(start, frac)}
    if status != "Unknown":
        r["endTime"] = _iso(start + timedelta(minutes=minutes), frac)
    return r


# ── _parse_ts ────────────────────────────────────────────────────────────────
def test_parse_timestamp_formats():
    assert _parse_ts("2026-10-01T10:00:00Z") == datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    assert _parse_ts("2026-10-01T10:00:00.123Z").microsecond == 123000
    assert _parse_ts("2026-10-01T10:00:00.1234567Z").microsecond == 123456  # 7-digit .NET ticks
    assert _parse_ts("2026-10-01T10:00:00+00:00") is not None
    assert _parse_ts("garbage") is None
    assert _parse_ts(None) is None


# ── _analyze_refresh_history ─────────────────────────────────────────────────
def test_no_history_is_unmeasured():
    assert _analyze_refresh_history([], now=NOW) == (None, None)


def test_in_progress_and_cancelled_are_not_counted():
    history = [_refresh("Completed", 1), _refresh("Failed", 2), _refresh("Unknown", 0),
               _refresh("Cancelled", 3), _refresh("Disabled", 4)]
    rate, _ = _analyze_refresh_history(history, now=NOW)
    assert rate == 50.0


def test_only_last_30_days_used():
    history = [_refresh("Completed", 1)] + [_refresh("Failed", 40 + i) for i in range(5)]
    rate, _ = _analyze_refresh_history(history, now=NOW)
    assert rate == 0.0


def test_durations_without_fractional_seconds_are_parsed():
    history = [_refresh("Completed", 1, minutes=30, frac=False), _refresh("Completed", 2, minutes=10)]
    _, avg = _analyze_refresh_history(history, now=NOW)
    assert avg == 20.0


def test_only_old_or_unfinished_refreshes_is_unmeasured():
    history = [_refresh("Unknown", 0), _refresh("Completed", 45)]
    assert _analyze_refresh_history(history, now=NOW) == (None, None)


# ── fetch_all_datasets against a mocked Power BI API ─────────────────────────
def _mock_api(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/groups"):
        return httpx.Response(200, json={"value": [{"id": "ws1", "name": "Finance"}]})
    if path.endswith("/groups/ws1/datasets"):
        return httpx.Response(200, json={"value": [
            {"id": "d1", "name": "Sales", "configuredBy": "a@x.org", "isRefreshable": True,
             "endorsementDetails": {"endorsement": "Certified"}},
            {"id": "d2", "name": "NoHistory", "configuredBy": "b@x.org", "isRefreshable": True,
             "endorsementDetails": None},
        ]})
    if path.endswith("/groups/ws1/reports"):
        return httpx.Response(200, json={"value": [{"datasetId": "d1"}, {"datasetId": "d1"}]})
    if path.endswith("/datasets/d1/refreshes"):
        # Real clock here: fetch_all_datasets filters on the actual current date
        start = datetime.now(timezone.utc) - timedelta(days=1)
        return httpx.Response(200, json={"value": [
            {"status": "Completed", "startTime": _iso(start), "endTime": _iso(start + timedelta(minutes=12))},
            {"status": "Failed", "startTime": _iso(start), "endTime": _iso(start + timedelta(minutes=2))},
        ]})
    if path.endswith("/datasets/d2/refreshes"):
        return httpx.Response(200, json={"value": []})
    return httpx.Response(404)


def _client():
    c = PBIClient("t", "c", "s", transport=httpx.MockTransport(_mock_api))
    c._get_token = lambda: "token"
    return c


def test_fetch_maps_live_data_without_inventing_metrics():
    datasets = {d.dataset_id: d for d in asyncio.run(_client().fetch_all_datasets())}
    d1, d2 = datasets["d1"], datasets["d2"]

    # isRefreshable must not be read as "uses incremental refresh"
    assert d1.refresh_efficiency.uses_incremental_refresh is None
    assert d1.refresh_efficiency.refresh_failure_rate_pct == 50.0
    assert d1.refresh_efficiency.avg_refresh_duration_min == 7.0
    assert d1.usage.report_count == 2
    assert d1.usage.is_certified is True
    assert d1.usage.active_users_30d is None
    assert d1.model_health.bpa_critical_count is None

    # null endorsementDetails must not crash; no history = refresh not measured
    assert d2.usage.is_certified is False
    assert d2.refresh_efficiency.refresh_failure_rate_pct is None


def test_live_datasets_need_assessment_until_enriched():
    for ds in asyncio.run(_client().fetch_all_datasets()):
        assert score_dataset(ds).decision == MigrationDecision.NEEDS_ASSESSMENT


# ── /api/connect ─────────────────────────────────────────────────────────────
def test_connect_loads_live_data_as_needs_assessment(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "PBIClient", lambda **kw: _client())
    r = client.post("/api/connect", json={"tenant_id": "t", "client_id": "c", "client_secret": "s"})
    assert r.status_code == 200, r.text
    assert r.json()["dataset_count"] == 2
    s = client.get("/api/summary").json()
    assert s["mode"] == "live"
    assert s["needs_assessment"] == 2 and s["migrate"] == 0


def test_connect_with_no_datasets_gives_clear_message(client, monkeypatch):
    import app as app_module

    class Empty:
        async def fetch_all_datasets(self):
            return []
    monkeypatch.setattr(app_module, "PBIClient", lambda **kw: Empty())
    r = client.post("/api/connect", json={"tenant_id": "t", "client_id": "c", "client_secret": "s"})
    assert r.status_code == 400
    assert r.json()["detail"] == "No datasets found. Check service principal workspace access."
