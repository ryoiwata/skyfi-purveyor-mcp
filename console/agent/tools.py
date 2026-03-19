from __future__ import annotations

import hashlib
import os
import time

from langchain_mcp_adapters.client import MultiServerMCPClient

PURVEYOR_MCP_URL = os.environ.get(
    "PURVEYOR_MCP_URL",
    "http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp",
)

# Per-key tool cache: {key_hash: (tools, expires_at)}
_tool_cache: dict[str, tuple[list, float]] = {}
_CACHE_TTL = 300  # 5 minutes


def _key_hash(skyfi_api_key: str) -> str:
    return hashlib.sha256(skyfi_api_key.encode()).hexdigest()[:16]


async def get_purveyor_tools(skyfi_api_key: str) -> list:
    """Discover Purveyor MCP tools for the given API key (cached 5 min)."""
    key_hash = _key_hash(skyfi_api_key)
    now = time.time()

    if key_hash in _tool_cache:
        tools, expires_at = _tool_cache[key_hash]
        if now < expires_at:
            return tools

    try:
        async with MultiServerMCPClient(
            {
                "purveyor": {
                    "url": PURVEYOR_MCP_URL,
                    "transport": "streamable_http",
                    "headers": {"X-Skyfi-Api-Key": skyfi_api_key},
                }
            }
        ) as client:
            tools = client.get_tools()
    except Exception as e:
        raise RuntimeError(
            f"Could not connect to Purveyor MCP server at {PURVEYOR_MCP_URL}. "
            f"Ensure the server is running. Error: {e}"
        ) from e

    _tool_cache[key_hash] = (tools, now + _CACHE_TTL)
    return tools


def make_mcp_client(skyfi_api_key: str) -> MultiServerMCPClient:
    """Create a fresh MCP client context manager for a request."""
    return MultiServerMCPClient(
        {
            "purveyor": {
                "url": PURVEYOR_MCP_URL,
                "transport": "streamable_http",
                "headers": {"X-Skyfi-Api-Key": skyfi_api_key},
            }
        }
    )
