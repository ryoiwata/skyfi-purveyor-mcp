"""MCP server setup — Streamable HTTP and stdio transports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from purveyor import __version__
from purveyor.core.cache import CachedSkyFiClient, get_cache_backend
from purveyor.core.config import load_settings
from purveyor.core.logging import setup_logging
from purveyor.core.skyfi_client import SkyFiClient
from purveyor.models.database import create_engine, create_session_factory, init_db

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Startup and shutdown lifecycle for the MCP server.

    Yields a dict with keys:
      - settings: Settings instance
      - cached_client: CachedSkyFiClient
      - cache: CacheBackend (raw, for geocoding cache)
      - session_factory: async session factory
    """
    settings = load_settings()
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)
    log.info("purveyor_starting", version=__version__, local_mode=settings.local_mode)

    # Database
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine)

    # SkyFi client + cache
    api_key = settings.skyfi_api_key or ""
    cache = get_cache_backend(settings)
    client = SkyFiClient(api_key=api_key)
    cached_client = CachedSkyFiClient(client, cache)

    def make_client(key: str) -> CachedSkyFiClient:
        """Create a per-request CachedSkyFiClient with the given API key.

        Used in cloud mode to build a client from the X-Skyfi-Api-Key header.
        """
        return CachedSkyFiClient(SkyFiClient(api_key=key), cache)

    log.info("purveyor_ready")

    try:
        yield {
            "settings": settings,
            "cached_client": cached_client,
            "make_client": make_client,
            "cache": cache,
            "session_factory": session_factory,
        }
    finally:
        log.info("purveyor_shutting_down")
        await client.close()
        await engine.dispose()


# Create the MCP server instance.
# DNS rebinding protection is disabled: the X-Skyfi-Api-Key header is the auth
# boundary (per DESIGN_DECISIONS §CORS). Purveyor runs behind a load balancer
# whose hostname would otherwise fail host validation.
mcp = FastMCP(
    "purveyor",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _register_all() -> None:
    """Import and register all tools and resources onto the MCP server."""
    from purveyor.resources.skyfi_resources import register as register_resources
    from purveyor.tools.account import register as register_account
    from purveyor.tools.archives import register as register_archives
    from purveyor.tools.feasibility import register as register_feasibility
    from purveyor.tools.geospatial import register as register_geospatial
    from purveyor.tools.notifications import register as register_notifications
    from purveyor.tools.orders import register as register_orders
    from purveyor.tools.osm import register as register_osm
    from purveyor.tools.preview import register as register_preview
    from purveyor.tools.pricing import register as register_pricing
    from purveyor.tools.webhook_events import register as register_webhook_events

    register_geospatial(mcp)
    register_osm(mcp)
    register_archives(mcp)
    register_preview(mcp)
    register_pricing(mcp)
    register_feasibility(mcp)
    register_orders(mcp)
    register_account(mcp)
    register_notifications(mcp)
    register_webhook_events(mcp)
    register_resources(mcp)


_register_all()
