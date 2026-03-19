"""Manual smoke test for the LangGraph agent.

Usage:
    source .venv/bin/activate
    python test_agent.py

Requires OPENAI_API_KEY and SKYFI_API_KEY (or test key) in .env.
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def test_whoami() -> None:
    """Test that the agent can call the whoami tool and return account info."""
    from graph import build_graph
    from tools import make_mcp_client

    skyfi_api_key = os.environ.get("SKYFI_API_KEY", "")
    if not skyfi_api_key:
        print("WARNING: SKYFI_API_KEY not set — tool calls will fail authentication.")

    print("Connecting to Purveyor MCP and building graph...")
    async with make_mcp_client(skyfi_api_key) as mcp_client:
        tools = mcp_client.get_tools()
        print(f"Discovered {len(tools)} tools: {[t.name for t in tools]}")

        graph = build_graph(tools)

        print("\nInvoking agent: 'Who am I? Use the whoami tool.'\n")
        result = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": "Who am I? Use the whoami tool."}],
                "current_aoi": None,
                "active_confirmation": None,
            }
        )

    last_msg = result["messages"][-1]
    print("Agent response:")
    print(last_msg.content)


async def test_streaming() -> None:
    """Test that the SSE stream emits expected event types."""
    from server import stream_response

    skyfi_api_key = os.environ.get("SKYFI_API_KEY", "")
    messages = [{"role": "user", "content": "Say hello and list your available tools briefly."}]

    print("\nStreaming events from /api/chat:\n")
    event_types: list[str] = []
    async for sse in stream_response(messages, skyfi_api_key):
        # Parse the SSE line to extract event type
        for line in sse.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
                event_types.append(event_type)
                print(f"  [{event_type}]")

    print(f"\nEvent sequence: {event_types}")
    assert "done" in event_types, "Stream must end with 'done' event"
    assert any(e == "text_delta" for e in event_types), "Stream must contain text_delta events"
    print("\nStreaming test PASSED")


if __name__ == "__main__":
    import sys

    test = sys.argv[1] if len(sys.argv) > 1 else "whoami"

    if test == "whoami":
        asyncio.run(test_whoami())
    elif test == "stream":
        asyncio.run(test_streaming())
    else:
        print(f"Unknown test: {test}. Use 'whoami' or 'stream'.")
        sys.exit(1)
