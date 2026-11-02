from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Self
from urllib.parse import quote

import httpx2
from pydantic import ValidationError

from scorm_dispatch.errors import ScormDispatchError
from scorm_dispatch.models import (
    Asset,
    AssetInput,
    Course,
    PackageRequest,
    Partner,
    PartnerInput,
    PartnerList,
    Problem,
    RuntimeAsset,
    ScormVersion,
    UsageReport,
)


def _seg(value: str) -> str:
    return quote(value, safe="")


class Client:
    """Async client of one scorm-dispatch deployment.

    Pass `http_client` to share a connection pool (you then close it yourself); otherwise the
    client owns one and `aclose()` / `async with` closes it.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str,
        *,
        http_client: httpx2.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._admin_key = admin_key
        self._owns_http = http_client is None
        self._http = http_client or httpx2.AsyncClient(timeout=timeout)
        self._timeout = timeout

    async def __aenter__(self) -> Self:
        """Enter the async context; returns the client."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the client (only the HTTP client it owns)."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client, unless it was injected."""
        if self._owns_http:
            await self._http.aclose()

    async def _send(
        self,
        method: str,
        path: str,
        *,
        admin: bool = True,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        json: object = None,
    ) -> httpx2.Response:
        h = dict(headers or {})
        if admin:  # the runtime and health routes are public: never leak the key there
            h["Authorization"] = f"Bearer {self._admin_key}"
        response = await self._http.request(
            method,
            self._base + path,
            params=params,
            headers=h,
            json=json,
            timeout=self._timeout,
        )
        if response.is_success:
            return response
        raise _error(response)

    # --- partners ---------------------------------------------------------------------------

    async def put_partner(self, partner_id: str, partner: PartnerInput) -> Partner:
        """Idempotent upsert; replaces every field."""
        r = await self._send("PUT", f"/v1/partners/{_seg(partner_id)}", json=partner)
        return Partner.model_validate_json(r.content)

    async def get_partner(self, partner_id: str) -> Partner:
        """Fetch one partner (404 if missing)."""
        r = await self._send("GET", f"/v1/partners/{_seg(partner_id)}")
        return Partner.model_validate_json(r.content)

    async def list_partners(self, *, limit: int = 50, offset: int = 0) -> PartnerList:
        """One page of partners ordered by id; `limit` 1-200."""
        r = await self._send("GET", "/v1/partners", params={"limit": limit, "offset": offset})
        return PartnerList.model_validate_json(r.content)

    # --- assets -----------------------------------------------------------------------------

    async def put_asset(self, asset_key: str, asset: AssetInput) -> Asset:
        """Idempotent upsert; `assetId` never changes once created."""
        r = await self._send("PUT", f"/v1/assets/{_seg(asset_key)}", json=asset)
        return Asset.model_validate_json(r.content)

    async def get_asset(self, asset_key: str) -> Asset:
        """Fetch one asset (404 if missing)."""
        r = await self._send("GET", f"/v1/assets/{_seg(asset_key)}")
        return Asset.model_validate_json(r.content)

    # --- packages and reports ---------------------------------------------------------------

    async def create_package(
        self, partner_id: str, scorm_version: ScormVersion, course: Course
    ) -> bytes:
        """Generate a SCORM package; returns the zip."""
        body: PackageRequest = {
            "partnerId": partner_id,
            "scormVersion": scorm_version,
            "course": course,
        }
        r = await self._send("POST", "/v1/packages", json=body)
        return r.content

    async def get_usage_report(self, month: str) -> UsageReport:
        """Active learners per partner for `month` (`YYYY-MM`)."""
        r = await self._send("GET", "/v1/reports/usage", params={"month": month})
        return UsageReport.model_validate_json(r.content)

    async def get_usage_report_csv(self, month: str) -> str:
        """Same report as `get_usage_report`, as RFC 4180 CSV text."""
        r = await self._send(
            "GET", "/v1/reports/usage", params={"month": month}, headers={"Accept": "text/csv"}
        )
        return r.text

    # --- runtime and operations -------------------------------------------------------------

    async def get_runtime_asset(
        self, asset_id: str, *, partner: str, learner: str, origin: str
    ) -> RuntimeAsset:
        """What a package does in the browser. Public route: sends `Origin`, never the key."""
        r = await self._send(
            "GET",
            f"/v1/runtime/assets/{_seg(asset_id)}",
            admin=False,
            params={"partner": partner, "learner": learner},
            headers={"Origin": origin},
        )
        return RuntimeAsset.model_validate_json(r.content)

    async def healthz(self) -> None:
        """Process alive. Raises `ScormDispatchError` otherwise."""
        await self._send("GET", "/healthz", admin=False)

    async def readyz(self) -> None:
        """Database reachable. Raises `ScormDispatchError` (503) otherwise."""
        await self._send("GET", "/readyz", admin=False)


def _error(response: httpx2.Response) -> ScormDispatchError:
    try:
        problem = Problem.model_validate_json(response.content)
    except ValidationError:  # a proxy's HTML page, an empty body...
        problem = Problem(
            title=response.reason_phrase,
            status=response.status_code,
            detail=response.text[:500] or None,
        )
    retry = response.headers.get("Retry-After")
    return ScormDispatchError(
        response.status_code, problem, int(retry) if retry and retry.isdigit() else None
    )
