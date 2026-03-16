"""In-memory store for demo webhook events.

Holds the most recent 100 order webhook events received at POST /webhooks/orders.
Shared between the FastAPI route and the list_webhook_events MCP tool via module
import — both run in the same process.

This is intentionally ephemeral (survives requests, not restarts), suitable for
demo and testing purposes only.
"""

from __future__ import annotations

from collections import deque
from typing import Any

# Module-level deque capped at 100 events. appendleft() keeps newest first.
order_webhook_events: deque[dict[str, Any]] = deque(maxlen=100)
