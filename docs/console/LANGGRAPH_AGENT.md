# Purveyor Console — LangGraph Agent Design

## Overview

The LangGraph agent is the AI backend for the Purveyor Console. It:
1. Receives conversation messages from the frontend via FastAPI
2. Connects to Purveyor MCP server and discovers its tools dynamically
3. Runs an agent loop using OpenAI gpt-4o + Purveyor tools
4. Streams responses (text tokens + tool results) back to the frontend via SSE

---

## Graph Definition

```
START → agent → [conditional] → tools → agent → ... → END
                    │
                    └── no tool calls → END
```

The graph runs in a loop: the agent generates a response (possibly with tool calls), executes tools if needed, returns results to the agent, and continues until the agent produces a response with no tool calls.

### Full Graph Code

```python
# agent/graph.py
from __future__ import annotations

import json
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .tools import get_purveyor_tools
from .system_prompt import SYSTEM_PROMPT


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_aoi: str | None          # WKT of most recent AOI (for agent context)
    active_confirmation: dict | None  # Pending order token + metadata


def should_continue(state: AgentState) -> str:
    """Route: if last message has tool calls → tools node, else → END."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END


async def call_model(state: AgentState, config: RunnableConfig) -> dict:
    """Agent node: call OpenAI with tools bound."""
    skyfi_api_key = config["configurable"]["skyfi_api_key"]
    tools = await get_purveyor_tools(skyfi_api_key)

    model = ChatOpenAI(model="gpt-4o", streaming=True, temperature=0)
    model_with_tools = model.bind_tools(tools)

    # Prepend system prompt to messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + state["messages"]
    response = await model_with_tools.ainvoke(messages)

    return {"messages": [response]}


async def call_tools(state: AgentState, config: RunnableConfig) -> dict:
    """Tools node: execute all pending tool calls."""
    skyfi_api_key = config["configurable"]["skyfi_api_key"]
    tools = await get_purveyor_tools(skyfi_api_key)
    tool_node = ToolNode(tools)
    return await tool_node.ainvoke(state, config)


# Build and compile the graph
builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", call_tools)
builder.set_entry_point("agent")
builder.add_conditional_edges(
    "agent",
    should_continue,
    {"tools": "tools", END: END},
)
builder.add_edge("tools", "agent")

graph = builder.compile()
```

---

## System Prompt

```python
# agent/system_prompt.py

SYSTEM_PROMPT = """You are a satellite imagery assistant powered by SkyFi's platform via Purveyor.
You help users search for, evaluate, and order satellite imagery of any location on Earth.

## Your Capabilities

You have access to SkyFi's satellite imagery platform through these tools:
- Search the archive of millions of existing satellite images
- Check feasibility and predict future satellite passes for tasking
- Get pricing information for any area
- Place and confirm imagery orders
- Set up monitoring for new imagery over areas of interest
- Geocode place names to coordinates
- Create and analyze areas of interest (AOIs)

## How to Work

**Always geocode first.** When a user mentions a location by name, call `geocode_location` before \
any search or order tool. This resolves the place name to a WKT polygon for the tools.

**Show what's available before ordering.** Before proposing any order, call `search_archives` to \
find existing imagery. Only suggest tasking (new capture) if archive imagery is unavailable or \
unsuitable. Always show `get_pricing` before generating a confirmation URL.

**Never place orders directly.** `create_archive_order` and `create_tasking_order` return a \
confirmation URL. Always include this URL in your response and tell the user to review the cost \
and confirm via the inline widget. Never describe an order as "placed" until the user confirms.

**Check feasibility for tasking.** Before recommending a tasking order, call `check_feasibility` \
to determine satellite access and timing.

**Be specific about costs.** When showing pricing, convert cents to dollars and round to two \
decimal places. Always state the total estimated cost prominently.

**Include archive links.** For any specific archive result, include the SkyFi URL so the user \
can view it directly: format as [View on SkyFi](url).

## Response Format

Structure your responses clearly:
- Use bullet points for lists of results (not walls of text)
- Lead with the most important information (best match, lowest price, soonest pass)
- State the cost before asking for confirmation — never bury it
- After a tool returns results, summarize the key findings in 2-3 sentences before listing details
- For errors, explain what went wrong and suggest a corrective action

## Boundaries

- You can only access imagery via Purveyor's tools — you cannot call SkyFi's API directly
- You do not have real-time news or events data — only what the satellite imagery metadata shows
- If asked about something unrelated to satellite imagery, politely redirect to your purpose
- If a tool returns an error, explain it clearly and suggest alternatives
"""
```

---

## MCP Tool Discovery

Tools are discovered from Purveyor MCP at the start of each tool execution. Because the SkyFi API key is user-specific and per-request, the MCP client must be created per-request.

```python
# agent/tools.py
from __future__ import annotations

import asyncio
import time
from functools import lru_cache

from langchain_mcp_adapters.client import MultiServerMCPClient

import os

PURVEYOR_MCP_URL = os.environ["PURVEYOR_MCP_URL"]

# Simple per-key cache: {api_key_hash: (tools, expires_at)}
_tool_cache: dict[str, tuple[list, float]] = {}
_CACHE_TTL = 300  # 5 minutes


async def get_purveyor_tools(skyfi_api_key: str) -> list:
    """
    Discover Purveyor MCP tools for the given API key.
    Results are cached per key for 5 minutes to avoid per-call overhead.
    """
    import hashlib
    key_hash = hashlib.sha256(skyfi_api_key.encode()).hexdigest()[:16]
    now = time.time()

    if key_hash in _tool_cache:
        tools, expires_at = _tool_cache[key_hash]
        if now < expires_at:
            return tools

    async with MultiServerMCPClient({
        "purveyor": {
            "url": PURVEYOR_MCP_URL,
            "transport": "streamable_http",
            "headers": {"X-Skyfi-Api-Key": skyfi_api_key},
        }
    }) as client:
        tools = client.get_tools()

    _tool_cache[key_hash] = (tools, now + _CACHE_TTL)
    return tools
```

**Important:** The `MultiServerMCPClient` context manager opens the MCP connection and performs tool discovery (calls `tools/list`). It must be kept alive for the duration of tool execution. The current design re-opens the connection each call. An optimization would be to hold the client open for the duration of a conversation turn.

### Connection Context Optimization (for later)

```python
# To hold the MCP connection open for an entire conversation turn:
async def run_with_mcp_client(messages, skyfi_api_key):
    async with MultiServerMCPClient({...}) as client:
        tools = client.get_tools()
        # Build graph with these tools bound
        # Run the full astream_events within this context
        async for event in graph.astream_events(...):
            yield event
```

---

## Streaming Implementation

The FastAPI server streams agent events to the frontend in SSE format.

```python
# agent/server.py
from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .graph import graph

logger = logging.getLogger(__name__)
app = FastAPI(title="Purveyor Console Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    messages: list[dict]
    skyfi_api_key: str


class ChatMessage(BaseModel):
    role: str
    content: str


@app.post("/api/chat")
async def chat(request: ChatRequest):
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
async def health():
    return {"status": "ok"}


async def stream_response(messages: list[dict], skyfi_api_key: str):
    """Yield SSE events from the LangGraph agent."""
    config = {
        "configurable": {
            "skyfi_api_key": skyfi_api_key,
        }
    }

    initial_state = {
        "messages": messages,
        "current_aoi": None,
        "active_confirmation": None,
    }

    try:
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            sse = parse_langgraph_event(event)
            if sse:
                yield sse
    except Exception as e:
        logger.exception("Agent stream error")
        yield format_sse("error", {"message": str(e), "code": "agent_error"})

    yield format_sse("done", {})


def parse_langgraph_event(event: dict) -> str | None:
    """Parse a LangGraph astream_events event into an SSE string."""
    kind = event.get("event")
    name = event.get("name", "")

    # Text token from LLM
    if kind == "on_chat_model_stream":
        chunk = event["data"].get("chunk")
        if chunk and hasattr(chunk, "content") and chunk.content:
            return format_sse("text_delta", {"token": chunk.content})

    # Tool call initiated
    elif kind == "on_tool_start" and name != "__start__":
        return format_sse("tool_call", {
            "tool": name,
            "input": event["data"].get("input", {}),
        })

    # Tool call completed
    elif kind == "on_tool_end" and name != "__start__":
        output = event["data"].get("output")
        # LangGraph tool output may be a ToolMessage; extract content
        if hasattr(output, "content"):
            output_data = _try_parse_json(output.content)
        else:
            output_data = output
        return format_sse("tool_result", {
            "tool": name,
            "output": output_data,
        })

    return None


def _try_parse_json(text: str) -> dict | str:
    """Attempt to parse JSON; return raw string on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
```

---

## Error Handling

### MCP Connection Failure
If `MultiServerMCPClient` cannot connect to Purveyor, tool discovery raises a connection error. The stream_response function catches this and emits an `error` SSE event.

```python
# In get_purveyor_tools:
try:
    async with MultiServerMCPClient({...}) as client:
        return client.get_tools()
except Exception as e:
    raise RuntimeError(
        f"Could not connect to Purveyor MCP server at {PURVEYOR_MCP_URL}. "
        f"Ensure the server is running and the URL is correct. Error: {e}"
    ) from e
```

Frontend renders: "Could not connect to Purveyor. Check that the server is running."

### Tool Execution Error
Purveyor returns structured error responses (see its DESIGN_DECISIONS.md). LangGraph surfaces these as `ToolMessage` with the error content. The agent then explains the error to the user.

For infrastructure errors (MCP JSON-RPC errors), the agent receives an error message and should explain it:
- `aoi_too_large` → "The requested area is too large. I'll clip it to 500,000 sq km."
- `no_results` → "No imagery found for that location and time range. Try expanding the date range or adjusting the resolution filter."
- `skyfi_unavailable` → "SkyFi's API is currently unavailable. Please try again in a few minutes."

### OpenAI Rate Limiting
`langchain-openai` raises `RateLimitError` on 429 responses. Wrap with tenacity:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import RateLimitError

@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(3),
)
async def invoke_with_retry(model_with_tools, messages):
    return await model_with_tools.ainvoke(messages)
```

### Conversation State
If the agent returns a malformed state (missing keys), the `call_model` and `call_tools` functions should return safe defaults:

```python
# Defensive state handling in call_model
return {
    "messages": [response],
    # Don't include current_aoi or active_confirmation unless updating them
    # LangGraph merges state, so omitting keys preserves existing values
}
```

---

## Multi-Turn Tool Use

A single user message may result in multiple tool call rounds. Example:

```
User: "Find imagery of the Suez Canal and order the cheapest result"

Turn 1:
  agent → tool_calls: [geocode_location("Suez Canal")]
  tools → ToolMessage: {lat: 30.5, lon: 32.3, wkt: "POLYGON(...)"}

Turn 2:
  agent → tool_calls: [search_archives(aoi=wkt), get_pricing(aoi=wkt)]
  tools → ToolMessage: {archives: [...]}
          ToolMessage: {pricing: {...}}

Turn 3:
  agent → tool_calls: [create_archive_order(archive_id="abc", aoi=wkt)]
  tools → ToolMessage: {confirmation_url: "...", estimated_cost_cents: 45000}

Turn 4:
  agent → text: "I found 8 archives... The cheapest is $120.00...
                 [Confirmation widget rendered by frontend]"
  (no tool calls → graph ends)
```

The frontend receives SSE events for each tool call and result, updating the map and chat incrementally throughout the multi-turn sequence. This is the key UX advantage: the map updates after each tool, not only after the agent finishes responding.

---

## Running Locally

```bash
cd console/agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install langgraph langchain-openai langchain-mcp-adapters \
            fastapi uvicorn python-dotenv structlog pydantic tenacity

# Create .env
cat > .env << EOF
OPENAI_API_KEY=sk-...
PURVEYOR_MCP_URL=http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp
EOF

# Run the agent server
uvicorn server:app --reload --port 8001

# Test the endpoint
curl -N -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Who am I?"}],"skyfi_api_key":"YOUR_KEY"}'
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `langgraph` | ≥0.2 | Agent graph definition and execution |
| `langchain-openai` | ≥0.2 | OpenAI gpt-4o integration |
| `langchain-mcp-adapters` | ≥0.1 | Connect to Purveyor MCP, convert tools to LangChain format |
| `langchain-core` | ≥0.3 | Message types, RunnableConfig |
| `fastapi` | ≥0.115 | HTTP server for SSE streaming endpoint |
| `uvicorn[standard]` | ≥0.32 | ASGI server |
| `pydantic` | ≥2.0 | Request/response validation |
| `tenacity` | ≥8.0 | Retry logic for OpenAI rate limits |
| `python-dotenv` | ≥1.0 | Load .env file in development |
| `structlog` | ≥24.0 | Structured logging |

Install all:
```bash
pip install langgraph langchain-openai langchain-mcp-adapters langchain-core \
            fastapi uvicorn[standard] pydantic tenacity python-dotenv structlog
```

---

## Design Decisions

**Why LangGraph over vanilla LangChain AgentExecutor?**
LangGraph's `astream_events` API gives fine-grained control over event streaming — we can distinguish between `on_chat_model_stream` (text tokens), `on_tool_start` (loading indicators), and `on_tool_end` (map updates). LangChain's older AgentExecutor doesn't provide the same event granularity.

**Why gpt-4o and not gpt-4o-mini?**
Satellite imagery workflows require following multi-step instructions precisely: geocode first, check pricing before ordering, never place orders directly. gpt-4o follows the system prompt more reliably. gpt-4o-mini can be offered as a cheaper alternative in the settings panel.

**Why per-request MCP connection?**
Each user has a different SkyFi API key. The MCP connection carries the key in headers. We cannot share a single connection across users. The 5-minute tool cache mitigates the latency cost of tool discovery.

**Why SSE over WebSocket?**
SSE is simpler (one-directional), natively supported by browsers without extra libraries, and sufficient for this use case. The frontend sends messages via regular `POST`, and the response is streamed. WebSocket would add complexity without benefit here.

**Why FastAPI and not LangServe?**
LangServe adds a dependency and its streaming API has changed across versions. A simple FastAPI endpoint with `astream_events` is more explicit, easier to debug, and gives full control over the SSE event format the frontend expects.
