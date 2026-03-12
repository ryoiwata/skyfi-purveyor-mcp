"""Confirmation token encryption, decryption, and order confirmation flow.

Per DESIGN_DECISIONS.md sections 1-6:
- API keys live in Fernet-encrypted URL tokens, never in the database.
- Tokens have a 30-minute TTL enforced by Fernet's built-in ttl parameter.
- Tokens are single-use; status is tracked via order_confirmations table.
- Multi-instance single-use enforcement uses SELECT FOR UPDATE SKIP LOCKED on Postgres.
- SQLite deployments are single-instance and use plain SELECT.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from purveyor.core.config import Settings
from purveyor.core.errors import ErrorCode, ToolError
from purveyor.core.skyfi_client import SkyFiClient
from purveyor.core.skyfi_types import (
    ArchiveOrderRequest,
    ArchiveOrderResponse,
    TaskingOrderRequest,
    TaskingOrderResponse,
)
from purveyor.models.tables import OrderConfirmation

log = structlog.get_logger(__name__)


def encrypt_confirmation_token(payload: dict[str, Any], fernet_key: bytes) -> str:
    """Encrypt an order payload dict into a URL-safe Fernet token string.

    Args:
        payload: Dict containing api_key, order_type, order_params, estimated_cost_cents.
        fernet_key: Fernet symmetric key bytes (from Settings.fernet_key).

    Returns:
        URL-safe base64 token string (Fernet's native output format).
    """
    json_bytes = json.dumps(payload).encode("utf-8")
    token_bytes = Fernet(fernet_key).encrypt(json_bytes)
    return token_bytes.decode()


def decrypt_confirmation_token(
    token: str, fernet_key: bytes, ttl: int = 1800
) -> dict[str, Any]:
    """Decrypt a Fernet token and return the payload dict.

    Args:
        token: URL-safe Fernet token string.
        fernet_key: Fernet symmetric key bytes (from Settings.fernet_key).
        ttl: Time-to-live in seconds (default: 1800 = 30 minutes).

    Returns:
        Decrypted payload dict.

    Raises:
        ToolError: With code ORDER_EXPIRED if the token is invalid or expired.
    """
    try:
        decrypted = Fernet(fernet_key).decrypt(token.encode(), ttl=ttl)
        return json.loads(decrypted)  # type: ignore[no-any-return]
    except InvalidToken as exc:
        raise ToolError(
            code=ErrorCode.ORDER_EXPIRED,
            message="This order confirmation has expired or is invalid.",
        ) from exc


def compute_token_hash(token: str) -> str:
    """Compute a SHA-256 hex digest of a token string.

    Args:
        token: The Fernet token string to hash.

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(token.encode()).hexdigest()


async def create_confirmation(
    session: AsyncSession,
    token: str,
    order_type: str,
    api_key_hash: str,
    estimated_cost_cents: int,
    mcp_session_id: str | None = None,
) -> OrderConfirmation:
    """Create and persist a new pending OrderConfirmation record.

    Args:
        session: Async SQLAlchemy session.
        token: The Fernet URL token (hashed for storage).
        order_type: "TASKING" or "ARCHIVE".
        api_key_hash: SHA-256 hex digest of the user's API key.
        estimated_cost_cents: Estimated order cost in integer cents.
        mcp_session_id: Optional MCP session ID for SSE routing.

    Returns:
        The newly created and committed OrderConfirmation row.
    """
    token_hash = compute_token_hash(token)
    expires_at = datetime.now(UTC) + timedelta(minutes=30)

    record = OrderConfirmation(
        token_hash=token_hash,
        status="pending",
        order_type=order_type,
        api_key_hash=api_key_hash,
        mcp_session_id=mcp_session_id,
        estimated_cost_cents=estimated_cost_cents,
        expires_at=expires_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    log.info(
        "confirmation_created",
        token_hash=token_hash[:16] + "...",
        order_type=order_type,
        estimated_cost_cents=estimated_cost_cents,
    )
    return record


async def get_confirmation_by_token(
    session: AsyncSession, token: str
) -> OrderConfirmation | None:
    """Fetch an OrderConfirmation row by token (hashed for lookup).

    Args:
        session: Async SQLAlchemy session.
        token: The Fernet URL token string to look up.

    Returns:
        The matching OrderConfirmation, or None if not found.
    """
    token_hash = compute_token_hash(token)
    stmt = select(OrderConfirmation).where(OrderConfirmation.token_hash == token_hash)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def confirm_order(
    session: AsyncSession,
    token: str,
    fernet_key: bytes,
    skyfi_client: SkyFiClient | None = None,
    use_skip_locked: bool = False,
) -> tuple[OrderConfirmation, TaskingOrderResponse | ArchiveOrderResponse]:
    """Confirm a pending order: decrypt the token, place the order via SkyFi, update DB.

    This is the critical confirmation path (DESIGN_DECISIONS.md §1):
    1. Look up the record by token hash (with optional SKIP LOCKED for Postgres).
    2. Validate the record status.
    3. Decrypt the token to get the API key and order params.
    4. Place the order via SkyFi using the decrypted API key.
    5. Update the record to status="placed" with the SkyFi order ID.

    Args:
        session: Async SQLAlchemy session.
        token: The Fernet URL token string from the confirmation URL.
        fernet_key: Fernet symmetric key bytes.
        skyfi_client: Optional pre-built SkyFiClient (used for testing). If None,
                      a new client is built from the decrypted API key in the token.
        use_skip_locked: If True, use SELECT FOR UPDATE SKIP LOCKED (Postgres only).

    Returns:
        Tuple of (updated OrderConfirmation record, SkyFi order response).

    Raises:
        ToolError: With appropriate error code for expired, already-placed, or
                   already-cancelled orders.
    """
    token_hash = compute_token_hash(token)

    # --- Step 1: Fetch the record (with optional row lock for multi-instance Postgres) ---
    stmt = select(OrderConfirmation).where(
        OrderConfirmation.token_hash == token_hash,
    )
    if use_skip_locked:
        # TODO: With FOR UPDATE SKIP LOCKED, a concurrent request that races here
        # will get no row back and should treat it as "already being processed".
        stmt = stmt.with_for_update(skip_locked=True)

    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    # --- Step 2: Validate record state ---
    if record is None:
        raise ToolError(
            code=ErrorCode.ORDER_EXPIRED,
            message="Order not found. The link may be invalid or already expired.",
        )

    if record.status == "placed":
        raise ToolError(
            code=ErrorCode.ORDER_ALREADY_PLACED,
            message="This order has already been confirmed and placed with SkyFi.",
        )
    if record.status == "cancelled":
        raise ToolError(
            code=ErrorCode.ORDER_ALREADY_CANCELLED,
            message="This order was already cancelled. No charge occurred.",
        )
    if record.status == "expired":
        raise ToolError(
            code=ErrorCode.ORDER_EXPIRED,
            message="This order confirmation has expired.",
        )

    # --- Step 3: Decrypt token (validates TTL — raises ToolError if expired) ---
    payload = decrypt_confirmation_token(token, fernet_key)

    api_key: str = payload["api_key"]
    order_type: str = payload.get("order_type", record.order_type)
    order_params: dict[str, Any] = payload["order_params"]

    log.info(
        "confirmation_placing_order",
        token_hash=token_hash[:16] + "...",
        order_type=order_type,
    )

    # --- Step 4: Place order via SkyFi using the decrypted API key ---
    client = skyfi_client or SkyFiClient(api_key=api_key)
    should_close_client = skyfi_client is None

    try:
        order_response: TaskingOrderResponse | ArchiveOrderResponse
        if order_type == "TASKING":
            request = TaskingOrderRequest.model_validate(order_params)
            order_response = await client.create_tasking_order(request)
        else:
            request_archive = ArchiveOrderRequest.model_validate(order_params)
            order_response = await client.create_archive_order(request_archive)
    finally:
        if should_close_client:
            await client.close()

    # --- Step 5: Update the record to "placed" ---
    record.status = "placed"
    record.skyfi_order_id = uuid.UUID(str(order_response.id))
    record.confirmed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(record)

    log.info(
        "confirmation_order_placed",
        token_hash=token_hash[:16] + "...",
        skyfi_order_id=str(order_response.id),
        order_type=order_type,
    )

    return record, order_response


async def cancel_confirmation(
    session: AsyncSession, confirmation_id: uuid.UUID
) -> str:
    """Cancel a pending order confirmation by its database UUID.

    Args:
        session: Async SQLAlchemy session.
        confirmation_id: The UUID primary key of the OrderConfirmation record.

    Returns:
        A status message string appropriate for display.

    Raises:
        ToolError: With ORDER_ALREADY_PLACED if the order has already been placed.
    """
    stmt = select(OrderConfirmation).where(OrderConfirmation.id == confirmation_id)
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        return "Order not found."

    if record.status == "pending":
        record.status = "cancelled"
        await session.commit()
        log.info("confirmation_cancelled", confirmation_id=str(confirmation_id))
        return "Order cancelled. No charge will occur."

    if record.status == "placed":
        raise ToolError(
            code=ErrorCode.ORDER_ALREADY_PLACED,
            message="This order has already been confirmed and placed with SkyFi.",
        )

    # Already cancelled or expired
    return "This order was already cancelled or expired."


def resolve_base_url(request: Request, settings: Settings) -> str:
    """Resolve the server's public base URL for building confirmation/webhook URLs.

    Per DESIGN_DECISIONS.md §5 (layered base URL resolution):
    1. Explicit config: settings.confirmation_base_url
    2. Reverse-proxy headers: X-Forwarded-Proto + X-Forwarded-Host
    3. Host header from request
    4. Fallback: http://localhost:{port}

    Args:
        request: The FastAPI Request object.
        settings: Loaded Settings instance.

    Returns:
        Base URL string (no trailing slash), e.g. "https://purveyor.example.com".
    """
    if settings.confirmation_base_url:
        return settings.confirmation_base_url.rstrip("/")

    proto = (
        request.headers.get("X-Forwarded-Proto")
        or request.headers.get("x-forwarded-proto")
        or request.url.scheme
    )
    host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or f"localhost:{settings.server_port}"
    )

    return f"{proto}://{host}"
