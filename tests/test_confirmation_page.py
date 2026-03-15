"""Integration tests for GET/POST /confirm/{token} FastAPI endpoints.

Uses a single module-scoped FastAPI app + TestClient to avoid the
StreamableHTTPSessionManager single-use constraint.

Tests verify:
- Pending token renders the order details page (200)
- Missing token → 410 Link Expired (record_not_found path)
- Wrong Fernet key → 410 Link Expired (decrypt_failed path)
- Already-placed token → 409 Already Processed
- Already-cancelled token → 409 Already Processed
- POST action=confirm places the order
- POST action=cancel cancels the order
- Base32 URL round-trip: fernet_to_url_token / url_token_to_fernet are inverse
- Token hash is identical after base32 URL path round-trip (no encoding corruption)
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Enable local mode — tests use SQLite and auto-generated Fernet key
os.environ.setdefault("LOCAL_MODE", "true")


# ---------------------------------------------------------------------------
# Module-scoped app + client (avoids restarting the MCP session manager)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> Any:
    from purveyor.app import create_app

    return create_app()


@pytest.fixture(scope="module")
def client(app: Any) -> Any:  # type: ignore[misc]
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="module")
def fernet_key(app: Any) -> bytes:
    return app.state.settings.fernet_key  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(fernet_key: bytes, payload: dict[str, Any] | None = None) -> str:
    from purveyor.core.confirmation import encrypt_confirmation_token

    if payload is None:
        payload = {
            "api_key": "test-api-key",
            "order_type": "ARCHIVE",
            "order_params": {
                "aoi": "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))",
                "archiveId": "archive-123",
                "deliveryDriver": "NONE",
            },
            "estimated_cost_cents": 42500,
        }
    return encrypt_confirmation_token(payload, fernet_key)


def _persist_record(app: Any, token: str, status: str = "pending", order_type: str = "ARCHIVE") -> None:
    """Write an OrderConfirmation row directly via the app's session_factory."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from purveyor.core.confirmation import compute_token_hash
    from purveyor.models.tables import OrderConfirmation

    async def _write() -> None:
        session_factory = app.state.session_factory
        async with session_factory() as session:
            record = OrderConfirmation(
                token_hash=compute_token_hash(token),
                status=status,
                order_type=order_type,
                api_key_hash="a" * 64,
                estimated_cost_cents=42500,
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            session.add(record)
            await session.commit()

    asyncio.run(_write())


# ---------------------------------------------------------------------------
# GET /confirm/{token}
# ---------------------------------------------------------------------------


def _make_url_token(fernet_key: bytes, payload: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return (fernet_token, url_token) pair for testing."""
    from purveyor.core.confirmation import fernet_to_url_token

    fernet_token = _make_token(fernet_key, payload)
    return fernet_token, fernet_to_url_token(fernet_token)


def test_confirm_page_pending_renders_200(client: Any, app: Any, fernet_key: bytes) -> None:
    """Pending token renders confirmation page with 200 when URL uses base32."""
    fernet_token, url_token = _make_url_token(fernet_key)
    _persist_record(app, fernet_token)

    response = client.get(f"/confirm/{url_token}")

    assert response.status_code == 200
    assert "confirm" in response.text.lower() or "$" in response.text


def test_confirm_page_missing_record_returns_410(client: Any, fernet_key: bytes) -> None:
    """Token not in DB → 410 (record_not_found path)."""
    from purveyor.core.confirmation import encrypt_confirmation_token, fernet_to_url_token

    # Different payload → different token → no DB record for this one
    fernet_token = encrypt_confirmation_token(
        {"api_key": "no-record", "order_type": "ARCHIVE", "order_params": {}, "estimated_cost_cents": 0},
        fernet_key,
    )
    url_token = fernet_to_url_token(fernet_token)

    response = client.get(f"/confirm/{url_token}")

    assert response.status_code == 410
    assert "expired" in response.text.lower() or "link" in response.text.lower()


def test_confirm_page_wrong_key_returns_410(client: Any, app: Any) -> None:
    """Token encrypted with wrong key → record found but decrypt fails → 410."""
    from cryptography.fernet import Fernet

    from purveyor.core.confirmation import encrypt_confirmation_token, fernet_to_url_token

    other_key = Fernet.generate_key()
    fernet_token = encrypt_confirmation_token(
        {"api_key": "x", "order_type": "ARCHIVE", "order_params": {}, "estimated_cost_cents": 0},
        other_key,
    )
    # Write DB record so lookup succeeds, then decrypt with app key (mismatch)
    _persist_record(app, fernet_token)
    url_token = fernet_to_url_token(fernet_token)

    response = client.get(f"/confirm/{url_token}")

    assert response.status_code == 410


def test_confirm_page_placed_returns_409(client: Any, app: Any, fernet_key: bytes) -> None:
    """Already-placed token → 409."""
    fernet_token, url_token = _make_url_token(
        fernet_key, {"api_key": "placed-key", "order_type": "ARCHIVE", "order_params": {}, "estimated_cost_cents": 0}
    )
    _persist_record(app, fernet_token, status="placed")

    response = client.get(f"/confirm/{url_token}")

    assert response.status_code == 409


def test_confirm_page_cancelled_returns_409(client: Any, app: Any, fernet_key: bytes) -> None:
    """Already-cancelled token → 409."""
    fernet_token, url_token = _make_url_token(
        fernet_key, {"api_key": "cancelled-key", "order_type": "ARCHIVE", "order_params": {}, "estimated_cost_cents": 0}
    )
    _persist_record(app, fernet_token, status="cancelled")

    response = client.get(f"/confirm/{url_token}")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /confirm/{token}
# ---------------------------------------------------------------------------


def test_post_cancel_returns_cancelled_page(client: Any, app: Any, fernet_key: bytes) -> None:
    """POST action=cancel → 200 cancelled page."""
    fernet_token, url_token = _make_url_token(
        fernet_key, {"api_key": "cancel-me", "order_type": "ARCHIVE", "order_params": {}, "estimated_cost_cents": 0}
    )
    _persist_record(app, fernet_token)

    response = client.post(f"/confirm/{url_token}", data={"action": "cancel"})

    assert response.status_code == 200
    assert "cancel" in response.text.lower()


def test_post_confirm_places_tasking_order(client: Any, app: Any, fernet_key: bytes) -> None:
    """POST action=confirm calls SkyFi and shows success page."""
    import uuid

    mock_order_id = uuid.uuid4()
    mock_response = MagicMock()
    mock_response.id = mock_order_id

    payload = {
        "api_key": "real-api-key",
        "order_type": "TASKING",
        "order_params": {
            "aoi": "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))",
            "windowStart": "2026-03-15T10:00:00",
            "windowEnd": "2026-03-15T18:00:00",
            "productType": "DAY",
            "resolution": "VERY HIGH",
            "deliveryDriver": "NONE",
        },
        "estimated_cost_cents": 42500,
    }
    fernet_token, url_token = _make_url_token(fernet_key, payload)
    _persist_record(app, fernet_token, order_type="TASKING")

    with patch("purveyor.core.confirmation.SkyFiClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_instance.create_tasking_order = AsyncMock(return_value=mock_response)
        mock_instance.close = AsyncMock()
        mock_cls.return_value = mock_instance

        response = client.post(f"/confirm/{url_token}", data={"action": "confirm"})

    assert response.status_code == 200
    # Success page should mention the order ID or "confirmed"
    assert "confirmed" in response.text.lower() or str(mock_order_id) in response.text


# ---------------------------------------------------------------------------
# Base32 round-trip tests — fernet_to_url_token / url_token_to_fernet are inverse
# ---------------------------------------------------------------------------


def test_base32_round_trip_is_lossless(fernet_key: bytes) -> None:
    """fernet_to_url_token followed by url_token_to_fernet returns the original Fernet token."""
    from purveyor.core.confirmation import fernet_to_url_token, url_token_to_fernet

    fernet_token = _make_token(fernet_key)
    url_token = fernet_to_url_token(fernet_token)

    # URL token must contain only A-Z2-7 (no underscores, dashes, equals)
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in url_token), (
        f"URL token contains characters outside A-Z2-7: {url_token!r}"
    )

    recovered = url_token_to_fernet(url_token)
    assert recovered == fernet_token, (
        f"Round-trip failed:\n  original: {fernet_token!r}\n  recovered: {recovered!r}"
    )


def test_base32_url_token_case_insensitive(fernet_key: bytes) -> None:
    """url_token_to_fernet handles lowercase base32 (e.g., if Gemini lowercases the URL)."""
    from purveyor.core.confirmation import fernet_to_url_token, url_token_to_fernet

    fernet_token = _make_token(fernet_key, {"api_key": "case-test", "order_type": "ARCHIVE",
                                             "order_params": {}, "estimated_cost_cents": 0})
    url_token = fernet_to_url_token(fernet_token).lower()  # simulate Gemini lowercasing

    recovered = url_token_to_fernet(url_token)
    assert recovered == fernet_token


def test_token_hash_identical_after_base32_url_path_round_trip(
    client: Any, app: Any, fernet_key: bytes
) -> None:
    """Token hash is identical before and after base32 URL path round-trip.

    This is the critical regression test: verifies that the DB lookup finds the
    record after the URL token has been encoded by fernet_to_url_token() and
    decoded by url_token_to_fernet() inside the request handler.
    """
    from purveyor.core.confirmation import compute_token_hash

    fernet_token, url_token = _make_url_token(
        fernet_key, {"api_key": "roundtrip-base32", "order_type": "ARCHIVE",
                     "order_params": {}, "estimated_cost_cents": 0}
    )
    expected_hash = compute_token_hash(fernet_token)
    captured: dict[str, str] = {}

    import purveyor.core.confirmation as conf_module
    original_fn = conf_module.compute_token_hash

    def capturing_hash(t: str) -> str:
        h = original_fn(t)
        captured["hash"] = h
        return h

    _persist_record(app, fernet_token)

    with patch.object(conf_module, "compute_token_hash", side_effect=capturing_hash):
        response = client.get(f"/confirm/{url_token}")

    assert "hash" in captured, "compute_token_hash was never called during the request"
    assert captured["hash"] == expected_hash, (
        f"Token hash mismatch after base32 URL path round-trip!\n"
        f"  Before HTTP: {expected_hash}\n"
        f"  After HTTP:  {captured['hash']}\n"
        f"  URL token (first 20): {url_token[:20]!r}\n"
    )
    assert response.status_code == 200
