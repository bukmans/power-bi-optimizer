"""
Power BI REST API Client
Connects to the Power BI REST API using MSAL (service principal or interactive auth)
to discover workspaces and datasets. Falls back to demo data when not configured.
"""

import os
import httpx
from typing import Optional
from engine.scorer import (
    DatasetInput, ModelHealthInput, QueryPerformanceInput,
    RefreshEfficiencyInput, UsageInput, SizeComplexityInput,
)

PBI_API = "https://api.powerbi.com/v1.0/myorg"
AUTHORITY = "https://login.microsoftonline.com/{tenant_id}"
SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]


class PBIClient:
    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.tenant_id = tenant_id or os.getenv("PBI_TENANT_ID")
        self.client_id = client_id or os.getenv("PBI_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("PBI_CLIENT_SECRET")
        self._token: Optional[str] = None

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

    async def list_workspaces(self) -> list[dict]:
        """Return all workspaces the service principal has access to."""
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{PBI_API}/groups", headers=self._headers())
            r.raise_for_status()
            return r.json().get("value", [])

    async def list_datasets(self, workspace_id: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{PBI_API}/groups/{workspace_id}/datasets",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json().get("value", [])

    async def get_refresh_history(self, workspace_id: str, dataset_id: str, top: int = 30) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{PBI_API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top={top}",
                headers=self._headers(),
            )
            if r.status_code == 404:
                return []
            r.raise_for_status()
            return r.json().get("value", [])

    async def get_reports(self, workspace_id: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{PBI_API}/groups/{workspace_id}/reports",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json().get("value", [])

    async def fetch_all_datasets(self) -> list[DatasetInput]:
        """
        Fetch and map all accessible datasets to DatasetInput objects.
        Note: BPA/memory scores require Semantic Link notebooks – these
        are set to neutral defaults here. Run Semantic Link analysis
        separately and POST results via /api/datasets/{id}/bpa-update.
        """
        workspaces = await self.list_workspaces()
        results: list[DatasetInput] = []

        for ws in workspaces:
            ws_id = ws["id"]
            ws_name = ws.get("name", "Unknown Workspace")

            try:
                datasets = await self.list_datasets(ws_id)
                reports = await self.get_reports(ws_id)
            except Exception:
                continue

            # Map dataset_id -> report count
            dataset_report_count: dict[str, int] = {}
            for rpt in reports:
                ds_id = rpt.get("datasetId", "")
                dataset_report_count[ds_id] = dataset_report_count.get(ds_id, 0) + 1

            for ds in datasets:
                ds_id = ds.get("id", "")
                ds_name = ds.get("name", "Unnamed Dataset")

                # Refresh history analysis
                try:
                    history = await self.get_refresh_history(ws_id, ds_id, top=30)
                except Exception:
                    history = []

                failure_rate, avg_duration_min = _analyze_refresh_history(history)

                results.append(DatasetInput(
                    dataset_id=ds_id,
                    dataset_name=ds_name,
                    workspace_id=ws_id,
                    workspace_name=ws_name,
                    owner=ds.get("configuredBy", "Unknown"),
                    created_date=ds.get("createdDate"),
                    last_modified=None,
                    # BPA/memory: neutral until Semantic Link notebook runs
                    model_health=ModelHealthInput(),
                    # Query performance: neutral until Query Insights are available
                    query_performance=QueryPerformanceInput(),
                    refresh_efficiency=RefreshEfficiencyInput(
                        refresh_failure_rate_pct=failure_rate,
                        avg_refresh_duration_min=avg_duration_min,
                        uses_incremental_refresh=ds.get("isRefreshable", False),
                    ),
                    usage=UsageInput(
                        report_count=dataset_report_count.get(ds_id, 0),
                        is_certified=ds.get("endorsementDetails", {}).get("endorsement") == "Certified",
                    ),
                    size_complexity=SizeComplexityInput(),
                ))

        return results


def _analyze_refresh_history(history: list[dict]) -> tuple[float, float]:
    """Compute failure rate % and average duration in minutes from refresh history."""
    if not history:
        return 0.0, 0.0

    failures = sum(1 for r in history if r.get("status") == "Failed")
    failure_rate = round(failures / len(history) * 100, 1)

    durations = []
    for r in history:
        start = r.get("startTime")
        end = r.get("endTime")
        if start and end:
            from datetime import datetime
            fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
            try:
                s = datetime.strptime(start, fmt)
                e = datetime.strptime(end, fmt)
                durations.append((e - s).total_seconds() / 60)
            except ValueError:
                pass

    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0
    return failure_rate, avg_duration
