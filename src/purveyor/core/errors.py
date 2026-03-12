"""Error types and codes for Purveyor MCP tools.

Business errors use isError=True in MCP content (not JSON-RPC errors).
Infrastructure errors (DB down, unhandled exceptions) raise MCPError.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx
from mcp.types import CallToolResult, TextContent


class ErrorCode(StrEnum):
    """Structured error codes for business errors returned from tools."""

    AOI_TOO_LARGE = "aoi_too_large"
    AOI_TOO_MANY_VERTICES = "aoi_too_many_vertices"
    NO_RESULTS = "no_results"
    RATE_LIMITED = "rate_limited"
    INVALID_INPUT = "invalid_input"
    SKYFI_API_ERROR = "skyfi_api_error"
    SKYFI_UNAVAILABLE = "skyfi_unavailable"
    ORDER_EXPIRED = "order_expired"
    ORDER_ALREADY_CONFIRMED = "order_already_confirmed"
    ORDER_ALREADY_CANCELLED = "order_already_cancelled"
    ORDER_ALREADY_PLACED = "order_already_placed"
    FEASIBILITY_TIMEOUT = "feasibility_timeout"
    OPEN_DATA_LIMIT_REACHED = "open_data_limit_reached"
    NOMINATIM_UNAVAILABLE = "nominatim_unavailable"


@dataclass
class ToolError(Exception):
    """A structured business error for return from MCP tool handlers.

    Business errors use isError=True in the MCP content, not JSON-RPC errors.
    Infrastructure errors (DB down, unhandled exceptions) should raise MCPError.
    """

    code: str
    message: str
    detail: Any = field(default=None)

    def to_call_tool_result(self) -> CallToolResult:
        """Convert to a CallToolResult with isError=True."""
        structured: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            structured["detail"] = self.detail
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(structured, indent=2))],
            isError=True,
        )


def skyfi_error_from_response(response: httpx.Response) -> ToolError:
    """Map a SkyFi API HTTP error response to a ToolError.

    Args:
        response: The httpx.Response with a 4xx or 5xx status code.

    Returns:
        A ToolError with an appropriate code and message.
    """
    status = response.status_code
    try:
        body = response.json()
        api_message: str = str(body.get("message") or body.get("error") or body)
    except Exception:
        api_message = response.text or f"HTTP {status}"

    if status in (401, 403):
        return ToolError(
            code=ErrorCode.SKYFI_API_ERROR,
            message=f"SkyFi authentication failed: {api_message}",
            detail={"status_code": status},
        )
    if status == 402:
        if "open data" in api_message.lower() or "limit" in api_message.lower():
            return ToolError(
                code=ErrorCode.OPEN_DATA_LIMIT_REACHED,
                message=(
                    "You've reached your daily open data order limit. "
                    "Free accounts can place 1 open data order per day; "
                    "Pro accounts can place up to 5. "
                    "You can upgrade at app.skyfi.com or try again tomorrow."
                ),
                detail={"status_code": status},
            )
        return ToolError(
            code=ErrorCode.SKYFI_API_ERROR,
            message=f"SkyFi payment error: {api_message}",
            detail={"status_code": status},
        )
    if status == 422:
        return ToolError(
            code=ErrorCode.INVALID_INPUT,
            message=f"SkyFi rejected the request: {api_message}",
            detail={"status_code": status},
        )
    if 400 <= status < 500:
        return ToolError(
            code=ErrorCode.SKYFI_API_ERROR,
            message=f"SkyFi API error ({status}): {api_message}",
            detail={"status_code": status},
        )
    # 5xx
    return ToolError(
        code=ErrorCode.SKYFI_UNAVAILABLE,
        message=f"SkyFi API is temporarily unavailable ({status}): {api_message}",
        detail={"status_code": status},
    )
