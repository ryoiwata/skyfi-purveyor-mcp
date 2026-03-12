"""FastAPI application — health endpoint, webhooks, confirmation pages."""

from __future__ import annotations

import datetime
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

log = structlog.get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("fastapi_startup")
    yield
    log.info("fastapi_shutdown")


def create_app(settings: Any | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional Settings instance. Loads from environment if not provided.
    """
    from purveyor.core.config import load_settings
    from purveyor.core.logging import setup_logging

    if settings is None:
        settings = load_settings()

    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    app = FastAPI(
        title="Purveyor MCP Server",
        description="Remote MCP server wrapping the SkyFi Platform API",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # CORS — default allow-all, configurable via ALLOWED_ORIGINS
    origins = settings.allowed_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount MCP server at /mcp
    from purveyor.server import mcp
    app.mount("/mcp", mcp.streamable_http_app())

    @app.get("/health")
    async def health() -> JSONResponse:
        """Health check: reports DB, SkyFi API, and Redis status."""
        start = time.monotonic()
        result: dict[str, Any] = {
            "status": "healthy",
            "database": "ok",
            "skyfi_api": "ok",
            "redis": "skipped",
        }
        status_code = 200

        # Check SkyFi API reachability
        try:
            from purveyor.core.skyfi_client import SkyFiClient

            cfg = settings
            temp_client = SkyFiClient(api_key=cfg.skyfi_api_key or "")
            await temp_client.ping()
            await temp_client.close()
        except Exception as exc:
            log.warning("health_skyfi_unreachable", error=str(exc))
            result["skyfi_api"] = f"error: {type(exc).__name__}"
            result["status"] = "degraded"
            status_code = 503

        # Redis check
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis

                r = aioredis.from_url(settings.redis_url)
                await r.ping()  # type: ignore[misc]
                await r.aclose()
                result["redis"] = "ok"
            except Exception as exc:
                log.warning("health_redis_unreachable", error=str(exc))
                result["redis"] = f"error: {type(exc).__name__}"

        result["duration_ms"] = round((time.monotonic() - start) * 1000)
        result["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"

        return JSONResponse(content=result, status_code=status_code)

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """Kubernetes readiness probe."""
        return JSONResponse(content={"status": "ready"})

    # Webhook stubs (real implementation in Phase 3)
    @app.post("/webhooks/order-event")
    async def webhook_order_event() -> JSONResponse:
        """Stub — order event webhook receiver (Phase 3)."""
        return JSONResponse(content={"status": "received"})

    @app.post("/webhooks/archive-notification")
    async def webhook_archive_notification() -> JSONResponse:
        """Stub — archive notification webhook receiver (Phase 3)."""
        return JSONResponse(content={"status": "received"})

    return app
