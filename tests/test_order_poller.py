"""Tests for the order status poller: event firing, registry management, polling loop."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx

from purveyor.core.order_poller import (
    _TERMINAL_STATUSES,
    MAX_POLL_ATTEMPTS,
    _polling_registry,
    fire_and_store_webhook,
    register_order_for_polling,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_registry() -> None:
    """Clear the global polling registry between tests."""
    _polling_registry.clear()


def _make_mock_order(order_id: str, status: str = "CREATED") -> MagicMock:
    """Build a MagicMock order with the fields _poll_once actually accesses."""
    mock = MagicMock()
    mock.status = status
    mock.id = uuid.UUID(order_id)
    mock.model_dump.return_value = {"id": order_id, "status": status}
    return mock


# ---------------------------------------------------------------------------
# fire_and_store_webhook
# ---------------------------------------------------------------------------


@respx.mock
async def test_fire_and_store_webhook_appends_to_deque() -> None:
    """fire_and_store_webhook stores the event in the demo deque."""
    from purveyor.core.webhook_store import order_webhook_events

    initial_len = len(order_webhook_events)

    webhook_url = "https://webhook.example.com/events"
    respx.post(webhook_url).mock(return_value=httpx.Response(200, json={"ok": True}))

    order_id = str(uuid.uuid4())
    await fire_and_store_webhook(
        webhook_url=webhook_url,
        order_id=order_id,
        order_info_dict={"id": order_id, "status": "CREATED"},
        event_status="CREATED",
        session_factory=None,
    )

    assert len(order_webhook_events) == initial_len + 1
    newest = order_webhook_events[0]
    assert newest["payload"]["event"]["status"] == "CREATED"
    assert newest["payload"]["orderInfo"]["id"] == order_id


@respx.mock
async def test_fire_and_store_webhook_posts_to_url() -> None:
    """fire_and_store_webhook makes an HTTP POST to the webhook URL."""
    webhook_url = "https://webhook.example.com/notify"
    route = respx.post(webhook_url).mock(return_value=httpx.Response(200))

    await fire_and_store_webhook(
        webhook_url=webhook_url,
        order_id="order-abc",
        order_info_dict={"id": "order-abc", "status": "STARTED"},
        event_status="STARTED",
        session_factory=None,
    )

    assert route.called


@respx.mock
async def test_fire_and_store_webhook_tolerates_http_failure() -> None:
    """fire_and_store_webhook does not raise if the POST fails — event is still stored."""
    from purveyor.core.webhook_store import order_webhook_events

    initial_len = len(order_webhook_events)

    webhook_url = "https://webhook.example.com/broken"
    respx.post(webhook_url).mock(side_effect=httpx.ConnectError("refused"))

    await fire_and_store_webhook(
        webhook_url=webhook_url,
        order_id="order-err",
        order_info_dict={"id": "order-err", "status": "CREATED"},
        event_status="CREATED",
        session_factory=None,
    )

    # Event still stored even if POST failed
    assert len(order_webhook_events) == initial_len + 1


@respx.mock
async def test_fire_and_store_webhook_persists_to_db() -> None:
    """fire_and_store_webhook calls session_factory and writes a WebhookEvent row."""
    import json

    from purveyor.models.tables import WebhookEvent

    webhook_url = "https://webhook.example.com/db-test"
    respx.post(webhook_url).mock(return_value=httpx.Response(200))

    # Set up in-memory DB
    from sqlalchemy import select

    import purveyor.models.tables  # noqa: F401
    from purveyor.models.database import create_engine, create_session_factory, init_db

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    sf = create_session_factory(engine)
    await init_db(engine)

    try:
        order_id = str(uuid.uuid4())
        await fire_and_store_webhook(
            webhook_url=webhook_url,
            order_id=order_id,
            order_info_dict={"id": order_id, "status": "PROCESSING_COMPLETE"},
            event_status="PROCESSING_COMPLETE",
            session_factory=sf,
        )

        async with sf() as session:
            rows = (await session.execute(select(WebhookEvent))).scalars().all()

        assert len(rows) == 1
        payload = json.loads(rows[0].payload)
        assert payload["payload"]["event"]["status"] == "PROCESSING_COMPLETE"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# register_order_for_polling
# ---------------------------------------------------------------------------


async def test_register_order_for_polling_adds_to_registry() -> None:
    """register_order_for_polling adds the order to the global polling registry."""
    _clear_registry()

    order_id = str(uuid.uuid4())
    await register_order_for_polling(
        order_id=order_id,
        api_key="test-api-key",
        webhook_url="https://webhook.example.com/poll",
        initial_status="CREATED",
    )

    assert order_id in _polling_registry
    entry = _polling_registry[order_id]
    assert entry["api_key"] == "test-api-key"
    assert entry["webhook_url"] == "https://webhook.example.com/poll"
    assert entry["last_status"] == "CREATED"
    assert entry["poll_count"] == 0


async def test_register_order_overwrites_existing_entry() -> None:
    """Registering the same order_id twice overwrites the first entry."""
    _clear_registry()

    order_id = str(uuid.uuid4())
    await register_order_for_polling(order_id=order_id, api_key="key-1", webhook_url="url-1")
    await register_order_for_polling(order_id=order_id, api_key="key-2", webhook_url="url-2", initial_status="STARTED")

    assert _polling_registry[order_id]["api_key"] == "key-2"
    assert _polling_registry[order_id]["last_status"] == "STARTED"


# ---------------------------------------------------------------------------
# _poll_once — status change detection
# ---------------------------------------------------------------------------


@respx.mock
async def test_poll_once_fires_webhook_on_status_change() -> None:
    """_poll_once fires a webhook when the order status has changed."""
    from purveyor.core.order_poller import _poll_once
    from purveyor.core.webhook_store import order_webhook_events

    _clear_registry()

    order_id = str(uuid.uuid4())
    webhook_url = "https://webhook.example.com/stage"
    respx.post(webhook_url).mock(return_value=httpx.Response(200))

    _polling_registry[order_id] = {
        "api_key": "test-key",
        "webhook_url": webhook_url,
        "last_status": "CREATED",
        "poll_count": 0,
    }

    # SkyFi returns STARTED (payment accepted/not required)
    mock_order = _make_mock_order(order_id, status="STARTED")

    with patch("purveyor.core.skyfi_client.SkyFiClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.get_order = AsyncMock(return_value=mock_order)
        instance.close = AsyncMock()

        initial_deque_len = len(order_webhook_events)
        await _poll_once(session_factory=None)

    # Webhook event fired
    assert len(order_webhook_events) == initial_deque_len + 1
    newest = order_webhook_events[0]
    assert newest["payload"]["event"]["status"] == "STARTED"

    # Registry updated to new status
    assert _polling_registry[order_id]["last_status"] == "STARTED"
    assert _polling_registry[order_id]["poll_count"] == 1


@respx.mock
async def test_poll_once_no_webhook_when_status_unchanged() -> None:
    """_poll_once does NOT fire a webhook when status is the same as last_status."""
    from purveyor.core.order_poller import _poll_once
    from purveyor.core.webhook_store import order_webhook_events

    _clear_registry()

    order_id = str(uuid.uuid4())
    webhook_url = "https://webhook.example.com/no-change"
    respx.post(webhook_url).mock(return_value=httpx.Response(200))

    _polling_registry[order_id] = {
        "api_key": "test-key",
        "webhook_url": webhook_url,
        "last_status": "STARTED",
        "poll_count": 5,
    }

    # SkyFi still returns STARTED — no change
    mock_order = _make_mock_order(order_id, status="STARTED")

    with patch("purveyor.core.skyfi_client.SkyFiClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.get_order = AsyncMock(return_value=mock_order)
        instance.close = AsyncMock()

        initial_deque_len = len(order_webhook_events)
        await _poll_once(session_factory=None)

    # No new event
    assert len(order_webhook_events) == initial_deque_len
    # Poll count still incremented
    assert _polling_registry[order_id]["poll_count"] == 6


async def test_poll_once_removes_order_on_terminal_status() -> None:
    """_poll_once removes the order from the registry when a terminal status is reached."""
    from purveyor.core.order_poller import _poll_once

    _clear_registry()

    order_id = str(uuid.uuid4())
    webhook_url = "https://webhook.example.com/terminal"

    _polling_registry[order_id] = {
        "api_key": "test-key",
        "webhook_url": webhook_url,
        "last_status": "PROCESSING_COMPLETE",
        "poll_count": 10,
    }

    mock_order = _make_mock_order(order_id, status="DELIVERY_COMPLETED")

    with patch("purveyor.core.skyfi_client.SkyFiClient") as mock_client_cls, \
         respx.mock:
        respx.post(webhook_url).mock(return_value=httpx.Response(200))
        instance = mock_client_cls.return_value
        instance.get_order = AsyncMock(return_value=mock_order)
        instance.close = AsyncMock()

        await _poll_once(session_factory=None)

    # Order removed from registry after terminal status
    assert order_id not in _polling_registry


async def test_poll_once_retires_order_after_max_attempts() -> None:
    """_poll_once retires an order that has exceeded MAX_POLL_ATTEMPTS."""
    from purveyor.core.order_poller import _poll_once

    _clear_registry()

    order_id = str(uuid.uuid4())

    _polling_registry[order_id] = {
        "api_key": "test-key",
        "webhook_url": "https://webhook.example.com/retire",
        "last_status": "STARTED",
        "poll_count": MAX_POLL_ATTEMPTS,  # Already at limit
    }

    with patch("purveyor.core.skyfi_client.SkyFiClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.get_order = AsyncMock()
        instance.close = AsyncMock()

        await _poll_once(session_factory=None)

    # Order retired — get_order never called
    instance.get_order.assert_not_called()
    assert order_id not in _polling_registry


async def test_poll_once_handles_api_error_gracefully() -> None:
    """_poll_once increments poll_count and continues when SkyFi API raises."""
    from purveyor.core.order_poller import _poll_once

    _clear_registry()

    order_id = str(uuid.uuid4())
    _polling_registry[order_id] = {
        "api_key": "test-key",
        "webhook_url": "https://webhook.example.com/err",
        "last_status": "CREATED",
        "poll_count": 0,
    }

    with patch("purveyor.core.skyfi_client.SkyFiClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.get_order = AsyncMock(side_effect=Exception("SkyFi API timeout"))
        instance.close = AsyncMock()

        await _poll_once(session_factory=None)

    # Order still in registry (not removed) but poll_count incremented
    assert order_id in _polling_registry
    assert _polling_registry[order_id]["poll_count"] == 1


# ---------------------------------------------------------------------------
# Full stage progression integration
# ---------------------------------------------------------------------------


@respx.mock
async def test_poll_fires_events_for_all_five_stages() -> None:
    """Simulates a full order lifecycle — webhook fires at each of the 5 stages."""
    from purveyor.core.order_poller import _poll_once
    from purveyor.core.webhook_store import order_webhook_events

    _clear_registry()

    order_id = str(uuid.uuid4())
    webhook_url = "https://webhook.example.com/full-lifecycle"
    respx.post(webhook_url).mock(return_value=httpx.Response(200))

    # Register with initial CREATED status (already fired at confirmation time)
    _polling_registry[order_id] = {
        "api_key": "test-key",
        "webhook_url": webhook_url,
        "last_status": "CREATED",
        "poll_count": 0,
    }

    # Stage progression returned by SkyFi on successive polls
    stages = ["STARTED", "PROCESSING_PENDING", "PROCESSING_COMPLETE", "DELIVERY_COMPLETED"]

    fired_statuses: list[str] = []

    for stage in stages:
        mock_order = _make_mock_order(order_id, status=stage)

        with patch("purveyor.core.skyfi_client.SkyFiClient") as mock_client_cls:
            instance = mock_client_cls.return_value
            instance.get_order = AsyncMock(return_value=mock_order)
            instance.close = AsyncMock()

            pre_len = len(order_webhook_events)
            await _poll_once(session_factory=None)
            post_len = len(order_webhook_events)

        if post_len > pre_len:
            fired_statuses.append(order_webhook_events[0]["payload"]["event"]["status"])

        if stage in _TERMINAL_STATUSES:
            break

    assert fired_statuses == stages
    # Order removed from registry after DELIVERY_COMPLETED
    assert order_id not in _polling_registry
