"""Tests for confirmation token encryption, decryption, and order confirmation flow."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
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
        record, resp = await confirm_order(
            session=session,
            token=token,
            fernet_key=key,
            skyfi_client=mock_client,
        )

    assert record.status == "placed"
    assert record.skyfi_order_id == order_response.id
    assert resp.id == order_response.id
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
