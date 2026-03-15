"""Tests for the demo webhook receiver endpoints (POST/GET /webhooks/orders)
and the list_webhook_events MCP tool.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.requests import Request

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _order_event_payload(
    order_id: str = "order-abc-123", status: str = "DELIVERY_COMPLETED"
) -> dict[str, Any]:
    return {
        "order_info": {
            "id": order_id,
            "order_type": "ARCHIVE",
        },
        "event": {
            "status": status,
            "timestamp": "2026-03-15T12:00:00Z",
            "message": None,
        },
    }


@pytest.fixture(autouse=True)
def clear_webhook_store() -> Any:
    """Clear the in-memory webhook store before each test."""
    from purveyor.core.webhook_store import order_webhook_events

    order_webhook_events.clear()
    yield
    order_webhook_events.clear()


@pytest.fixture
def http_app() -> Any:
    """Minimal FastAPI test app with only the demo webhook routes from app.py."""
    from purveyor.core.webhook_store import order_webhook_events

    app = FastAPI()

    @app.post("/webhooks/orders")
    async def receive_order_webhook(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        order_webhook_events.appendleft(
            {
                "received_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "payload": body,
            }
        )
        return JSONResponse(content={"status": "ok"})

    @app.get("/webhooks/orders")
    async def list_order_webhooks(limit: int = 20) -> JSONResponse:
        clamped = max(1, min(limit, 100))
        events = list(order_webhook_events)[:clamped]
        return JSONResponse(
            content={
                "total_stored": len(order_webhook_events),
                "showing": len(events),
                "events": events,
            }
        )

    @app.get("/webhooks/orders/ui", response_class=HTMLResponse)
    async def webhook_events_ui() -> HTMLResponse:
        return HTMLResponse(content="<html><body>events ui</body></html>")

    return app


# ---------------------------------------------------------------------------
# POST /webhooks/orders
# ---------------------------------------------------------------------------


async def test_receive_webhook_returns_200(http_app: Any) -> None:
    """POST /webhooks/orders always returns 200."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        resp = await client.post("/webhooks/orders", json=_order_event_payload())

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_receive_webhook_stores_event(http_app: Any) -> None:
    """POSTing a webhook payload stores it in the in-memory deque."""
    from httpx import ASGITransport, AsyncClient

    from purveyor.core.webhook_store import order_webhook_events

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        await client.post(
            "/webhooks/orders", json=_order_event_payload(order_id="order-xyz", status="CREATED")
        )

    assert len(order_webhook_events) == 1
    stored = order_webhook_events[0]
    assert stored["payload"]["order_info"]["id"] == "order-xyz"
    assert "received_at" in stored


async def test_receive_webhook_newest_first(http_app: Any) -> None:
    """Events are stored newest-first (appendleft)."""
    from httpx import ASGITransport, AsyncClient

    from purveyor.core.webhook_store import order_webhook_events

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        await client.post("/webhooks/orders", json=_order_event_payload(order_id="first"))
        await client.post("/webhooks/orders", json=_order_event_payload(order_id="second"))

    assert order_webhook_events[0]["payload"]["order_info"]["id"] == "second"
    assert order_webhook_events[1]["payload"]["order_info"]["id"] == "first"


async def test_receive_webhook_capped_at_100(http_app: Any) -> None:
    """Deque maxlen=100 drops oldest entries once full."""
    from httpx import ASGITransport, AsyncClient

    from purveyor.core.webhook_store import order_webhook_events

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        for i in range(105):
            await client.post("/webhooks/orders", json=_order_event_payload(order_id=f"order-{i}"))

    assert len(order_webhook_events) == 100


async def test_receive_webhook_invalid_json_stored_as_empty_dict(http_app: Any) -> None:
    """POST with non-JSON body is gracefully stored as empty dict, returns 200."""
    from httpx import ASGITransport, AsyncClient

    from purveyor.core.webhook_store import order_webhook_events

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/orders",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    assert order_webhook_events[0]["payload"] == {}


# ---------------------------------------------------------------------------
# GET /webhooks/orders
# ---------------------------------------------------------------------------


async def test_list_webhooks_empty(http_app: Any) -> None:
    """GET /webhooks/orders returns empty list when no events stored."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        resp = await client.get("/webhooks/orders")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_stored"] == 0
    assert data["showing"] == 0
    assert data["events"] == []


async def test_list_webhooks_returns_stored_events(http_app: Any) -> None:
    """GET /webhooks/orders returns all stored events."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        for i in range(3):
            await client.post("/webhooks/orders", json=_order_event_payload(order_id=f"order-{i}"))
        resp = await client.get("/webhooks/orders")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_stored"] == 3
    assert data["showing"] == 3
    assert len(data["events"]) == 3


async def test_list_webhooks_limit_param(http_app: Any) -> None:
    """GET /webhooks/orders?limit=2 returns at most 2 events."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        for i in range(5):
            await client.post("/webhooks/orders", json=_order_event_payload(order_id=f"order-{i}"))
        resp = await client.get("/webhooks/orders?limit=2")

    data = resp.json()
    assert data["total_stored"] == 5
    assert data["showing"] == 2
    assert len(data["events"]) == 2


# ---------------------------------------------------------------------------
# GET /webhooks/orders/ui
# ---------------------------------------------------------------------------


async def test_webhook_ui_returns_html(http_app: Any) -> None:
    """GET /webhooks/orders/ui returns an HTML page."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        resp = await client.get("/webhooks/orders/ui")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# list_webhook_events MCP tool — direct function calls
# ---------------------------------------------------------------------------


async def test_list_webhook_events_tool_empty() -> None:
    """list_webhook_events returns empty-state summary when no events stored."""
    from mcp.server.fastmcp import FastMCP

    from purveyor.tools.webhook_events import register

    mcp = FastMCP("test")
    register(mcp)
    tool_fn = mcp._tool_manager._tools["list_webhook_events"].fn

    result = await tool_fn(limit=10)
    assert result["total_stored"] == 0
    assert result["showing"] == 0
    assert result["events"] == []
    assert "No webhook events" in result["summary"]


async def test_list_webhook_events_tool_with_events() -> None:
    """list_webhook_events returns structured events with skyfi_order_url."""
    from mcp.server.fastmcp import FastMCP

    from purveyor.core.webhook_store import order_webhook_events
    from purveyor.tools.webhook_events import register

    order_webhook_events.appendleft(
        {
            "received_at": "2026-03-15T12:00:00Z",
            "payload": {
                "order_info": {"id": "order-999", "order_type": "ARCHIVE"},
                "event": {"status": "DELIVERY_COMPLETED", "message": None},
            },
        }
    )

    mcp = FastMCP("test")
    register(mcp)
    tool_fn = mcp._tool_manager._tools["list_webhook_events"].fn

    result = await tool_fn(limit=10)

    assert result["total_stored"] == 1
    assert result["showing"] == 1
    event = result["events"][0]
    assert event["order_id"] == "order-999"
    assert event["status"] == "DELIVERY_COMPLETED"
    assert event["order_type"] == "ARCHIVE"
    assert "skyfi_order_url" in event
    assert "order-999" in event["skyfi_order_url"]
    assert "order-999" in result["summary"]


async def test_list_webhook_events_tool_limit_respected() -> None:
    """list_webhook_events respects limit parameter."""
    from mcp.server.fastmcp import FastMCP

    from purveyor.core.webhook_store import order_webhook_events
    from purveyor.tools.webhook_events import register

    for i in range(10):
        order_webhook_events.appendleft(
            {
                "received_at": "2026-03-15T12:00:00Z",
                "payload": {
                    "order_info": {"id": f"order-{i}", "order_type": "ARCHIVE"},
                    "event": {"status": "CREATED", "message": None},
                },
            }
        )

    mcp = FastMCP("test")
    register(mcp)
    tool_fn = mcp._tool_manager._tools["list_webhook_events"].fn

    result = await tool_fn(limit=3)
    assert result["total_stored"] == 10
    assert result["showing"] == 3
    assert len(result["events"]) == 3


async def test_list_webhook_events_adds_skyfi_url_only_when_order_id_present() -> None:
    """Events without an order_id do not get a skyfi_order_url key."""
    from mcp.server.fastmcp import FastMCP

    from purveyor.core.webhook_store import order_webhook_events
    from purveyor.tools.webhook_events import register

    order_webhook_events.appendleft(
        {
            "received_at": "2026-03-15T12:00:00Z",
            "payload": {
                "event": {"status": "UNKNOWN", "message": None},
            },
        }
    )

    mcp = FastMCP("test")
    register(mcp)
    tool_fn = mcp._tool_manager._tools["list_webhook_events"].fn

    result = await tool_fn(limit=10)
    event = result["events"][0]
    assert event["order_id"] == ""
    assert "skyfi_order_url" not in event
