"""Tests for FastAPI app — health endpoint, readiness probe, MCP tool/resource registration."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

# Enable local mode so Settings doesn't require CONFIRMATION_SECRET_KEY
os.environ.setdefault("LOCAL_MODE", "true")

from purveyor.server import mcp

# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def test_tools_registered() -> None:
    """All expected Phase 2 tools are registered on the MCP server."""
    tools = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "geocode_location",
        "create_aoi_from_point",
        "calculate_aoi_area",
        "search_archives",
        "get_archive_details",
        "get_pricing",
        "check_feasibility",
        "get_pass_predictions",
        "list_orders",
        "get_order_status",
        "download_deliverable",
        "whoami",
        "setup_monitoring",
        "list_notifications",
        "get_notification_history",
        "delete_notification",
    }
    assert expected.issubset(tools), f"Missing tools: {expected - tools}"


def test_resources_registered() -> None:
    """All expected Phase 2 resources are registered on the MCP server."""
    import asyncio

    async def _get_resources() -> list[str]:
        resources = await mcp.list_resources()
        return [str(r.uri) for r in resources]

    uris = asyncio.run(_get_resources())
    expected = {
        "skyfi://pricing/current",
        "skyfi://orders/recent",
        "skyfi://account/info",
        "skyfi://providers/list",
        "skyfi://resolutions/list",
    }
    assert expected.issubset(set(uris)), f"Missing resources: {expected - set(uris)}"


def test_tool_count_at_least_16() -> None:
    """At least 16 tools registered (Phase 2 target)."""
    tools = mcp._tool_manager.list_tools()
    assert len(tools) >= 16, f"Only {len(tools)} tools registered"


# ---------------------------------------------------------------------------
# FastAPI health endpoint
# ---------------------------------------------------------------------------


def test_ready_endpoint() -> None:
    """/ready returns 200 after lifespan startup completes."""
    from purveyor.app import create_app

    app = create_app()
    # Use context manager so lifespan runs, setting app.state.ready = True
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"


def test_health_endpoint_structure() -> None:
    """/health returns a dict with required keys (SkyFi may be degraded in test env)."""
    from purveyor.app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        # Accept either 200 (healthy) or 503 (degraded — no SkyFi in test env)
        assert response.status_code in (200, 503)
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "skyfi_api" in data
        assert "timestamp" in data


def test_health_keys_present() -> None:
    """/health always returns timestamp and status keys regardless of SkyFi."""
    from purveyor.app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        data = response.json()
        for key in ("status", "database", "skyfi_api", "redis", "timestamp"):
            assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Webhook endpoints (real implementation)
# ---------------------------------------------------------------------------


def test_webhook_order_event_requires_token() -> None:
    """Webhook order-event without token returns 401."""
    from purveyor.app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/webhooks/order-event", json={"event": "test"})
        assert response.status_code == 401


def test_webhook_archive_notification_requires_token() -> None:
    """Webhook archive-notification without token returns 401."""
    from purveyor.app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/webhooks/archive-notification", json={"archiveId": "x"})
        assert response.status_code == 401
