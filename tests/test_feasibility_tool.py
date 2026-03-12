"""Tests for check_feasibility (dual-mode) and get_pass_predictions MCP tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from purveyor.core.skyfi_types import (
    ApiProvider,
    FeasibilityResponse,
    FeasibilityScore,
    Pass,
    PassPredictionResponse,
    ProviderCombinedScore,
    WeatherScore,
)
from purveyor.server import mcp

FEASIBILITY_ID = str(uuid.uuid4())
SIMPLE_WKT = "POLYGON((-97.76 30.24, -97.72 30.24, -97.72 30.28, -97.76 30.28, -97.76 30.24))"


def _pending_feasibility() -> FeasibilityResponse:
    return FeasibilityResponse(
        id=uuid.UUID(FEASIBILITY_ID),
        validUntil=datetime(2024, 6, 15, 11, 0, 0, tzinfo=UTC),
        overall_score=None,
    )


def _complete_feasibility() -> FeasibilityResponse:
    return FeasibilityResponse(
        id=uuid.UUID(FEASIBILITY_ID),
        validUntil=datetime(2024, 6, 15, 11, 0, 0, tzinfo=UTC),
        overall_score=FeasibilityScore(
            feasibility=0.85,
            weatherScore=WeatherScore(weatherScore=0.9),
            providerScore=ProviderCombinedScore(score=0.8, providerScores=[]),
        ),
    )


def _make_pass() -> Pass:
    return Pass(
        provider=ApiProvider.PLANET,
        satname="dove-1",
        satid="SAT-001",
        noradid="12345",
        node="node1",
        productType="DAY",
        resolution="VERY HIGH",
        lat=30.27,
        lon=-97.74,
        passDate=datetime(2024, 6, 15, 14, 30, 0, tzinfo=UTC),
        meanT=90,
        offNadirAngle=15.0,
        solarElevationAngle=45.0,
        minSquareKms=1.0,
        maxSquareKms=100.0,
        priceForOneSquareKm=5.0,
        gsdDegMin=0.00003,
        gsdDegMax=0.00004,
    )


def _make_ctx(cached_client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    mock_settings = MagicMock()
    mock_settings.geocoding_base_url = "https://nominatim.openstreetmap.org"
    ctx.request_context.lifespan_context = {
        "cached_client": cached_client,
        "settings": mock_settings,
        "cache": MagicMock(get=AsyncMock(return_value=None), set=AsyncMock()),
        "session_factory": None,
    }
    return ctx


# ---------------------------------------------------------------------------
# check_feasibility — check mode (feasibility_id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_feasibility_check_mode_complete() -> None:
    """Check mode returns complete results when score is available."""
    cached_client = MagicMock()
    cached_client.get_feasibility_status = AsyncMock(return_value=_complete_feasibility())

    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn
    result = await tool_fn(feasibility_id=FEASIBILITY_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, dict)
    assert result["status"] == "complete"
    assert result["overall_score"] == 0.85
    assert "HIGH" in result["summary"]


@pytest.mark.asyncio
async def test_check_feasibility_check_mode_pending() -> None:
    """Check mode returns pending when score is not yet available."""
    cached_client = MagicMock()
    cached_client.get_feasibility_status = AsyncMock(return_value=_pending_feasibility())

    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn
    result = await tool_fn(feasibility_id=FEASIBILITY_ID, ctx=_make_ctx(cached_client))

    assert result["status"] == "pending"
    assert result["feasibility_id"] == FEASIBILITY_ID


@pytest.mark.asyncio
async def test_check_feasibility_check_mode_api_error() -> None:
    """Check mode API failure returns isError=True."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_feasibility_status = AsyncMock(side_effect=Exception("timeout"))

    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn
    result = await tool_fn(feasibility_id=FEASIBILITY_ID, ctx=_make_ctx(cached_client))

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# check_feasibility — create mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_feasibility_create_mode_returns_pending_after_polls() -> None:
    """Create mode returns pending status if check never completes in time."""
    cached_client = MagicMock()
    cached_client.create_feasibility_task = AsyncMock(return_value=_pending_feasibility())
    # All polls return pending
    cached_client.get_feasibility_status = AsyncMock(return_value=_pending_feasibility())

    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn

    # Patch asyncio.sleep to avoid actual waiting
    with patch("purveyor.tools.feasibility.asyncio.sleep", new_callable=AsyncMock):
        result = await tool_fn(
            location=SIMPLE_WKT,
            product_type="DAY",
            resolution="VERY HIGH",
            start_date="2024-06-01",
            end_date="2024-06-30",
            ctx=_make_ctx(cached_client),
        )

    assert result["status"] == "pending"
    assert "feasibility_id" in result
    # 3 quick polls were made
    assert cached_client.get_feasibility_status.call_count == 3


@pytest.mark.asyncio
async def test_check_feasibility_create_mode_returns_complete_on_quick_poll() -> None:
    """Create mode returns complete results if SkyFi completes during quick poll."""
    cached_client = MagicMock()
    cached_client.create_feasibility_task = AsyncMock(return_value=_pending_feasibility())
    # First poll returns complete
    cached_client.get_feasibility_status = AsyncMock(return_value=_complete_feasibility())

    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn

    with patch("purveyor.tools.feasibility.asyncio.sleep", new_callable=AsyncMock):
        result = await tool_fn(
            location=SIMPLE_WKT,
            product_type="DAY",
            resolution="VERY HIGH",
            start_date="2024-06-01",
            end_date="2024-06-30",
            ctx=_make_ctx(cached_client),
        )

    assert result["status"] == "complete"
    assert result["overall_score"] == 0.85


@pytest.mark.asyncio
async def test_check_feasibility_create_mode_no_location_error() -> None:
    """Create mode without location returns invalid_input."""
    import json

    from mcp.types import CallToolResult

    cached_client = MagicMock()
    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn
    result = await tool_fn(
        product_type="DAY",
        resolution="VERY HIGH",
        start_date="2024-06-01",
        end_date="2024-06-30",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert json.loads(result.content[0].text)["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_check_feasibility_invalid_product_type() -> None:
    """Invalid product_type returns invalid_input error."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    tool_fn = mcp._tool_manager.get_tool("check_feasibility").fn
    result = await tool_fn(
        location=SIMPLE_WKT,
        product_type="FAKE_TYPE",
        resolution="VERY HIGH",
        start_date="2024-06-01",
        end_date="2024-06-30",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True


# ---------------------------------------------------------------------------
# get_pass_predictions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pass_predictions_returns_sorted_passes() -> None:
    """Pass predictions are sorted by date."""
    from datetime import timedelta

    pass1 = _make_pass()
    pass2 = _make_pass()
    pass2.pass_date = pass1.pass_date + timedelta(days=1)

    cached_client = MagicMock()
    cached_client.get_pass_predictions = AsyncMock(
        return_value=PassPredictionResponse(passes=[pass2, pass1])
    )

    tool_fn = mcp._tool_manager.get_tool("get_pass_predictions").fn
    result = await tool_fn(
        location=SIMPLE_WKT,
        from_date="2024-06-01",
        to_date="2024-06-30",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, dict)
    assert result["total"] == 2
    # Sorted by date ascending
    dates = [p["pass_date"] for p in result["passes"]]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_get_pass_predictions_no_results_returns_error() -> None:
    """No passes returns no_results error."""
    from mcp.types import CallToolResult

    cached_client = MagicMock()
    cached_client.get_pass_predictions = AsyncMock(
        return_value=PassPredictionResponse(passes=[])
    )

    tool_fn = mcp._tool_manager.get_tool("get_pass_predictions").fn
    result = await tool_fn(
        location=SIMPLE_WKT,
        from_date="2024-06-01",
        to_date="2024-06-30",
        ctx=_make_ctx(cached_client),
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
