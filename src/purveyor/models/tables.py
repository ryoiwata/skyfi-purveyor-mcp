"""SQLAlchemy ORM table definitions for Purveyor.

Schema is based on DESIGN_DECISIONS.md §2 (order_confirmations), §3 (webhook_events),
§4 (notification_registry), and SPEC.md §5.1 (background_tasks, geocode_cache).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from purveyor.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OrderConfirmation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks pending and completed order confirmations.

    Per DESIGN_DECISIONS.md §2: API key and order params are in the Fernet-encrypted
    URL token, NOT in this table. This table tracks status, routing info, and
    the resulting SkyFi order ID only.
    """

    __tablename__ = "order_confirmations"

    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
        comment="SHA-256 hex digest of the Fernet URL token",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="pending | confirmed | placed | expired | cancelled",
    )
    order_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="TASKING or ARCHIVE",
    )
    api_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="SHA-256 hex digest of the SkyFi API key (for SSE routing)",
    )
    mcp_session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="MCP session ID for SSE notification routing",
    )
    skyfi_order_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="Set after the order is successfully placed with SkyFi",
    )
    estimated_cost_cents: Mapped[int | None] = mapped_column(
        Integer(), nullable=True,
        comment="Estimated cost shown on the confirmation page",
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    order_payload_json: Mapped[str | None] = mapped_column(
        Text(), nullable=True,
        comment=(
            "JSON blob with order_params and webhook_url; not security-sensitive. "
            "NULL on records created before migration b1c2d3e4f5a6 (params in token)."
        ),
    )


class WebhookEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Log of all inbound webhook events from SkyFi.

    Per DESIGN_DECISIONS.md §3: events persist here first, then are delivered
    to active SSE streams or queued for reconnect delivery.
    """

    __tablename__ = "webhook_events"

    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="order_status | archive_notification",
    )
    # Use Text for SQLite compatibility (JSONB only in Postgres)
    payload: Mapped[str] = mapped_column(
        Text(), nullable=False,
        comment="Raw JSON payload from SkyFi",
    )
    api_key_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="SHA-256 of the owning API key (for reconnect delivery routing)",
    )
    delivered: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, index=True,
        comment="Whether this event has been delivered to an active session",
    )
    event_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True,
        comment="SkyFi-provided event ID for idempotency deduplication",
    )


class BackgroundTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks background task execution state for recovery on restart."""

    __tablename__ = "background_tasks"

    task_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="poll_feasibility | poll_order_confirmation",
    )
    payload: Mapped[str] = mapped_column(
        Text(), nullable=False,
        comment="JSON-encoded task parameters",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="pending | running | completed | failed",
    )
    result: Mapped[str | None] = mapped_column(
        Text(), nullable=True,
        comment="JSON-encoded task result or error",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0,
    )


class NotificationRegistry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Maps SkyFi notification IDs to owner API key hashes for webhook routing.

    Per DESIGN_DECISIONS.md §4: When SkyFi fires an archive notification webhook,
    this table is used to look up which user's session to notify.
    """

    __tablename__ = "notification_registry"

    # Override UUID pk to use notification_id as the primary key
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        comment="SkyFi notification_id (the primary key IS the notification ID)",
    )
    api_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="SHA-256 of the API key that created this notification",
    )


class GeocodeCache(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cache for OpenStreetMap Nominatim geocoding results.

    Spatial columns (coordinates, bounding_box) are only used with PostGIS.
    For SQLite, raw_response contains the full OSM data.
    """

    __tablename__ = "geocode_cache"

    place_name: Mapped[str] = mapped_column(
        String(500), nullable=False, index=True,
        comment="Normalized place name used as the lookup key",
    )
    display_name: Mapped[str | None] = mapped_column(
        Text(), nullable=True,
        comment="Full human-readable resolved place name from OSM",
    )
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    raw_response: Mapped[str | None] = mapped_column(
        Text(), nullable=True,
        comment="JSON-encoded raw OSM response",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
