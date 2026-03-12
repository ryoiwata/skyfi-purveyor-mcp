"""Tests for MCP resources: skyfi:// URIs."""

from __future__ import annotations

import json

import pytest

from purveyor.server import mcp


async def _read_resource(uri: str) -> str:
    """Helper to read a resource by URI."""
    resources = await mcp.list_resources()
    resource_map = {str(r.uri): r for r in resources}
    assert uri in resource_map, f"Resource {uri} not found. Available: {list(resource_map.keys())}"
    results = await mcp.read_resource(uri)
    # read_resource returns an iterable of ReadResourceContents
    return next(iter(results)).content  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_providers_list_resource() -> None:
    """skyfi://providers/list returns valid JSON with providers array."""
    content = await _read_resource("skyfi://providers/list")
    data = json.loads(content)
    assert "providers" in data
    assert isinstance(data["providers"], list)
    assert len(data["providers"]) > 0
    assert data["total"] == len(data["providers"])
    # Each provider has id and name
    for p in data["providers"]:
        assert "id" in p
        assert "name" in p


@pytest.mark.asyncio
async def test_resolutions_list_resource() -> None:
    """skyfi://resolutions/list returns valid JSON with resolutions array."""
    content = await _read_resource("skyfi://resolutions/list")
    data = json.loads(content)
    assert "resolutions" in data
    assert isinstance(data["resolutions"], list)
    assert len(data["resolutions"]) > 0
    # Each resolution has id and value
    for r in data["resolutions"]:
        assert "id" in r
        assert "value" in r


@pytest.mark.asyncio
async def test_providers_include_planet() -> None:
    """Providers list includes PLANET (well-known SkyFi provider)."""
    content = await _read_resource("skyfi://providers/list")
    data = json.loads(content)
    provider_ids = {p["id"] for p in data["providers"]}
    assert "PLANET" in provider_ids


@pytest.mark.asyncio
async def test_resolutions_include_very_high() -> None:
    """Resolutions list includes VERY HIGH tier."""
    content = await _read_resource("skyfi://resolutions/list")
    data = json.loads(content)
    resolution_values = {r["value"] for r in data["resolutions"]}
    assert "VERY HIGH" in resolution_values


@pytest.mark.asyncio
async def test_pricing_current_resource_returns_json() -> None:
    """skyfi://pricing/current returns valid JSON."""
    content = await _read_resource("skyfi://pricing/current")
    data = json.loads(content)
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_orders_recent_resource_returns_json() -> None:
    """skyfi://orders/recent returns valid JSON."""
    content = await _read_resource("skyfi://orders/recent")
    data = json.loads(content)
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_account_info_resource_returns_json() -> None:
    """skyfi://account/info returns valid JSON."""
    content = await _read_resource("skyfi://account/info")
    data = json.loads(content)
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_resources_count() -> None:
    """At least 5 resources registered."""
    resources = await mcp.list_resources()
    assert len(resources) >= 5, f"Only {len(resources)} resources registered"
