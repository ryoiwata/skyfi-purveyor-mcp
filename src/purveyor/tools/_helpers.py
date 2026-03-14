"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

from typing import Any

from purveyor.core.cache import CachedSkyFiClient

McpContext = Any  # Context[Any, Any, Any] — avoid circular imports


def get_api_key_from_ctx(ctx: McpContext) -> str:
    """Extract the SkyFi API key for the current request.

    In local mode, returns the server-configured key from Settings.
    In cloud mode, reads the X-Skyfi-Api-Key HTTP request header.
    """
    from typing import Any

    lc: dict[str, Any] = ctx.request_context.lifespan_context
    settings = lc["settings"]

    if settings.local_mode:
        return settings.skyfi_api_key or ""

    http_request = ctx.request_context.request
    if http_request is not None:
        return http_request.headers.get("x-skyfi-api-key", "")
    return ""


def get_skyfi_client(ctx: McpContext) -> CachedSkyFiClient:
    """Return an authenticated CachedSkyFiClient for this request.

    In local mode, returns the shared client from the lifespan context (API key
    is configured server-side via SKYFI_API_KEY / config.json).

    In cloud mode, extracts the X-Skyfi-Api-Key HTTP header from the current
    MCP request and constructs a per-request client with that key.  Each MCP
    tool call carries the header because the Google ADK / MCP client is
    configured to forward it on every POST to /mcp.
    """
    lc: dict[str, Any] = ctx.request_context.lifespan_context
    settings = lc["settings"]

    if settings.local_mode:
        return lc["cached_client"]

    # Cloud mode: the API key arrives in the HTTP request headers.
    # ctx.request_context.request is the Starlette Request object forwarded
    # through ServerMessageMetadata by the streamable-HTTP transport layer.
    http_request = ctx.request_context.request
    api_key = ""
    if http_request is not None:
        # Starlette Headers are case-insensitive; lowercase lookup is safe.
        api_key = http_request.headers.get("x-skyfi-api-key", "")

    return lc["make_client"](api_key)
