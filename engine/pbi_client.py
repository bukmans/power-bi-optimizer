"""
Power BI REST API Client
Connects to the Power BI REST API using MSAL (service principal or interactive auth)
to discover workspaces and datasets. Falls back to demo data when not configured.
"""

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from typing import Optional
from engine.scorer import (
    DatasetInput, ModelHealthInput, QueryPerformanceInput,
    RefreshEfficiencyInput, UsageInput, SizeComplexityInput,
)

PBI_API = "https://api.powerbi.com/v1.0/myorg"
AUTHORITY = "https://login.microsoftonline.com/{tenant_id}"
SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

REFRESH_WINDOW_DAYS = 30
MAX_CONCURRENT_REQUESTS = 8


class PBIClient:
    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,  # injectable for tests
    ):
        self.tenant_id = tenant_id or os.getenv("PBI_TENANT_ID")
        self.client_id = client_id or os.getenv("PBI_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("PBI_CLIENT_SECRET")
        self._token: Optional[str] = None
        self._transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    def _get_token(self) -> str:
        """Acquire OAuth2 token via MSAL client credentials."""
        try:
            import msal
            app = msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=AUTHORITY.format(tenant_id=self.tenant_id),
            )
            result = app.acquire_token_for_client(scopes=SCOPE)
            if "access_token" not in result:
                raise ValueError(f"Token error: {result.get('error_description', 'Unknown error')}")
            return result["access_token"]
        except ImportError:
            raise RuntimeError("msal package not installed. Run: pip install msal")

    def _headers(self) -> dict:
        if not self._token:
            self._token = self._get_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=30.0)

    async def _get_values(self, client: httpx.AsyncClient, url: str, allow_404: bool = False) -> list[dict]:
        r = await client.get(url, headers=self._headers())
        if allow_404 and r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json().get("value", [])

    async def list_workspaces(self, client: httpx.AsyncClient) -> list[dict]:
        """Return all workspaces the service principal has access to."""
        return await self._get_values(client, f"{PBI_API}/groups")

    async def list_datasets(self, client: httpx.AsyncClient, workspace_id: str) -> list[dict]:
        return await self._get_values(client, f"{PBI_API}/groups/{workspace_id}/datasets")

    async def get_refresh_history(self, client: httpx.AsyncClient, workspace_id: str,
                                  dataset_id: str, top: int = 60) -> list[dict]:
        return await self._get_values(
            client, f"{PBI_API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top={top}",
            allow_404=True,
        )

    async def get_reports(self, client: httpx.AsyncClient, workspace_id: str) -> list[dict]:
        return await self._get_values(client, f"{PBI_API}/groups/{workspace_id}/reports")

    async def fetch_all_datasets(self) -> list[DatasetInput]:
        """
        Fetch and map all accessible datasets to DatasetInput objects.

        Only refresh history, report count and endorsement are available from these
        endpoints. Everything else is left as None (not measured) so it is excluded
        from the score – run the Semantic Link notebook and POST results via
        /api/datasets/{id}/bpa-update, and post usage from the activity log.
        """
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        async with self._http() as client:
            workspaces = await self.list_workspaces(client)

            async def load_workspace(ws: dict) -> list[DatasetInput]:
                ws_id = ws["id"]
                ws_name = ws.get("name", "Unknown Workspace")
                try:
                    async with sem:
                        datasets = await self.list_datasets(client, ws_id)
                    async with sem:
                        reports = await self.get_reports(client, ws_id)
                except httpx.HTTPError:
                    return []  # no access to this workspace's contents

                report_count: dict[str, int] = {}
                for rpt in reports:
                    ds_id = rpt.get("datasetId", "")
                    report_count[ds_id] = report_count.get(ds_id, 0) + 1

                async def load_dataset(ds: dict) -> DatasetInput:
                    ds_id = ds.get("id", "")
                    try:
                        async with sem:
                            history = await self.get_refresh_history(client, ws_id, ds_id)
                    except httpx.HTTPError:
                        history = []
                    failure_rate, avg_duration_min = _analyze_refresh_history(history)
                    endorsement = (ds.get("endorsementDetails") or {}).get("endorsement")

                    return DatasetInput(
                        dataset_id=ds_id,
                        dataset_name=ds.get("name", "Unnamed Dataset"),
                        workspace_id=ws_id,
                        workspace_name=ws_name,
                        owner=ds.get("configuredBy", "Unknown"),
                        created_date=ds.get("createdDate"),
                        last_modified=None,
                        # Not available from the REST API – left unmeasured
                        model_health=ModelHealthInput(),
                        query_performance=QueryPerformanceInput(),
                        size_complexity=SizeComplexityInput(),
                        refresh_efficiency=RefreshEfficiencyInput(
                            refresh_failure_rate_pct=failure_rate,
                            avg_refresh_duration_min=avg_duration_min,
                            # isRefreshable only means the dataset *can* be refreshed; the
                            # REST API does not say whether incremental refresh is configured
                            uses_incremental_refresh=None,
                        ),
                        usage=UsageInput(
                            report_count=report_count.get(ds_id, 0),
                            is_certified=endorsement == "Certified",
                        ),
                    )

                return await asyncio.gather(*(load_dataset(ds) for ds in datasets))

            per_ws = await asyncio.gather(*(load_workspace(ws) for ws in workspaces))

        return [ds for group in per_ws for ds in group]


_FRACTION = re.compile(r"\.(\d+)")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse Power BI timestamps: with or without fractional seconds (up to 7 digits) and 'Z'."""
    if not value:
        return None
    s = value.strip().replace("Z", "+00:00")
    s = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), s, count=1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _analyze_refresh_history(history: list[dict], now: Optional[datetime] = None
                             ) -> tuple[Optional[float], Optional[float]]:
    """Failure rate % and average duration (minutes) over finished refreshes in the last 30 days.

    Returns (None, None) when there is nothing to measure. In-progress ("Unknown"),
    cancelled and disabled refreshes are neither successes nor failures and are skipped.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=REFRESH_WINDOW_DAYS)

    finished = []
    for r in history:
        if r.get("status") not in ("Completed", "Failed"):
            continue
        start = _parse_ts(r.get("startTime"))
        if start is None or start < cutoff:
            continue
        finished.append((r["status"], start, _parse_ts(r.get("endTime"))))

    if not finished:
        return None, None

    failures = sum(1 for status, _, _ in finished if status == "Failed")
    failure_rate = round(failures / len(finished) * 100, 1)

    durations = [(end - start).total_seconds() / 60 for _, start, end in finished if end]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    return failure_rate, avg_duration
