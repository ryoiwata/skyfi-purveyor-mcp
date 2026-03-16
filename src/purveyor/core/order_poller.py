"""Background polling for order status updates and webhook delivery.

When SkyFi does not reliably deliver webhooks, Purveyor polls GET /orders/{id}
every POLL_INTERVAL_SECONDS and fires a webhook to the registered URL on each
status change. Events are stored in the demo webhook deque AND persisted to DB.

Order stage progression (mirrors SkyFi UI order history):
    CREATED             → "Order Placed"
    STARTED             → "Payment Not Required" (free) / "Payment Accepted"
    PROVIDER_PENDING    → order accepted by provider
    PROCESSING_PENDING  → "Order Accepted" / queued for processing
    PROCESSING_COMPLETE → "Processing" complete
    DELIVERY_COMPLETED  → "Complete"
"""

from __future__ import annotations

import asyncio
import datetime
import json
import uuid
from typing import Any

import httpx
import structlog

from purveyor.core.webhook_store import order_webhook_events

log = structlog.get_logger(__name__)

# In-memory polling registry: order_id (str) → entry dict
# Not persisted — survives requests, not restarts.
# API key lives here only in-memory (never written to DB).
_polling_registry: dict[str, dict[str, Any]] = {}
_registry_lock: asyncio.Lock | None = None  # Lazy init after event loop is running

POLL_INTERVAL_SECONDS = 30
MAX_POLL_ATTEMPTS = 120  # ~1 hour at 30s intervals

# Terminal statuses: stop polling when any of these are reached
_TERMINAL_STATUSES = frozenset(
    {
        "DELIVERY_COMPLETED",
        "DELIVERY_FAILED",
        "PROCESSING_FAILED",
        "PROVIDER_FAILED",
        "PAYMENT_FAILED",
        "PLATFORM_FAILED",
    }
)


def _get_lock() -> asyncio.Lock:
    """Get or create the registry lock (must be called within a running event loop)."""
    global _registry_lock
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    return _registry_lock


async def register_order_for_polling(
    order_id: str,
    api_key: str,
    webhook_url: str,
    initial_status: str = "CREATED",
) -> None:
    """Register an order for background status polling.

    Args:
        order_id: SkyFi order UUID string.
        api_key: SkyFi API key used to query order status.
        webhook_url: URL to POST status update events to.
        initial_status: The status already fired on placement (not re-fired).
    """
    async with _get_lock():
        _polling_registry[order_id] = {
            "api_key": api_key,
            "webhook_url": webhook_url,
            "last_status": initial_status,
            "poll_count": 0,
        }
    log.info(
        "order_poller_registered",
        order_id=order_id,
        webhook_url=webhook_url,
        initial_status=initial_status,
    )


async def _persist_webhook_event(session_factory: Any, event: dict[str, Any]) -> None:
    """Persist a webhook event to the database."""
    from purveyor.models.tables import WebhookEvent

    if session_factory is None:
        return
    try:
        async with session_factory() as session:
            db_row = WebhookEvent(
                event_type="demo_order_webhook",
                payload=json.dumps(event),
                api_key_hash=None,
                delivered=True,
            )
            session.add(db_row)
            await session.commit()
    except Exception as exc:
        log.warning("order_poller_db_persist_failed", error=str(exc))


async def fire_and_store_webhook(
    webhook_url: str,
    order_id: str,
    order_info_dict: dict[str, Any],
    event_status: str,
    session_factory: Any = None,
    message: str | None = None,
) -> None:
    """Store a webhook event in the demo deque, persist to DB, and POST to the URL.

    Always stores locally first so the event is visible in the UI even if
    the HTTP POST to webhook_url fails.

    Args:
        webhook_url: URL to POST the event to.
        order_id: SkyFi order ID (for logging).
        order_info_dict: Serialized order info (by_alias=True JSON-safe dict).
        event_status: SkyFi DeliveryStatus string (e.g. "CREATED").
        session_factory: SQLAlchemy async session factory for DB persistence.
        message: Optional human-readable note to include in the event.
    """
    payload: dict[str, Any] = {
        "orderInfo": order_info_dict,
        "event": {
            "status": event_status,
            "timestamp": datetime.datetime.now(datetime.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "message": message,
        },
    }
    event: dict[str, Any] = {
        "received_at": datetime.datetime.now(datetime.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "payload": payload,
    }

    # 1. Store in demo deque (synchronous, never fails)
    order_webhook_events.appendleft(event)

    # 2. Persist to DB
    await _persist_webhook_event(session_factory, event)

    # 3. POST to webhook URL
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
        log.info(
            "order_poller_webhook_fired",
            order_id=order_id,
            event_status=event_status,
            http_status=resp.status_code,
        )
    except Exception as exc:
        log.warning(
            "order_poller_webhook_post_failed",
            order_id=order_id,
            event_status=event_status,
            error=str(exc),
        )


def _serialize_order(order: Any) -> dict[str, Any]:
    """Serialize an order response to a JSON-safe dict with string UUIDs."""
    data: dict[str, Any] = order.model_dump(by_alias=True, mode="json", exclude_none=True)
    # Ensure UUID fields are strings
    for key, value in list(data.items()):
        if isinstance(value, uuid.UUID):
            data[key] = str(value)
    # Ensure nested dicts too
    return data


async def _poll_once(session_factory: Any) -> None:
    """Poll all registered orders once; fire webhooks on status changes."""
    from purveyor.core.skyfi_client import SkyFiClient

    async with _get_lock():
        snapshot = dict(_polling_registry)

    for order_id, entry in snapshot.items():
        api_key: str = entry["api_key"]
        webhook_url: str = entry["webhook_url"]
        last_status: str = entry["last_status"]
        poll_count: int = entry["poll_count"]

        # Retire orders that have been polling too long
        if poll_count >= MAX_POLL_ATTEMPTS:
            async with _get_lock():
                _polling_registry.pop(order_id, None)
            log.info("order_poller_retired_max_attempts", order_id=order_id)
            continue

        try:
            client = SkyFiClient(api_key=api_key)
            try:
                order = await client.get_order(order_id)
            finally:
                await client.close()

            current_status = str(order.status)

            async with _get_lock():
                if order_id in _polling_registry:
                    _polling_registry[order_id]["poll_count"] = poll_count + 1

            if current_status != last_status:
                log.info(
                    "order_poller_status_changed",
                    order_id=order_id,
                    old_status=last_status,
                    new_status=current_status,
                )
                order_dict = _serialize_order(order)
                await fire_and_store_webhook(
                    webhook_url=webhook_url,
                    order_id=order_id,
                    order_info_dict=order_dict,
                    event_status=current_status,
                    session_factory=session_factory,
                )
                async with _get_lock():
                    if order_id in _polling_registry:
                        _polling_registry[order_id]["last_status"] = current_status

                if current_status in _TERMINAL_STATUSES:
                    async with _get_lock():
                        _polling_registry.pop(order_id, None)
                    log.info(
                        "order_poller_terminal",
                        order_id=order_id,
                        status=current_status,
                    )

        except Exception as exc:
            log.warning(
                "order_poller_poll_error",
                order_id=order_id,
                error=str(exc),
            )
            async with _get_lock():
                if order_id in _polling_registry:
                    _polling_registry[order_id]["poll_count"] = poll_count + 1


async def run_order_poller(session_factory: Any) -> None:
    """Continuous background task: poll registered orders every POLL_INTERVAL_SECONDS.

    Designed to run inside the FastAPI lifespan as an asyncio task.
    Exits cleanly on CancelledError.

    Args:
        session_factory: SQLAlchemy async session factory for DB persistence.
    """
    log.info("order_poller_started", interval_seconds=POLL_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            if _polling_registry:
                await _poll_once(session_factory)
        except asyncio.CancelledError:
            log.info("order_poller_stopped")
            return
        except Exception as exc:
            log.warning("order_poller_loop_error", error=str(exc))
