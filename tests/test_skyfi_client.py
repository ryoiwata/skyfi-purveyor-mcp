"""Tests for SkyFiClient — all HTTP calls mocked with respx."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
import respx

from purveyor.core.skyfi_client import SkyFiClient
from purveyor.core.skyfi_types import (
    ArchiveOrderRequest,
    CreateNotificationRequest,
    DeliveryDriver,
    FeasibilityRequest,
    GetArchivesRequest,
    OrderRedeliveryRequest,
    PassPredictionRequest,
    PricingRequest,
    ProductType,
    TaskingOrderRequest,
)

SKYFI_BASE = "https://app.skyfi.com/platform-api"
TEST_API_KEY = "test-key-abc123"

# ---------------------------------------------------------------------------
# Sample fixture data
# ---------------------------------------------------------------------------

ARCHIVE_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
OWNER_ID = str(uuid.uuid4())
NOTIFICATION_ID = str(uuid.uuid4())
FEASIBILITY_ID = str(uuid.uuid4())


def _archive_json(archive_id: str = ARCHIVE_ID) -> dict:
    return {
        "archiveId": archive_id,
        "provider": "PLANET",
        "constellation": "dove",
        "productType": "DAY",
        "platformResolution": 3.0,
        "resolution": "VERY HIGH",
        "captureTimestamp": "2024-01-15T10:00:00Z",
        "cloudCoveragePercent": 5.0,
        "offNadirAngle": 10.0,
        "footprint": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "minSqKm": 1.0,
        "maxSqKm": 100.0,
        "priceForOneSquareKm": 5.0,
        "priceForOneSquareKmCents": 500,
        "priceFullScene": 500.0,
        "openData": False,
        "totalAreaSquareKm": 50.0,
        "deliveryTimeHours": 12.0,
        "gsd": 3.0,
    }


def _archive_response_json(archive_id: str = ARCHIVE_ID) -> dict:
    return {**_archive_json(archive_id), "overlapRatio": 0.85, "overlapSqkm": 42.5}


def _tasking_order_json() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "orderId": ORDER_ID,
        "itemId": ITEM_ID,
        "orderType": "TASKING",
        "orderCost": 50000,
        "ownerId": OWNER_ID,
        "status": "CREATED",
        "orderCode": "ORD-001",
        "createdAt": "2024-01-15T10:00:00Z",
        "aoi": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "aoiSqkm": 12.3,
        "windowStart": "2024-02-01T00:00:00Z",
        "windowEnd": "2024-02-28T23:59:59Z",
        "productType": "DAY",
        "resolution": "VERY HIGH",
        "downloadImageUrl": None,
        "downloadPayloadUrl": None,
    }


def _archive_order_json() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "orderId": ORDER_ID,
        "itemId": ITEM_ID,
        "orderType": "ARCHIVE",
        "orderCost": 25000,
        "ownerId": OWNER_ID,
        "status": "CREATED",
        "orderCode": "ORD-002",
        "createdAt": "2024-01-15T10:00:00Z",
        "aoi": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "aoiSqkm": 10.0,
        "archiveId": ARCHIVE_ID,
        "archive": _archive_json(),
        "downloadImageUrl": None,
        "downloadPayloadUrl": None,
    }


def _whoami_json() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "organizationId": str(uuid.uuid4()),
        "email": "test@example.com",
        "firstName": "Test",
        "lastName": "User",
        "isDemoAccount": False,
        "currentBudgetUsage": 10000,
        "budgetAmount": 100000,
        "hasValidSharedCard": True,
    }


def _notification_json() -> dict:
    return {
        "id": NOTIFICATION_ID,
        "ownerId": OWNER_ID,
        "aoi": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "gsdMin": None,
        "gsdMax": None,
        "productType": None,
        "webhookUrl": "https://example.com/webhook",
        "createdAt": "2024-01-15T10:00:00Z",
    }


def _feasibility_json(status: str = "PENDING") -> dict:
    return {
        "id": FEASIBILITY_ID,
        "validUntil": "2024-01-15T11:00:00Z",
        "overallScore": {
            "feasibility": 0.85,
            "weatherScore": {"weatherScore": 0.9},
            "providerScore": {"score": 0.8, "providerScores": []},
        } if status == "COMPLETE" else None,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> SkyFiClient:
    """SkyFiClient instance for testing."""
    return SkyFiClient(api_key=TEST_API_KEY)


# ---------------------------------------------------------------------------
# Auth header tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_header_sent_on_whoami(client: SkyFiClient) -> None:
    """X-Skyfi-Api-Key header must be sent on every request."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(return_value=httpx.Response(200, json=_whoami_json()))
        await client.whoami()
        request = mock.calls.last.request
        assert request.headers.get("x-skyfi-api-key") == TEST_API_KEY


@pytest.mark.asyncio
async def test_auth_header_sent_on_search(client: SkyFiClient) -> None:
    """Auth header present on POST requests too."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/archives").mock(
            return_value=httpx.Response(
                200, json={"archives": [_archive_response_json()], "nextPage": None}
            )
        )
        req = GetArchivesRequest(aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")
        await client.search_archives(req)
        request = mock.calls.last.request
        assert request.headers.get("x-skyfi-api-key") == TEST_API_KEY


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whoami_parses_response(client: SkyFiClient) -> None:
    """whoami returns a correctly parsed WhoamiUser."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(return_value=httpx.Response(200, json=_whoami_json()))
        user = await client.whoami()
        assert user.email == "test@example.com"
        assert user.first_name == "Test"
        assert user.budget_amount == 100000


# ---------------------------------------------------------------------------
# search_archives
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_archives_returns_results(client: SkyFiClient) -> None:
    """search_archives returns parsed ArchiveResponse list."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/archives").mock(
            return_value=httpx.Response(
                200,
                json={"archives": [_archive_response_json()], "nextPage": None, "total": 1},
            )
        )
        req = GetArchivesRequest(aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", page_size=25)
        result = await client.search_archives(req)
        assert len(result.archives) == 1
        assert result.archives[0].archive_id == ARCHIVE_ID
        assert result.archives[0].overlap_ratio == 0.85


@pytest.mark.asyncio
async def test_search_archives_sends_correct_body(client: SkyFiClient) -> None:
    """search_archives sends the AOI in the request body."""
    aoi = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/archives").mock(
            return_value=httpx.Response(200, json={"archives": [], "nextPage": None})
        )
        req = GetArchivesRequest(aoi=aoi)
        await client.search_archives(req)
        import json
        body = json.loads(mock.calls.last.request.content)
        assert body["aoi"] == aoi


# ---------------------------------------------------------------------------
# get_archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_archive_parses_response(client: SkyFiClient) -> None:
    """get_archive returns a parsed Archive model."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get(f"/archives/{ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_archive_json())
        )
        archive = await client.get_archive(ARCHIVE_ID)
        assert archive.archive_id == ARCHIVE_ID
        assert archive.provider.value == "PLANET"


# ---------------------------------------------------------------------------
# get_pricing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pricing_returns_dict(client: SkyFiClient) -> None:
    """get_pricing returns the raw pricing dict."""
    pricing_data = {"tiers": [{"resolution": "HIGH", "pricePerSqKm": 5.0}]}
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/pricing").mock(return_value=httpx.Response(200, json=pricing_data))
        result = await client.get_pricing(None)
        assert "tiers" in result


@pytest.mark.asyncio
async def test_get_pricing_with_aoi(client: SkyFiClient) -> None:
    """get_pricing sends AOI when provided."""
    aoi = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/pricing").mock(return_value=httpx.Response(200, json={}))
        req = PricingRequest(aoi=aoi)
        await client.get_pricing(req)
        import json
        body = json.loads(mock.calls.last.request.content)
        assert body["aoi"] == aoi


# ---------------------------------------------------------------------------
# feasibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_feasibility_task(client: SkyFiClient) -> None:
    """create_feasibility_task returns parsed FeasibilityResponse."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/feasibility").mock(
            return_value=httpx.Response(200, json=_feasibility_json())
        )
        req = FeasibilityRequest(
            aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            product_type=ProductType.DAY,
            resolution="VERY HIGH",
            start_date=datetime(2024, 2, 1, tzinfo=UTC),
            end_date=datetime(2024, 2, 28, tzinfo=UTC),
        )
        result = await client.create_feasibility_task(req)
        assert str(result.id) == FEASIBILITY_ID


@pytest.mark.asyncio
async def test_get_feasibility_status(client: SkyFiClient) -> None:
    """get_feasibility_status returns updated feasibility data."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get(f"/feasibility/{FEASIBILITY_ID}").mock(
            return_value=httpx.Response(200, json=_feasibility_json("COMPLETE"))
        )
        result = await client.get_feasibility_status(FEASIBILITY_ID)
        assert result.overall_score is not None
        assert result.overall_score.feasibility == 0.85


# ---------------------------------------------------------------------------
# pass predictions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pass_predictions(client: SkyFiClient) -> None:
    """get_pass_predictions returns parsed PassPredictionResponse."""
    pass_data = {
        "passes": [
            {
                "provider": "PLANET",
                "satname": "dove-1",
                "satid": "SAT-001",
                "noradid": "12345",
                "node": "node1",
                "productType": "DAY",
                "resolution": "VERY HIGH",
                "lat": 34.05,
                "lon": -118.25,
                "passDate": "2024-02-15T14:30:00Z",
                "meanT": 90,
                "offNadirAngle": 15.0,
                "solarElevationAngle": 45.0,
                "minSquareKms": 1.0,
                "maxSquareKms": 100.0,
                "priceForOneSquareKm": 5.0,
                "gsdDegMin": 0.00003,
                "gsdDegMax": 0.00004,
            }
        ]
    }
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/feasibility/pass-prediction").mock(
            return_value=httpx.Response(200, json=pass_data)
        )
        req = PassPredictionRequest(
            aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            from_date=datetime(2024, 2, 1, tzinfo=UTC),
            to_date=datetime(2024, 2, 28, tzinfo=UTC),
        )
        result = await client.get_pass_predictions(req)
        assert len(result.passes) == 1
        assert result.passes[0].satname == "dove-1"


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tasking_order(client: SkyFiClient) -> None:
    """create_tasking_order returns parsed TaskingOrderResponse."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/order-tasking").mock(
            return_value=httpx.Response(200, json=_tasking_order_json())
        )
        req = TaskingOrderRequest(
            aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            window_start=datetime(2024, 2, 1, tzinfo=UTC),
            window_end=datetime(2024, 2, 28, tzinfo=UTC),
            product_type=ProductType.DAY,
            resolution="VERY HIGH",
        )
        result = await client.create_tasking_order(req)
        assert result.order_cost == 50000
        assert result.status.value == "CREATED"


@pytest.mark.asyncio
async def test_create_archive_order(client: SkyFiClient) -> None:
    """create_archive_order returns parsed ArchiveOrderResponse."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/order-archive").mock(
            return_value=httpx.Response(200, json=_archive_order_json())
        )
        req = ArchiveOrderRequest(
            aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            archive_id=ARCHIVE_ID,
        )
        result = await client.create_archive_order(req)
        assert result.archive_id == ARCHIVE_ID
        assert result.order_cost == 25000


def test_archive_order_request_none_driver_excluded() -> None:
    """model_dump_skyfi omits deliveryDriver/deliveryParams when driver is NONE.

    SkyFi's /order-archive endpoint rejects requests with deliveryDriver="NONE";
    the field must be absent when no delivery is configured.
    """
    req = ArchiveOrderRequest(
        aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        archive_id=str(uuid.uuid4()),
    )
    assert req.delivery_driver == DeliveryDriver.NONE
    payload = req.model_dump_skyfi()
    assert "deliveryDriver" not in payload
    assert "deliveryParams" not in payload


def test_tasking_order_request_none_driver_excluded() -> None:
    """model_dump_skyfi omits deliveryDriver/deliveryParams when driver is NONE."""
    req = TaskingOrderRequest(
        aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        window_start=datetime(2024, 2, 1, tzinfo=UTC),
        window_end=datetime(2024, 2, 28, tzinfo=UTC),
        product_type=ProductType.DAY,
        resolution="VERY HIGH",
    )
    assert req.delivery_driver == DeliveryDriver.NONE
    payload = req.model_dump_skyfi()
    assert "deliveryDriver" not in payload
    assert "deliveryParams" not in payload


def test_archive_order_request_s3_driver_included() -> None:
    """model_dump_skyfi includes deliveryDriver when a real driver is set."""
    req = ArchiveOrderRequest(
        aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        archive_id=str(uuid.uuid4()),
        delivery_driver=DeliveryDriver.S3,
    )
    payload = req.model_dump_skyfi()
    assert payload["deliveryDriver"] == "S3"


@pytest.mark.asyncio
async def test_list_orders(client: SkyFiClient) -> None:
    """list_orders returns parsed ListOrdersResponse."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/orders").mock(
            return_value=httpx.Response(
                200, json={"total": 1, "orders": [_tasking_order_json()]}
            )
        )
        result = await client.list_orders()
        assert result.total == 1
        assert len(result.orders) == 1


@pytest.mark.asyncio
async def test_get_order_tasking(client: SkyFiClient) -> None:
    """get_order returns TaskingOrderResponse for tasking orders."""
    from purveyor.core.skyfi_types import TaskingOrderResponse

    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get(f"/orders/{ORDER_ID}").mock(
            return_value=httpx.Response(200, json=_tasking_order_json())
        )
        result = await client.get_order(ORDER_ID)
        assert isinstance(result, TaskingOrderResponse)


@pytest.mark.asyncio
async def test_get_order_archive(client: SkyFiClient) -> None:
    """get_order returns ArchiveOrderResponse for archive orders."""
    from purveyor.core.skyfi_types import ArchiveOrderResponse

    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get(f"/orders/{ORDER_ID}").mock(
            return_value=httpx.Response(200, json=_archive_order_json())
        )
        result = await client.get_order(ORDER_ID)
        assert isinstance(result, ArchiveOrderResponse)


@pytest.mark.asyncio
async def test_request_redelivery(client: SkyFiClient) -> None:
    """request_redelivery returns updated order."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post(f"/orders/{ORDER_ID}/redelivery").mock(
            return_value=httpx.Response(200, json=_tasking_order_json())
        )
        req = OrderRedeliveryRequest(
            delivery_driver=DeliveryDriver.S3,
            delivery_params={"bucket": "test"},
        )
        result = await client.request_redelivery(ORDER_ID, req)
        assert result is not None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_notification(client: SkyFiClient) -> None:
    """create_notification returns parsed NotificationResponse."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.post("/notifications").mock(
            return_value=httpx.Response(200, json=_notification_json())
        )
        req = CreateNotificationRequest(
            aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            webhook_url="https://example.com/webhook",
        )
        result = await client.create_notification(req)
        assert str(result.id) == NOTIFICATION_ID


@pytest.mark.asyncio
async def test_list_notifications(client: SkyFiClient) -> None:
    """list_notifications returns parsed response."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/notifications").mock(
            return_value=httpx.Response(
                200, json={"total": 1, "notifications": [_notification_json()]}
            )
        )
        result = await client.list_notifications()
        assert result.total == 1


@pytest.mark.asyncio
async def test_get_notification(client: SkyFiClient) -> None:
    """get_notification returns NotificationWithHistory."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get(f"/notifications/{NOTIFICATION_ID}").mock(
            return_value=httpx.Response(
                200, json={**_notification_json(), "history": []}
            )
        )
        result = await client.get_notification(NOTIFICATION_ID)
        assert str(result.id) == NOTIFICATION_ID
        assert result.history == []


@pytest.mark.asyncio
async def test_delete_notification(client: SkyFiClient) -> None:
    """delete_notification succeeds and returns StatusResponse."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.delete(f"/notifications/{NOTIFICATION_ID}").mock(
            return_value=httpx.Response(200, json={"status": "deleted"})
        )
        result = await client.delete_notification(NOTIFICATION_ID)
        assert result.status == "deleted"


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_429(client: SkyFiClient) -> None:
    """Client retries on 429 and eventually succeeds."""
    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(429, json={"detail": "rate limited"})
        return httpx.Response(200, json=_whoami_json())

    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(side_effect=side_effect)
        result = await client.whoami()
        assert call_count == 3
        assert result.email == "test@example.com"


@pytest.mark.asyncio
async def test_retry_on_500(client: SkyFiClient) -> None:
    """Client retries on 500 server error."""
    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, json={"detail": "internal error"})
        return httpx.Response(200, json=_whoami_json())

    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(side_effect=side_effect)
        result = await client.whoami()
        assert call_count == 2
        assert result.email == "test@example.com"


@pytest.mark.asyncio
async def test_fails_after_max_retries(client: SkyFiClient) -> None:
    """After 3 retries, the exception is raised."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(
            return_value=httpx.Response(503, json={"detail": "unavailable"})
        )
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.whoami()
        assert exc_info.value.response.status_code == 503


@pytest.mark.asyncio
async def test_retry_on_502(client: SkyFiClient) -> None:
    """502 Bad Gateway is retried."""
    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(502, json={})
        return httpx.Response(200, json=_whoami_json())

    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(side_effect=side_effect)
        await client.whoami()
        assert call_count == 2


# ---------------------------------------------------------------------------
# Extra fields are ignored (DESIGN_DECISIONS §18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_fields_ignored_in_response(client: SkyFiClient) -> None:
    """Extra fields in SkyFi responses do not cause validation errors."""
    whoami_with_extras = {**_whoami_json(), "unknownFutureField": "some_value", "anotherNew": 42}
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/auth/whoami").mock(
            return_value=httpx.Response(200, json=whoami_with_extras)
        )
        result = await client.whoami()
        assert result.email == "test@example.com"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_archives_page(client: SkyFiClient) -> None:
    """search_archives_page calls GET /archives with page param."""
    with respx.mock(base_url=SKYFI_BASE) as mock:
        mock.get("/archives").mock(
            return_value=httpx.Response(
                200, json={"archives": [_archive_response_json()], "nextPage": None}
            )
        )
        result = await client.search_archives_page("abc123")
        assert len(result.archives) == 1
        # Verify the page param was sent
        params = dict(mock.calls.last.request.url.params)
        assert params.get("page") == "abc123"
