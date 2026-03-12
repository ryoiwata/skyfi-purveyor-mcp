"""SkyFi Platform API HTTP client with retry logic and structured logging."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from purveyor.core.skyfi_types import (
    Archive,
    ArchiveOrderRequest,
    ArchiveOrderResponse,
    CreateNotificationRequest,
    DemoDeliveryRequest,
    DemoDeliveryResponse,
    FeasibilityRequest,
    FeasibilityResponse,
    GetArchivesRequest,
    GetArchivesResponse,
    ListNotificationsResponse,
    ListOrdersResponse,
    NotificationResponse,
    NotificationWithHistory,
    OrderInfo,
    OrderRedeliveryRequest,
    OrderType,
    PassPredictionRequest,
    PassPredictionResponse,
    PricingRequest,
    SortColumn,
    SortDirection,
    StatusResponse,
    TaskingOrderRequest,
    TaskingOrderResponse,
    WhoamiUser,
)

log = structlog.get_logger(__name__)

SKYFI_BASE_URL = "https://app.skyfi.com/platform-api"

# HTTP status codes that warrant a retry
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception is a retryable HTTP error."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUSES
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


_F = TypeVar("_F", bound=Callable[..., Any])


def _skyfi_retry(fn: _F) -> _F:
    """Tenacity retry decorator for SkyFi API calls (typed wrapper)."""
    decorated = retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30) + wait_random(0, 0.5),
        reraise=True,
    )(fn)
    return decorated


class SkyFiClient:
    """Async HTTP client wrapping the SkyFi Platform API.

    All methods are coroutines. Authentication is via the X-Skyfi-Api-Key header.
    Retry logic uses tenacity with exponential backoff + jitter on 429 / 5xx.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = SKYFI_BASE_URL,
    ) -> None:
        """Create a new SkyFiClient.

        Args:
            api_key: SkyFi Platform API key.
            base_url: Base URL (default: production endpoint).
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-Skyfi-Api-Key": api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def __aenter__(self) -> SkyFiClient:
        """Support async context manager."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Close the underlying HTTP client."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute a single HTTP request with logging and raise on error."""
        start = time.monotonic()
        response = await self._client.request(method, path, json=json, params=params)
        duration_ms = (time.monotonic() - start) * 1000
        log.info(
            "skyfi_api_request",
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 1),
        )
        response.raise_for_status()
        return response

    @_skyfi_retry
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET with retry."""
        return await self._request("GET", path, params=params)

    @_skyfi_retry
    async def _post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        """POST with retry."""
        return await self._request("POST", path, json=json)

    @_skyfi_retry
    async def _delete(self, path: str) -> httpx.Response:
        """DELETE with retry."""
        return await self._request("DELETE", path)

    # ------------------------------------------------------------------
    # Health / auth
    # ------------------------------------------------------------------

    async def ping(self) -> dict[str, Any]:
        """GET /ping — basic connectivity check."""
        resp = await self._get("/ping")
        return resp.json()  # type: ignore[no-any-return]

    async def health_check(self) -> StatusResponse:
        """GET /health_check — service status."""
        resp = await self._get("/health_check")
        return StatusResponse.model_validate(resp.json())

    async def whoami(self) -> WhoamiUser:
        """GET /auth/whoami — current user info."""
        resp = await self._get("/auth/whoami")
        return WhoamiUser.model_validate(resp.json())

    # ------------------------------------------------------------------
    # Archives
    # ------------------------------------------------------------------

    async def search_archives(self, request: GetArchivesRequest) -> GetArchivesResponse:
        """POST /archives — search the imagery catalog."""
        resp = await self._post("/archives", json=request.model_dump_skyfi())
        return GetArchivesResponse.model_validate(resp.json())

    async def search_archives_page(self, page_url: str) -> GetArchivesResponse:
        """GET /archives?page=<hash> — continue paginating search results.

        Args:
            page_url: The nextPage value returned by a previous search.
        """
        resp = await self._get("/archives", params={"page": page_url})
        return GetArchivesResponse.model_validate(resp.json())

    async def get_archive(self, archive_id: str) -> Archive:
        """GET /archives/{archive_id} — full metadata for a single archive image."""
        resp = await self._get(f"/archives/{archive_id}")
        return Archive.model_validate(resp.json())

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    async def get_pricing(self, request: PricingRequest | None) -> dict[str, Any]:
        """POST /pricing — get the full pricing matrix."""
        body = request.model_dump(exclude_none=True) if request else {}
        resp = await self._post("/pricing", json=body)
        return resp.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Feasibility
    # ------------------------------------------------------------------

    async def create_feasibility_task(self, request: FeasibilityRequest) -> FeasibilityResponse:
        """POST /feasibility — create a feasibility assessment task."""
        resp = await self._post("/feasibility", json=request.model_dump_skyfi())
        return FeasibilityResponse.model_validate(resp.json())

    async def get_feasibility_status(self, feasibility_id: str) -> FeasibilityResponse:
        """GET /feasibility/{feasibility_id} — poll feasibility task status."""
        resp = await self._get(f"/feasibility/{feasibility_id}")
        return FeasibilityResponse.model_validate(resp.json())

    async def get_pass_predictions(
        self, request: PassPredictionRequest
    ) -> PassPredictionResponse:
        """POST /feasibility/pass-prediction — find satellite passes over an AOI."""
        resp = await self._post(
            "/feasibility/pass-prediction", json=request.model_dump_skyfi()
        )
        return PassPredictionResponse.model_validate(resp.json())

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def create_tasking_order(
        self, request: TaskingOrderRequest
    ) -> TaskingOrderResponse:
        """POST /order-tasking — create a satellite tasking order."""
        resp = await self._post("/order-tasking", json=request.model_dump_skyfi())
        return TaskingOrderResponse.model_validate(resp.json())

    async def create_archive_order(
        self, request: ArchiveOrderRequest
    ) -> ArchiveOrderResponse:
        """POST /order-archive — create an archive imagery order."""
        resp = await self._post("/order-archive", json=request.model_dump_skyfi())
        return ArchiveOrderResponse.model_validate(resp.json())

    async def list_orders(
        self,
        order_type: OrderType | None = None,
        page: int = 0,
        page_size: int = 25,
        sort_columns: list[SortColumn] | None = None,
        sort_directions: list[SortDirection] | None = None,
    ) -> ListOrdersResponse:
        """GET /orders — list orders with optional filtering and sorting."""
        params: dict[str, Any] = {
            "pageNumber": page,
            "pageSize": page_size,
        }
        if order_type is not None:
            params["orderType"] = order_type.value
        if sort_columns:
            params["sortColumns"] = [c.value for c in sort_columns]
        if sort_directions:
            params["sortDirections"] = [d.value for d in sort_directions]
        resp = await self._get("/orders", params=params)
        return ListOrdersResponse.model_validate(resp.json())

    async def get_order(self, order_id: str) -> OrderInfo:
        """GET /orders/{order_id} — get full order details.

        Returns either a TaskingOrderResponse or ArchiveOrderResponse depending
        on the order type.
        """
        resp = await self._get(f"/orders/{order_id}")
        data = resp.json()
        order_type = data.get("orderType")
        if order_type == "ARCHIVE":
            return ArchiveOrderResponse.model_validate(data)
        return TaskingOrderResponse.model_validate(data)

    async def get_deliverable_url(self, order_id: str, deliverable_type: str) -> str:
        """GET /orders/{order_id}/{deliverable_type} — signed download URL.

        The endpoint redirects to the actual download URL. We follow the
        redirect and return the final URL.
        """
        # Use a client that does NOT follow redirects so we can capture the Location header
        async with httpx.AsyncClient(
            headers={
                "X-Skyfi-Api-Key": self._api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
            follow_redirects=False,
        ) as client:
            resp = await client.get(
                f"{self._base_url}/orders/{order_id}/{deliverable_type}"
            )
        # 302/307 redirect — extract the Location header
        if resp.is_redirect:
            location: str = resp.headers.get("location") or ""
            log.info(
                "skyfi_api_request",
                method="GET",
                path=f"/orders/{order_id}/{deliverable_type}",
                status_code=resp.status_code,
            )
            return location
        # If not a redirect, the body may contain the URL directly
        resp.raise_for_status()
        body: Any = resp.json()
        if isinstance(body, str):
            return body
        url = body.get("url", "")
        return str(url)

    async def request_redelivery(
        self, order_id: str, request: OrderRedeliveryRequest
    ) -> OrderInfo:
        """POST /orders/{order_id}/redelivery — reschedule delivery."""
        resp = await self._post(
            f"/orders/{order_id}/redelivery", json=request.model_dump_skyfi()
        )
        data = resp.json()
        order_type = data.get("orderType")
        if order_type == "ARCHIVE":
            return ArchiveOrderResponse.model_validate(data)
        return TaskingOrderResponse.model_validate(data)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    async def create_notification(
        self, request: CreateNotificationRequest
    ) -> NotificationResponse:
        """POST /notifications — create an AOI monitoring notification."""
        resp = await self._post("/notifications", json=request.model_dump_skyfi())
        return NotificationResponse.model_validate(resp.json())

    async def list_notifications(
        self, page: int = 0, page_size: int = 10
    ) -> ListNotificationsResponse:
        """GET /notifications — list active notification monitors."""
        resp = await self._get(
            "/notifications", params={"pageNumber": page, "pageSize": page_size}
        )
        return ListNotificationsResponse.model_validate(resp.json())

    async def get_notification(self, notification_id: str) -> NotificationWithHistory:
        """GET /notifications/{notification_id} — notification with event history."""
        resp = await self._get(f"/notifications/{notification_id}")
        return NotificationWithHistory.model_validate(resp.json())

    async def delete_notification(self, notification_id: str) -> StatusResponse:
        """DELETE /notifications/{notification_id} — remove an AOI monitor."""
        resp = await self._delete(f"/notifications/{notification_id}")
        # The API may return empty body on success
        if resp.content:
            return StatusResponse.model_validate(resp.json())
        return StatusResponse(status="deleted")

    # ------------------------------------------------------------------
    # Demo delivery
    # ------------------------------------------------------------------

    async def demo_delivery(self, request: DemoDeliveryRequest) -> DemoDeliveryResponse:
        """POST /demo-delivery — test delivery to a customer bucket."""
        resp = await self._post("/demo-delivery", json=request.model_dump_skyfi())
        return DemoDeliveryResponse.model_validate(resp.json())
