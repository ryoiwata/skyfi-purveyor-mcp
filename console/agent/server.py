from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from graph import build_graph  # noqa: E402 — load_dotenv must run first
from tools import make_mcp_client  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="Purveyor Console Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    messages: list[dict]
    skyfi_api_key: str


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_response(request.messages, request.skyfi_api_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


async def stream_response(messages: list[dict], skyfi_api_key: str):
    """Yield SSE-formatted events from the LangGraph agent."""
    try:
        async with make_mcp_client(skyfi_api_key) as mcp_client:
            tools = mcp_client.get_tools()
            agent_graph = build_graph(tools)

            initial_state = {
                "messages": messages,
                "current_aoi": None,
                "active_confirmation": None,
            }

            async for event in agent_graph.astream_events(initial_state, version="v2"):
                sse = _parse_event(event)
                if sse:
                    yield sse

    except RuntimeError as e:
        # MCP connection failure
        yield _format_sse("error", {"message": str(e), "code": "mcp_connection_error"})
    except Exception as e:
        logger.exception("Agent stream error")
        yield _format_sse("error", {"message": "An unexpected error occurred.", "code": "agent_error"})

    yield _format_sse("done", {})


def _parse_event(event: dict) -> str | None:
    """Parse a LangGraph astream_events v2 event into an SSE string."""
    kind = event.get("event")
    name = event.get("name", "")

    if kind == "on_chat_model_stream":
        chunk = event["data"].get("chunk")
        if chunk and hasattr(chunk, "content") and chunk.content:
            # content may be a string or list of content blocks
            content = chunk.content
            if isinstance(content, str) and content:
                return _format_sse("text_delta", {"token": content})
            elif isinstance(content, list):
                text = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
                if text:
                    return _format_sse("text_delta", {"token": text})

    elif kind == "on_tool_start" and name not in ("__start__", "agent", "tools"):
        return _format_sse("tool_call", {
            "tool": name,
            "input": event["data"].get("input", {}),
        })

    elif kind == "on_tool_end" and name not in ("__start__", "agent", "tools"):
        output = event["data"].get("output")
        if hasattr(output, "content"):
            output_data = _try_parse_json(output.content)
        else:
            output_data = output
        return _format_sse("tool_result", {
            "tool": name,
            "output": output_data,
        })

    return None


def _try_parse_json(text: str | list) -> dict | str | list:
    """Attempt to parse JSON string; return raw value on failure."""
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
