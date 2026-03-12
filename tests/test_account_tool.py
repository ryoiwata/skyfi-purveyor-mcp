"""Tests for the whoami MCP tool and account tier inference."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.core.skyfi_types import WhoamiUser
from purveyor.server import mcp


def _whoami_user(
    is_demo: bool = False,
    budget_amount: int = 100_000,
    current_budget_usage: int = 10_000,
    has_valid_card: bool = True,
) -> WhoamiUser:
    return WhoamiUser(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="test@example.com",
        first_name="Test",
        last_name="User",
        is_demo_account=is_demo,
        current_budget_usage=current_budget_usage,
        budget_amount=budget_amount,
        has_valid_shared_card=has_valid_card,
    )


def _make_ctx(cached_client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": MagicMock(geocoding_base_url="https://nominatim.openstreetmap.org"),
        "cache": MagicMock(),
        "session_factory": None,
    }
    return ctx


@pytest.mark.asyncio
async def test_whoami_returns_user_info() -> None:
    """whoami returns user email and name."""
    user = _whoami_user()
    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(return_value=user)

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["email"] == "test@example.com"
    assert result["name"] == "Test User"


@pytest.mark.asyncio
async def test_whoami_demo_account_tier() -> None:
    """Demo account is identified as 'demo' tier with 1 open data order per day."""
    user = _whoami_user(is_demo=True)
    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(return_value=user)

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert result["account_tier"] == "demo"
    assert result["open_data_daily_limit"] == 1
    assert result["is_demo_account"] is True


@pytest.mark.asyncio
async def test_whoami_pro_account_tier() -> None:
    """Account with > $1000 budget is 'pro' tier with 5 open data orders per day."""
    user = _whoami_user(is_demo=False, budget_amount=500_000)  # $5000
    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(return_value=user)

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert result["account_tier"] == "pro"
    assert result["open_data_daily_limit"] == 5


@pytest.mark.asyncio
async def test_whoami_free_account_tier() -> None:
    """Account with <= $1000 budget and not demo is 'free' tier."""
    user = _whoami_user(is_demo=False, budget_amount=50_000)  # $500 — below threshold
    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(return_value=user)

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert result["account_tier"] == "free"
    assert result["open_data_daily_limit"] == 1


@pytest.mark.asyncio
async def test_whoami_budget_calculation() -> None:
    """Budget remaining is correctly calculated."""
    user = _whoami_user(budget_amount=100_000, current_budget_usage=30_000)
    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(return_value=user)

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert result["budget_total_cents"] == 100_000
    assert result["budget_used_cents"] == 30_000
    assert result["budget_remaining_cents"] == 70_000


@pytest.mark.asyncio
async def test_whoami_api_error_returns_error_result() -> None:
    """SkyFi API error returns isError=True result."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(side_effect=Exception("API down"))

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


@pytest.mark.asyncio
async def test_whoami_summary_contains_tier() -> None:
    """Summary mentions the account tier."""
    user = _whoami_user(is_demo=False, budget_amount=200_000)
    cached_client = MagicMock()
    cached_client.whoami = AsyncMock(return_value=user)

    tool_fn = mcp._tool_manager.get_tool("whoami").fn
    result = await tool_fn(ctx=_make_ctx(cached_client))

    assert "Pro" in result["summary"] or "pro" in result["summary"].lower()
