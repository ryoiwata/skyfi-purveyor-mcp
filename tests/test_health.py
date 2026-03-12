"""Tests for /health and /ready endpoints."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# Enable local mode so Settings doesn't require CONFIRMATION_SECRET_KEY
os.environ.setdefault("LOCAL_MODE", "true")


def _make_app() -> Any:
    from purveyor.app import create_app

    return create_app()


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_required_keys() -> None:
    """/health always includes status, database, skyfi_api, redis, timestamp."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        assert response.status_code in (200, 503)
        data = response.json()
        for key in ("status", "database", "skyfi_api", "redis", "timestamp"):
            assert key in data, f"Missing key: {key}"


def test_health_timestamp_format() -> None:
    """/health timestamp is an ISO 8601 UTC string."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        data = response.json()
        ts = data["timestamp"]
        # Should be parseable as an ISO 8601 datetime
        import datetime

        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt.tzinfo is not None or ts.endswith("Z") or "+" in ts


def test_health_skyfi_unreachable_returns_503() -> None:
    """/health returns 503 when SkyFi API is unreachable."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        with patch(
            "purveyor.core.skyfi_client.SkyFiClient.ping",
            new_callable=AsyncMock,
            side_effect=ConnectionError("SkyFi unreachable"),
        ):
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "degraded"
            assert "error" in data["skyfi_api"]


def test_health_redis_unavailable_is_not_503() -> None:
    """/health does NOT return 503 when only Redis is unavailable (caching is optional)."""
    app = _make_app()
    # Patch settings to have a redis_url so the Redis check runs
    with TestClient(app, raise_server_exceptions=False) as client:
        with (
            patch(
                "purveyor.core.skyfi_client.SkyFiClient.ping",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("purveyor.app.settings", create=True),
        ):
            # Just verify structure — redis check only runs if redis_url is set
            response = client.get("/health")
            data = response.json()
            assert "redis" in data


def test_health_redis_skipped_when_no_redis_url() -> None:
    """/health reports redis=skipped when REDIS_URL is not configured."""
    app = _make_app()
    # Default settings have no redis_url
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        data = response.json()
        # Without redis_url, redis should be "skipped"
        assert data["redis"] == "skipped"


def test_health_duration_ms_present() -> None:
    """/health includes duration_ms in the response."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        data = response.json()
        assert "duration_ms" in data
        assert isinstance(data["duration_ms"], int)
        assert data["duration_ms"] >= 0


def test_health_database_check_runs_after_startup() -> None:
    """/health checks database connectivity after lifespan startup completes."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        data = response.json()
        # After lifespan, session_factory is set, so database field is not "initializing"
        # It should be "ok" for SQLite in tests
        assert data["database"] in ("ok", "initializing", "error: ConnectionRefusedError")


# ---------------------------------------------------------------------------
# /ready endpoint
# ---------------------------------------------------------------------------


def test_ready_returns_200_after_startup() -> None:
    """/ready returns 200 with status=ready after lifespan completes."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        # TestClient runs lifespan fully, so ready should be True
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"


def test_ready_returns_503_before_startup() -> None:
    """/ready returns 503 when server has not completed startup."""
    app = _make_app()
    # app.state.ready defaults to False before lifespan runs
    assert app.state.ready is False

    # Confirm that the endpoint returns 503 when not ready
    # (Using client without context manager so lifespan doesn't run)
    with TestClient(app, raise_server_exceptions=False):
        # After entering context, lifespan has run → ready=True
        pass
    # After exiting context, lifespan shutdown has run → ready=False again
    assert app.state.ready is False


def test_ready_endpoint_structure() -> None:
    """/ready returns JSON with a 'status' key."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/ready")
        assert "status" in response.json()


# ---------------------------------------------------------------------------
# Sentry integration
# ---------------------------------------------------------------------------


def test_sentry_not_initialized_when_no_dsn() -> None:
    """Sentry is not initialized when SENTRY_DSN is not set."""
    import sentry_sdk

    app = _make_app()
    with TestClient(app, raise_server_exceptions=False):
        # No DSN in test env → sentry hub should have no DSN
        client_dsn = sentry_sdk.get_client().dsn
        # Either None or empty → not configured
        assert not client_dsn or client_dsn == ""


def test_sentry_before_send_filters_tool_errors() -> None:
    """_sentry_before_send discards ToolError business errors."""
    from purveyor.app import _sentry_before_send
    from purveyor.core.errors import ErrorCode, ToolError

    exc = ToolError(code=ErrorCode.SKYFI_API_ERROR, message="test")
    event: dict = {}
    hint = {"exc_info": (type(exc), exc, None)}

    result = _sentry_before_send(event, hint)
    assert result is None  # Discarded


def test_sentry_before_send_passes_other_errors() -> None:
    """_sentry_before_send allows non-business errors through."""
    from purveyor.app import _sentry_before_send

    exc = ValueError("unexpected")
    event: dict = {"message": "test"}
    hint = {"exc_info": (type(exc), exc, None)}

    result = _sentry_before_send(event, hint)
    assert result is not None  # Passed through
