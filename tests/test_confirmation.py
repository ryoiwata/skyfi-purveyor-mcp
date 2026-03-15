"""Tests for confirmation token encryption, decryption, and order confirmation flow."""

from __future__ import annotations

import asyncio
import datetime
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastapi import Request

from purveyor.core.confirmation import (
    cancel_confirmation,
    compute_token_hash,
    confirm_order,
    create_confirmation,
    decrypt_confirmation_token,
    encrypt_confirmation_token,
    get_confirmation_by_token,
    resolve_base_url,
)
from purveyor.core.errors import ErrorCode, ToolError
from purveyor.core.skyfi_types import (
    DeliveryStatus,
    OrderType,
    TaskingOrderResponse,
)

# Short test polygon reused across tests (keeps lines under 100 chars)
_TEST_AOI = "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fernet_key() -> bytes:
    from cryptography.fernet import Fernet
    return Fernet.generate_key()


def _sample_payload() -> dict[str, Any]:
    return {
        "api_key": "test-api-key",
        "order_type": "TASKING",
        "order_params": {
            "aoi": "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, "
                   "-97.76 30.28, -97.72 30.28))",
            "windowStart": "2026-03-15T10:00:00",
            "windowEnd": "2026-03-15T18:00:00",
            "productType": "DAY",
            "resolution": "VERY HIGH",
            "deliveryDriver": "NONE",
        },
        "estimated_cost_cents": 42500,
    }


@pytest.fixture
async def db_session() -> Any:
    """Async SQLite in-memory session for confirmation tests."""
    from purveyor.models.database import create_engine, create_session_factory, init_db

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_session_factory(engine)
    await init_db(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def session_factory() -> Any:
    """Async SQLite in-memory session factory."""
    from purveyor.models.database import create_engine, create_session_factory, init_db

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    sf = create_session_factory(engine)
    await init_db(engine)
    yield sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# Token encrypt / decrypt
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    """Encrypted payload can be decrypted back to original."""
    key = _make_fernet_key()
    payload = _sample_payload()

    token = encrypt_confirmation_token(payload, key)
    result = decrypt_confirmation_token(token, key)

    assert result["api_key"] == payload["api_key"]
    assert result["order_type"] == payload["order_type"]
    assert result["estimated_cost_cents"] == payload["estimated_cost_cents"]
    assert result["order_params"]["productType"] == "DAY"


def test_minimal_token_is_short() -> None:
    """New tokens carry only api_key — URL token must be short enough for LLMs."""
    from purveyor.core.confirmation import fernet_to_url_token

    key = _make_fernet_key()
    # New-style minimal payload: only the API key
    minimal_payload = {"api_key": "sk_live_abcdef1234567890abcdef1234567890"}
    token = encrypt_confirmation_token(minimal_payload, key)
    url_token = fernet_to_url_token(token)

    # Must be well under 256 chars so LLMs don't truncate
    assert len(url_token) < 256, (
        f"URL token is {len(url_token)} chars — too long for reliable LLM rendering"
    )


async def test_confirm_order_loads_params_from_db(session_factory: Any) -> None:
    """confirm_order uses order_params from order_payload_json when present."""
    import json

    key = _make_fernet_key()
    # Minimal token: only api_key
    token = encrypt_confirmation_token({"api_key": "test-api-key"}, key)

    order_payload = {
        "order_params": {
            "aoi": "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, "
                   "-97.76 30.28, -97.72 30.28))",
            "windowStart": "2026-03-15T10:00:00",
            "windowEnd": "2026-03-15T18:00:00",
            "productType": "DAY",
            "resolution": "VERY HIGH",
            "deliveryDriver": "NONE",
            "webhookUrl": "https://webhook.site/test-url",
        },
        "webhook_url": "https://webhook.site/test-url",
    }
    order_payload_json = json.dumps(order_payload)

    order_response = _make_tasking_order_response()
    mock_client = MagicMock()
    mock_client.create_tasking_order = AsyncMock(return_value=order_response)
    mock_client.close = AsyncMock()

    async with session_factory() as session:
        await create_confirmation(
            session, token, "TASKING", "f" * 64, 42500,
            order_payload_json=order_payload_json,
        )

    async with session_factory() as session:
        record, _resp = await confirm_order(
            session=session,
            token=token,
            fernet_key=key,
            skyfi_client=mock_client,
        )

    assert record.status == "placed"
    assert record.skyfi_order_id == order_response.id
    # Verify order was placed with params from DB (not from token)
    call_args = mock_client.create_tasking_order.call_args[0][0]
    assert call_args.webhook_url == "https://webhook.site/test-url"


async def test_confirm_order_backward_compat_no_db_payload(session_factory: Any) -> None:
    """confirm_order falls back to token payload for pre-migration records."""
    key = _make_fernet_key()
    # Old-style token with full payload
    payload = _sample_payload()
    token = encrypt_confirmation_token(payload, key)

    order_response = _make_tasking_order_response()
    mock_client = MagicMock()
    mock_client.create_tasking_order = AsyncMock(return_value=order_response)
    mock_client.close = AsyncMock()

    async with session_factory() as session:
        # No order_payload_json — simulates pre-migration record
        await create_confirmation(session, token, "TASKING", "f" * 64, 42500)

    async with session_factory() as session:
        record, _resp = await confirm_order(
            session=session,
            token=token,
            fernet_key=key,
            skyfi_client=mock_client,
        )

    assert record.status == "placed"
    mock_client.create_tasking_order.assert_called_once()


async def test_decrypt_expired_token() -> None:
    """Decrypting an expired token raises ToolError with ORDER_EXPIRED."""
    key = _make_fernet_key()
    payload = _sample_payload()

    token = encrypt_confirmation_token(payload, key)
    # Wait past TTL of 1 second
    await asyncio.sleep(2)

    with pytest.raises(ToolError) as exc_info:
        decrypt_confirmation_token(token, key, ttl=1)

    assert exc_info.value.code == ErrorCode.ORDER_EXPIRED


# ---------------------------------------------------------------------------
# compute_token_hash
# ---------------------------------------------------------------------------


def test_compute_token_hash_deterministic() -> None:
    """Same token always produces the same hash."""
    key = _make_fernet_key()
    payload = _sample_payload()
    token = encrypt_confirmation_token(payload, key)

    hash1 = compute_token_hash(token)
    hash2 = compute_token_hash(token)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex


def test_compute_token_hash_different_for_different_inputs() -> None:
    """Different tokens produce different hashes."""
    key = _make_fernet_key()
    # Different payloads → different tokens
    token1 = encrypt_confirmation_token({"api_key": "key1"}, key)
    token2 = encrypt_confirmation_token({"api_key": "key2"}, key)

    assert compute_token_hash(token1) != compute_token_hash(token2)


# ---------------------------------------------------------------------------
# DB-based confirmation operations
# ---------------------------------------------------------------------------


async def test_create_confirmation(db_session: Any) -> None:
    """create_confirmation persists a pending record with correct fields."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)
    api_key_hash = "a" * 64

    record = await create_confirmation(
        db_session, token, "TASKING", api_key_hash, 42500
    )

    assert record.id is not None
    assert record.status == "pending"
    assert record.order_type == "TASKING"
    assert record.api_key_hash == api_key_hash
    assert record.estimated_cost_cents == 42500
    assert record.token_hash == compute_token_hash(token)


async def test_get_confirmation_by_token(db_session: Any) -> None:
    """get_confirmation_by_token returns the correct record."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)

    created = await create_confirmation(db_session, token, "TASKING", "b" * 64, 100)
    found = await get_confirmation_by_token(db_session, token)

    assert found is not None
    assert found.id == created.id
    assert found.status == "pending"


async def test_cancel_pending_confirmation(db_session: Any) -> None:
    """Cancelling a pending confirmation sets status to 'cancelled'."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)

    record = await create_confirmation(db_session, token, "TASKING", "c" * 64, 100)
    msg = await cancel_confirmation(db_session, record.id)

    assert "cancelled" in msg.lower()
    # Verify in DB
    found = await get_confirmation_by_token(db_session, token)
    assert found is not None
    assert found.status == "cancelled"


async def test_cancel_already_placed(db_session: Any) -> None:
    """Cancelling a placed order raises ToolError(ORDER_ALREADY_PLACED)."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)

    record = await create_confirmation(db_session, token, "TASKING", "d" * 64, 100)
    # Manually set to placed
    record.status = "placed"
    await db_session.commit()

    with pytest.raises(ToolError) as exc_info:
        await cancel_confirmation(db_session, record.id)

    assert exc_info.value.code == ErrorCode.ORDER_ALREADY_PLACED


async def test_cancel_already_cancelled(db_session: Any) -> None:
    """Cancelling a cancelled order returns already-cancelled message."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)

    record = await create_confirmation(db_session, token, "TASKING", "e" * 64, 100)
    # First cancel
    await cancel_confirmation(db_session, record.id)
    # Second cancel
    msg = await cancel_confirmation(db_session, record.id)

    assert "already cancelled" in msg.lower() or "cancelled" in msg.lower()


# ---------------------------------------------------------------------------
# confirm_order
# ---------------------------------------------------------------------------


def _make_archive_order_response() -> Any:
    """Return a minimal MagicMock standing in for ArchiveOrderResponse."""
    resp = MagicMock()
    resp.id = uuid.uuid4()
    return resp


def _make_tasking_order_response() -> TaskingOrderResponse:
    return TaskingOrderResponse(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        order_type=OrderType.TASKING,
        order_cost=42500,
        owner_id=uuid.uuid4(),
        status=DeliveryStatus.CREATED,
        order_code="TEST-001",
        created_at=datetime.datetime.now(datetime.UTC),
        aoi="POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))",
        aoi_sqkm=25.0,
        window_start=datetime.datetime.now(datetime.UTC),
        window_end=datetime.datetime.now(datetime.UTC),
        product_type="DAY",
        resolution="VERY HIGH",
    )


async def test_confirm_order_places_and_updates(session_factory: Any) -> None:
    """confirm_order calls SkyFi, updates status to 'placed', sets skyfi_order_id."""
    key = _make_fernet_key()
    payload = _sample_payload()
    token = encrypt_confirmation_token(payload, key)

    order_response = _make_tasking_order_response()
    mock_client = MagicMock()
    mock_client.create_tasking_order = AsyncMock(return_value=order_response)
    mock_client.close = AsyncMock()

    async with session_factory() as session:
        await create_confirmation(session, token, "TASKING", "f" * 64, 42500)

    async with session_factory() as session:
        record, _resp = await confirm_order(
            session=session,
            token=token,
            fernet_key=key,
            skyfi_client=mock_client,
        )

    assert record.status == "placed"
    assert record.skyfi_order_id == order_response.id
    assert _resp.id == order_response.id
    mock_client.create_tasking_order.assert_called_once()


async def test_confirm_order_already_placed(session_factory: Any) -> None:
    """confirm_order on a placed confirmation raises ToolError(ORDER_ALREADY_PLACED)."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)

    async with session_factory() as session:
        record = await create_confirmation(session, token, "TASKING", "g" * 64, 100)
        record.status = "placed"
        await session.commit()

    mock_client = MagicMock()

    async with session_factory() as session:
        with pytest.raises(ToolError) as exc_info:
            await confirm_order(
                session=session,
                token=token,
                fernet_key=key,
                skyfi_client=mock_client,
            )

    assert exc_info.value.code == ErrorCode.ORDER_ALREADY_PLACED


async def test_confirm_archive_order_webhook_url_via_mock(session_factory: Any) -> None:
    """confirm_order for ARCHIVE type passes webhookUrl to SkyFi client."""
    import json as _json

    key = _make_fernet_key()
    token = encrypt_confirmation_token({"api_key": "test-api-key"}, key)

    webhook_url = "https://webhook.site/test-archive-url"
    order_payload = {
        "order_params": {
            "aoi": _TEST_AOI,
            "archiveId": "archive-abc-123",
            "deliveryDriver": "NONE",
            "deliveryParams": None,
            "label": "Platform Order",
            "orderLabel": "Platform Order",
            "metadata": None,
            "webhookUrl": webhook_url,
        },
        "webhook_url": webhook_url,
    }
    order_payload_json = _json.dumps(order_payload)

    archive_response = _make_archive_order_response()
    mock_client = MagicMock()
    mock_client.create_archive_order = AsyncMock(return_value=archive_response)
    mock_client.close = AsyncMock()

    async with session_factory() as session:
        await create_confirmation(
            session, token, "ARCHIVE", "a" * 64, 0,
            order_payload_json=order_payload_json,
        )

    async with session_factory() as session:
        record, _resp = await confirm_order(
            session=session,
            token=token,
            fernet_key=key,
            skyfi_client=mock_client,
        )

    assert record.status == "placed"
    assert record.skyfi_order_id == archive_response.id
    call_args = mock_client.create_archive_order.call_args[0][0]
    assert call_args.webhook_url == webhook_url, (
        f"webhook_url missing from ArchiveOrderRequest: got {call_args.webhook_url!r}"
    )
    # Verify the SkyFi wire payload contains webhookUrl
    skyfi_payload = call_args.model_dump_skyfi()
    assert "webhookUrl" in skyfi_payload, (
        f"webhookUrl missing from model_dump_skyfi() output: {list(skyfi_payload.keys())}"
    )
    assert skyfi_payload["webhookUrl"] == webhook_url


@respx.mock
async def test_confirm_archive_order_webhook_url_in_http_body(session_factory: Any) -> None:
    """End-to-end: webhookUrl appears in the actual HTTP body sent to SkyFi for ARCHIVE orders."""
    import json as _json

    from purveyor.core.skyfi_client import SKYFI_BASE_URL, SkyFiClient

    key = _make_fernet_key()
    webhook_url = "https://webhook.site/19238b05-6959-434f-93da-5676be689e55"
    token = encrypt_confirmation_token({"api_key": "live-test-key"}, key)

    order_payload = {
        "order_params": {
            "aoi": _TEST_AOI,
            "archiveId": "archive-abc-123",
            "deliveryDriver": "NONE",
            "deliveryParams": None,
            "label": "Platform Order",
            "orderLabel": "Platform Order",
            "metadata": None,
            "webhookUrl": webhook_url,
        },
        "webhook_url": webhook_url,
    }
    order_payload_json = _json.dumps(order_payload)

    archive_resp_json = {
        "id": str(uuid.uuid4()),
        "orderId": str(uuid.uuid4()),
        "itemId": str(uuid.uuid4()),
        "orderType": "ARCHIVE",
        "orderCost": 0,
        "ownerId": str(uuid.uuid4()),
        "status": "CREATED",
        "orderCode": "TEST-001",
        "createdAt": "2026-03-15T00:00:00Z",
        "aoi": _TEST_AOI,
        "aoiSqkm": 25.0,
        "archiveId": "archive-abc-123",
        "archive": {
            "id": "archive-abc-123",
            "archiveId": "archive-abc-123",
            "provider": "SENTINEL2_CREODIAS",
            "resolution": "LOW",
            "constellation": "Sentinel-2",
            "captureTimestamp": "2026-03-12T05:00:00Z",
            "cloudCoverage": 10.0,
            "aoi": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
            "overlapRatio": 1.0,
            "overlapSqkm": 100.0,
            "priceForOneSquareKmCents": 0,
            "priceForOneSquareKm": 0,
            "priceFullScene": 0,
            "minSqKm": 1.0,
            "maxSqKm": 1000.0,
            "openData": True,
            "productType": "MULTISPECTRAL",
            "platformResolution": 10.0,
            "footprint": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
            "totalAreaSquareKm": 1000.0,
            "gsd": 10.0,
        },
    }

    route = respx.post(f"{SKYFI_BASE_URL}/order-archive").mock(
        return_value=httpx.Response(200, json=archive_resp_json)
    )

    async with session_factory() as session:
        await create_confirmation(
            session, token, "ARCHIVE", "b" * 64, 0,
            order_payload_json=order_payload_json,
        )

    client = SkyFiClient(api_key="live-test-key")
    try:
        async with session_factory() as session:
            record, _resp = await confirm_order(
                session=session,
                token=token,
                fernet_key=key,
                skyfi_client=client,
            )
    finally:
        await client.close()

    assert route.called, "SkyFi /order-archive was never called"
    actual_body = json.loads(route.calls[0].request.content)
    assert "webhookUrl" in actual_body, (
        f"webhookUrl missing from HTTP body sent to SkyFi. Got keys: {list(actual_body.keys())}"
    )
    assert actual_body["webhookUrl"] == webhook_url, (
        f"webhookUrl mismatch: expected {webhook_url!r}, got {actual_body['webhookUrl']!r}"
    )
    assert record.status == "placed"


@respx.mock
async def test_confirm_tasking_order_webhook_url_in_http_body(session_factory: Any) -> None:
    """End-to-end: webhookUrl appears in the actual HTTP body sent to SkyFi for TASKING orders."""
    import json as _json

    from purveyor.core.skyfi_client import SKYFI_BASE_URL, SkyFiClient

    key = _make_fernet_key()
    webhook_url = "https://webhook.site/19238b05-6959-434f-93da-5676be689e55"
    token = encrypt_confirmation_token({"api_key": "live-test-key"}, key)

    order_payload = {
        "order_params": {
            "aoi": _TEST_AOI,
            "windowStart": "2026-03-15T10:00:00",
            "windowEnd": "2026-03-15T18:00:00",
            "productType": "DAY",
            "resolution": "VERY HIGH",
            "deliveryDriver": "NONE",
            "deliveryParams": None,
            "label": "Platform Order",
            "orderLabel": "Platform Order",
            "metadata": None,
            "webhookUrl": webhook_url,
            "priorityItem": False,
            "maxCloudCoveragePercent": 20,
            "maxOffNadirAngle": 30,
        },
        "webhook_url": webhook_url,
    }
    order_payload_json = _json.dumps(order_payload)

    tasking_order_id = str(uuid.uuid4())
    tasking_resp_json = {
        "id": tasking_order_id,
        "orderId": str(uuid.uuid4()),
        "itemId": str(uuid.uuid4()),
        "orderType": "TASKING",
        "orderCost": 42500,
        "ownerId": str(uuid.uuid4()),
        "status": "CREATED",
        "orderCode": "TEST-002",
        "createdAt": "2026-03-15T00:00:00Z",
        "aoi": _TEST_AOI,
        "aoiSqkm": 25.0,
        "windowStart": "2026-03-15T10:00:00Z",
        "windowEnd": "2026-03-15T18:00:00Z",
        "productType": "DAY",
        "resolution": "VERY HIGH",
    }

    route = respx.post(f"{SKYFI_BASE_URL}/order-tasking").mock(
        return_value=httpx.Response(200, json=tasking_resp_json)
    )

    async with session_factory() as session:
        await create_confirmation(
            session, token, "TASKING", "c" * 64, 42500,
            order_payload_json=order_payload_json,
        )

    client = SkyFiClient(api_key="live-test-key")
    try:
        async with session_factory() as session:
            record, _resp = await confirm_order(
                session=session,
                token=token,
                fernet_key=key,
                skyfi_client=client,
            )
    finally:
        await client.close()

    assert route.called, "SkyFi /order-tasking was never called"
    actual_body = json.loads(route.calls[0].request.content)
    assert "webhookUrl" in actual_body, (
        f"webhookUrl missing from HTTP body sent to SkyFi. Got keys: {list(actual_body.keys())}"
    )
    assert actual_body["webhookUrl"] == webhook_url
    assert record.status == "placed"


async def test_confirm_order_without_webhook_url_omits_field(session_factory: Any) -> None:
    """When no webhook_url is provided, webhookUrl must NOT appear in the SkyFi request."""
    import json as _json

    key = _make_fernet_key()
    token = encrypt_confirmation_token({"api_key": "test-api-key"}, key)

    order_payload = {
        "order_params": {
            "aoi": _TEST_AOI,
            "archiveId": "archive-abc-123",
            "deliveryDriver": "NONE",
            "deliveryParams": None,
            "label": "Platform Order",
            "orderLabel": "Platform Order",
            "metadata": None,
            "webhookUrl": None,  # explicitly None
        },
        "webhook_url": None,
    }
    order_payload_json = _json.dumps(order_payload)

    archive_response = _make_archive_order_response()
    mock_client = MagicMock()
    mock_client.create_archive_order = AsyncMock(return_value=archive_response)
    mock_client.close = AsyncMock()

    async with session_factory() as session:
        await create_confirmation(
            session, token, "ARCHIVE", "d" * 64, 0,
            order_payload_json=order_payload_json,
        )

    async with session_factory() as session:
        await confirm_order(
            session=session,
            token=token,
            fernet_key=key,
            skyfi_client=mock_client,
        )

    call_args = mock_client.create_archive_order.call_args[0][0]
    skyfi_payload = call_args.model_dump_skyfi()
    assert "webhookUrl" not in skyfi_payload, (
        "webhookUrl should be absent from SkyFi payload when not provided"
    )


async def test_confirm_order_cancelled(session_factory: Any) -> None:
    """confirm_order on a cancelled confirmation raises ToolError(ORDER_ALREADY_CANCELLED)."""
    key = _make_fernet_key()
    token = encrypt_confirmation_token(_sample_payload(), key)

    async with session_factory() as session:
        record = await create_confirmation(session, token, "TASKING", "h" * 64, 100)
        record.status = "cancelled"
        await session.commit()

    mock_client = MagicMock()

    async with session_factory() as session:
        with pytest.raises(ToolError) as exc_info:
            await confirm_order(
                session=session,
                token=token,
                fernet_key=key,
                skyfi_client=mock_client,
            )

    assert exc_info.value.code == ErrorCode.ORDER_ALREADY_CANCELLED


# ---------------------------------------------------------------------------
# resolve_base_url
# ---------------------------------------------------------------------------


def _make_settings(**kwargs: Any) -> Any:
    """Create a minimal Settings-like mock."""
    settings = MagicMock()
    settings.confirmation_base_url = kwargs.get("confirmation_base_url", None)
    settings.server_port = kwargs.get("server_port", 8000)
    return settings


def _make_request(headers: dict[str, str]) -> Any:
    """Create a minimal Request-like mock."""
    request = MagicMock(spec=Request)
    request.headers = headers
    request.url.scheme = "http"
    return request


def test_resolve_base_url_explicit_config() -> None:
    """When confirmation_base_url is set in settings, it is used directly."""
    settings = _make_settings(confirmation_base_url="https://purveyor.example.com/")
    request = _make_request({})

    result = resolve_base_url(request, settings)
    assert result == "https://purveyor.example.com"


def test_resolve_base_url_from_headers() -> None:
    """X-Forwarded-Proto + X-Forwarded-Host headers are used to build the URL."""
    settings = _make_settings()
    request = _make_request({
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "purveyor.example.com",
    })

    result = resolve_base_url(request, settings)
    assert result == "https://purveyor.example.com"


def test_resolve_base_url_localhost_fallback() -> None:
    """No config and no headers → localhost fallback with port."""
    settings = _make_settings(server_port=9000)
    # Request with no relevant headers and host fallback
    request = MagicMock(spec=Request)
    request.headers = {}
    request.url.scheme = "http"

    result = resolve_base_url(request, settings)
    assert "localhost" in result
    assert "9000" in result
