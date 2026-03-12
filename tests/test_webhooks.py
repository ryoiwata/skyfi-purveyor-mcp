"""Tests for the webhook receiver endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order_event_payload(
    order_id: str | None = None, status: str = "DELIVERY_COMPLETED"
) -> dict[str, Any]:
    oid = order_id or str(uuid.uuid4())
    return {
        "orderInfo": {
            "id": oid,
            "orderId": str(uuid.uuid4()),
            "itemId": str(uuid.uuid4()),
            "orderType": "TASKING",
            "orderCost": 42500,
            "ownerId": str(uuid.uuid4()),
            "status": status,
            "orderCode": "ORD-001",
            "createdAt": datetime.now(UTC).isoformat(),
            "aoi": (
                "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"
            ),
            "aoiSqkm": 25.0,
            "windowStart": datetime.now(UTC).isoformat(),
            "windowEnd": datetime.now(UTC).isoformat(),
            "productType": "DAY",
            "resolution": "VERY HIGH",
        },
        "event": {
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            "message": None,
        },
    }


def _make_archive_notification_payload(archive_id: str | None = None) -> dict[str, Any]:
    aid = archive_id or str(uuid.uuid4())
    return {
        "archiveId": aid,
        "id": aid,
        "provider": "PLANET",
        "constellation": "PS",
        "productType": "DAY",
        "platformResolution": 0.5,
        "resolution": "VERY HIGH",
        "captureTimestamp": datetime.now(UTC).isoformat(),
        "footprint": (
            "POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))"
        ),
        "minSqKm": 0.1,
        "maxSqKm": 500.0,
        "priceForOneSquareKm": 17.0,
        "priceForOneSquareKmCents": 1700,
        "priceFullScene": 425.0,
        "totalAreaSquareKm": 100.0,
        "gsd": 0.5,
        "overlapRatio": 0.85,
        "overlapSqkm": 12.5,
    }


@pytest.fixture
async def app_with_db() -> Any:
    """Create a FastAPI test app with in-memory SQLite."""
    import secrets

    from fastapi import FastAPI

    import purveyor.models.tables  # noqa: F401 — registers tables on Base.metadata
    from purveyor.models.database import create_engine, create_session_factory, init_db
    from purveyor.webhooks.receiver import router as webhook_router

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    app = FastAPI()
    app.include_router(webhook_router)

    webhook_secret = secrets.token_urlsafe(32)
    app.state.webhook_secret = webhook_secret
    app.state.session_factory = session_factory

    yield app, webhook_secret

    await engine.dispose()


# ---------------------------------------------------------------------------
# Webhook tests — order-event
# ---------------------------------------------------------------------------


async def test_webhook_order_event_valid_token(app_with_db: Any) -> None:
    """POST /webhooks/order-event with valid token returns 200."""
    app, webhook_secret = app_with_db
    payload = _make_order_event_payload()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/webhooks/order-event?token={webhook_secret}",
            json=payload,
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


async def test_webhook_order_event_missing_token(app_with_db: Any) -> None:
    """POST /webhooks/order-event without token returns 401."""
    app, _ = app_with_db
    payload = _make_order_event_payload()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhooks/order-event", json=payload)

    assert resp.status_code == 401


async def test_webhook_order_event_wrong_token(app_with_db: Any) -> None:
    """POST /webhooks/order-event with wrong token returns 401."""
    app, _ = app_with_db
    payload = _make_order_event_payload()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/order-event?token=wrong-secret",
            json=payload,
        )

    assert resp.status_code == 401


async def test_webhook_order_event_duplicate(app_with_db: Any) -> None:
    """Posting the same event twice returns 200 (idempotent)."""
    app, webhook_secret = app_with_db
    order_id = str(uuid.uuid4())
    payload = _make_order_event_payload(order_id=order_id, status="DELIVERY_COMPLETED")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post(
            f"/webhooks/order-event?token={webhook_secret}",
            json=payload,
        )
        resp2 = await client.post(
            f"/webhooks/order-event?token={webhook_secret}",
            json=payload,
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # Both return "received" — idempotent
    assert resp2.json()["status"] == "received"


# ---------------------------------------------------------------------------
# Webhook tests — archive-notification
# ---------------------------------------------------------------------------


async def test_webhook_archive_notification_valid(app_with_db: Any) -> None:
    """POST /webhooks/archive-notification with valid token returns 200."""
    app, webhook_secret = app_with_db
    payload = _make_archive_notification_payload()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/webhooks/archive-notification?token={webhook_secret}",
            json=payload,
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


async def test_webhook_archive_notification_missing_token(app_with_db: Any) -> None:
    """POST /webhooks/archive-notification without token returns 401."""
    app, _ = app_with_db
    payload = _make_archive_notification_payload()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhooks/archive-notification", json=payload)

    assert resp.status_code == 401


async def test_webhook_archive_notification_duplicate(app_with_db: Any) -> None:
    """Posting the same archive event twice returns 200 (idempotent)."""
    app, webhook_secret = app_with_db
    archive_id = str(uuid.uuid4())
    payload = _make_archive_notification_payload(archive_id=archive_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post(
            f"/webhooks/archive-notification?token={webhook_secret}",
            json=payload,
        )
        resp2 = await client.post(
            f"/webhooks/archive-notification?token={webhook_secret}",
            json=payload,
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200


async def test_webhook_archive_notification_invalid_json(app_with_db: Any) -> None:
    """POST with malformed JSON body returns 422."""
    app, webhook_secret = app_with_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/webhooks/archive-notification?token={webhook_secret}",
            content=b"not valid json {{{",
            headers={"content-type": "application/json"},
        )

    assert resp.status_code in (400, 422)


async def test_webhook_event_stored_in_db(app_with_db: Any) -> None:
    """After a valid order-event, a WebhookEvent record is stored in DB."""
    from purveyor.models.tables import WebhookEvent

    app, webhook_secret = app_with_db
    order_id = str(uuid.uuid4())
    payload = _make_order_event_payload(order_id=order_id, status="CREATED")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/webhooks/order-event?token={webhook_secret}",
            json=payload,
        )

    assert resp.status_code == 200

    session_factory = app.state.session_factory
    async with session_factory() as session:
        stmt = select(WebhookEvent).where(
            WebhookEvent.event_id == f"order-{order_id}-CREATED"
        )
        event = (await session.execute(stmt)).scalar_one_or_none()

    assert event is not None
    assert event.event_type == "order_status"
    assert event.delivered is False
