"""Webhook receiver for SkyFi order events and archive notifications."""

from __future__ import annotations

import json
import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from purveyor.core.skyfi_types import ArchiveResponse, OrderInfoWithEvent
from purveyor.models.tables import NotificationRegistry, OrderConfirmation, WebhookEvent

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# TODO (Phase 4): add per-IP rate limiting (100/min) using Redis or an in-memory counter


async def _require_webhook_token(request: Request) -> None:
    """FastAPI dependency: validate the shared secret token in ?token= query param.

    Using a Depends ensures this check runs before body parsing,
    so invalid/missing tokens always return 401 before any 422 body validation.

    Args:
        request: The FastAPI Request object.

    Raises:
        HTTPException: 401 if token is missing or invalid.
    """
    provided = request.query_params.get("token", "")
    expected = getattr(request.app.state, "webhook_secret", "")
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook token")


@router.post("/order-event", dependencies=[Depends(_require_webhook_token)])
async def webhook_order_event(
    request: Request,
    body: OrderInfoWithEvent,
) -> JSONResponse:
    """Receive an order status change event from SkyFi.

    Security (DESIGN_DECISIONS §5):
    1. Validate shared secret token in ?token= query param.
    2. Store event; always treat as an untrusted hint.
    3. Deduplicate by event_id to ensure idempotency.

    Per DESIGN_DECISIONS §3: Webhooks are hints, not truth. The actual
    order state must be verified against SkyFi API before acting on it.

    Args:
        request: The incoming FastAPI request.
        body: Parsed OrderInfoWithEvent payload from SkyFi.
    """
    order_info = body.order_info
    event = body.event

    order_id = str(order_info.id)
    event_status = str(event.status)
    event_id = f"order-{order_id}-{event_status}"

    log.info(
        "webhook_order_event_received",
        order_id=order_id,
        event_status=event_status,
        event_id=event_id,
    )

    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        # Deduplicate
        existing_stmt = select(WebhookEvent).where(WebhookEvent.event_id == event_id)
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            log.info("webhook_order_event_duplicate", event_id=event_id)
            return JSONResponse(content={"status": "received"})

        # Look up api_key_hash via OrderConfirmation
        import uuid as _uuid

        api_key_hash: str | None = None
        try:
            order_uuid = _uuid.UUID(order_id)
            conf_stmt = select(OrderConfirmation).where(
                OrderConfirmation.skyfi_order_id == order_uuid
            )
            conf = (await session.execute(conf_stmt)).scalar_one_or_none()
            if conf is not None:
                api_key_hash = conf.api_key_hash
        except Exception as exc:
            log.warning("webhook_order_lookup_failed", error=str(exc))

        # Serialize payload — scrub sensitive fields (security rule)
        raw_payload = body.model_dump(mode="json")
        # Remove any delivery params from the stored payload
        order_info_data = raw_payload.get("orderInfo") or raw_payload.get("order_info", {})
        for sensitive_key in ("deliveryParams", "delivery_params"):
            order_info_data.pop(sensitive_key, None)

        webhook_event = WebhookEvent(
            event_type="order_status",
            payload=json.dumps(raw_payload),
            api_key_hash=api_key_hash,
            delivered=False,
            event_id=event_id,
        )
        session.add(webhook_event)
        await session.commit()

    log.info("webhook_order_event_stored", event_id=event_id, api_key_hash_prefix=
             (api_key_hash[:8] + "...") if api_key_hash else None)

    return JSONResponse(content={"status": "received"})


@router.post("/archive-notification", dependencies=[Depends(_require_webhook_token)])
async def webhook_archive_notification(
    request: Request,
) -> JSONResponse:
    """Receive an archive availability notification from SkyFi.

    Security: Validate shared secret token (via dependency). Deduplicate by archive ID.

    Per DESIGN_DECISIONS §4: Look up the owning API key hash from
    notification_registry to route the event to the correct agent session.

    Args:
        request: The incoming FastAPI request.
    """
    try:
        raw_body = await request.json()
    except Exception as exc:
        log.warning("webhook_archive_invalid_json", error=str(exc))
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc

    # Extract archive_id for idempotency key
    archive_id: str | None = (
        raw_body.get("archiveId")
        or raw_body.get("archive_id")
        or raw_body.get("id")
    )

    # Validate as ArchiveResponse if possible (lenient — extra fields are ignored)
    try:
        ArchiveResponse.model_validate(raw_body)
    except Exception as val_exc:
        # Not strictly a valid ArchiveResponse — still store and process
        log.debug("archive_notification_not_full_archive_response", error=str(val_exc))

    notification_id: str | None = raw_body.get("notificationId") or raw_body.get("notification_id")

    event_id = f"archive-{archive_id or 'unknown'}"

    log.info(
        "webhook_archive_notification_received",
        archive_id=archive_id,
        notification_id=notification_id,
        event_id=event_id,
    )

    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        # Deduplicate
        existing_stmt = select(WebhookEvent).where(WebhookEvent.event_id == event_id)
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            log.info("webhook_archive_notification_duplicate", event_id=event_id)
            return JSONResponse(content={"status": "received"})

        # Look up api_key_hash from notification_registry
        import uuid as _uuid

        api_key_hash: str | None = None
        if notification_id:
            try:
                nid = _uuid.UUID(notification_id)
                reg_stmt = select(NotificationRegistry).where(NotificationRegistry.id == nid)
                reg = (await session.execute(reg_stmt)).scalar_one_or_none()
                if reg is not None:
                    api_key_hash = reg.api_key_hash
            except Exception as exc:
                log.warning("webhook_archive_registry_lookup_failed", error=str(exc))

        webhook_event = WebhookEvent(
            event_type="archive_notification",
            payload=json.dumps(raw_body),
            api_key_hash=api_key_hash,
            delivered=False,
            event_id=event_id,
        )
        session.add(webhook_event)
        await session.commit()

    log.info("webhook_archive_notification_stored", event_id=event_id)

    return JSONResponse(content={"status": "received"})
