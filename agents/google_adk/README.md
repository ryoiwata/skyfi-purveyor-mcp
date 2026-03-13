# Google ADK Agent for Purveyor

A [Google ADK](https://google.github.io/adk-docs/) test agent that connects to Purveyor (the SkyFi MCP server) via Gemini. Users can conversationally search satellite image archives, get pricing, check tasking feasibility, place orders, and monitor deliveries — all through natural language.

## Overview

This agent uses ADK's `McpToolset` to connect to Purveyor's `/mcp` endpoint and expose all Purveyor tools to a Gemini-powered LLM agent. Three connection options are provided:

| Option | File | When to use |
|--------|------|-------------|
| A (SSE/HTTP) | `agent.py` | Development + demos — full `adk web` UI |
| B (Stdio) | `agent_stdio.py` | Embedded mode — Purveyor runs as subprocess |
| C (Programmatic) | `test_programmatic.py` | Scripted tests — no browser UI needed |

## Prerequisites

- Python 3.11+ (Purveyor requires 3.11; ADK requires 3.9+)
- [google-adk](https://pypi.org/project/google-adk/) installed: `pip install google-adk python-dotenv`
- A [Gemini API key](https://aistudio.google.com/apikey) (`GOOGLE_GENAI_API_KEY`)
- A [SkyFi API key](https://app.skyfi.com) (`SKYFI_API_KEY`)
- Purveyor running (see below)

## Quick Start — Option A: SSE/HTTP (Recommended)

**Step 1:** Copy the env template and fill in your keys:

```bash
cp .env.example .env
# Edit .env and set GOOGLE_GENAI_API_KEY, SKYFI_API_KEY
```

**Step 2:** Start Purveyor (from the project root):

```bash
uv run purveyor serve --local
# Purveyor listens at http://localhost:8000
```

**Step 3:** Launch the ADK web UI (from `agents/google_adk/`):

```bash
cd agents/google_adk
adk web
```

**Step 4:** Open `http://localhost:8080` (ADK's default port), select `satellite_imagery_agent`, and start chatting.

### Example prompts

```
Show me recent satellite imagery of the Port of Rotterdam with less than 10% cloud cover
What would it cost to get high-resolution imagery of Suez Canal?
Check feasibility for tasking over Kyiv, Ukraine in the next 2 weeks
Search for open data imagery over Austin, TX from 2024
Who am I? (verify your SkyFi account)
```

## Option B: Stdio Mode

Purveyor runs as a subprocess instead of a separate HTTP server.

**Step 1:** Rename `agent_stdio.py` to `agent.py` (save the original as `agent_sse.py`), OR update `__init__.py`:

```python
# __init__.py
from . import agent_stdio as agent  # use stdio instead
```

**Step 2:** Run `adk web` as normal.

> **Important:** The order confirmation flow requires an HTTP server. If you use stdio mode, confirmation URLs (`http://localhost:8000/confirm/...`) will not work unless you also run Purveyor's HTTP server with the same `CONFIRMATION_SECRET_KEY`:
>
> ```bash
> # Terminal 1: HTTP server (for confirmations)
> CONFIRMATION_SECRET_KEY=<your-key> uv run purveyor serve --local
>
> # Terminal 2: adk web with stdio agent
> cd agents/google_adk
> adk web
> ```

## Option C: Programmatic Testing

Run queries without `adk web` — useful for smoke testing or CI:

```bash
# Purveyor must be running first
uv run purveyor serve --local &

cd agents/google_adk
python test_programmatic.py
```

The script fires three queries and prints responses:
1. "Who am I?" — verifies auth and API key
2. "Geocode 'Central Park, New York'" — verifies geocoding tool
3. "Search for recent satellite imagery of Central Park with less than 20% cloud cover" — end-to-end tool chain

## Connecting to AWS (or any remote Purveyor instance)

Just change `PURVEYOR_URL` in your `.env`:

```env
PURVEYOR_URL=https://your-purveyor-instance.example.com
```

The ADK agent will connect to the remote Purveyor MCP endpoint. Authentication (`X-Skyfi-Api-Key`) is passed in headers automatically.

## Tool Filtering

By default, all Purveyor tools are exposed to the agent. For production use cases, you may want to restrict which tools are available:

```python
# In agent.py, uncomment and adjust tool_filter:
McpToolset(
    connection_params=...,
    tool_filter=[
        "search_archives",
        "get_archive_details",
        "get_pricing",
        "geocode_location",
        "create_aoi_from_point",
        "whoami",
    ],
)
```

Use `tool_filter` to:
- Reduce the agent's "surface area" for focused use cases
- Prevent destructive operations (exclude order-creating tools for read-only agents)
- Improve response quality by reducing tool choice noise

## Available Tools

All 20 tools exposed by Purveyor (as of March 2026):

| Tool | Description |
|------|-------------|
| `whoami` | Get the authenticated SkyFi account info |
| `search_archives` | Search satellite image archives by location, date, resolution, cloud cover |
| `get_archive_details` | Get detailed metadata for a specific archive image |
| `get_pricing` | Get pricing for imagery in an AOI |
| `check_feasibility` | Check feasibility for a new tasking order |
| `get_pass_predictions` | Get satellite pass predictions for a location and time window |
| `create_archive_order` | Initiate an archive image order (returns confirmation URL) |
| `create_tasking_order` | Initiate a new tasking order (returns confirmation URL) |
| `list_orders` | List all orders for the authenticated account |
| `get_order_status` | Get the status of a specific order |
| `download_deliverable` | Get download URL for an order deliverable |
| `cancel_pending_order` | Cancel a pending confirmation (before user confirms) |
| `request_redelivery` | Request redelivery of a completed order |
| `setup_monitoring` | Set up AOI monitoring for new archive imagery |
| `list_notifications` | List active monitoring notifications |
| `get_notification_history` | Get event history for a notification |
| `delete_notification` | Delete an AOI monitoring notification |
| `geocode_location` | Geocode a place name to coordinates and WKT polygon |
| `create_aoi_from_point` | Create an AOI polygon from a center point and area |
| `calculate_aoi_area` | Calculate the area of a WKT polygon in sq km |

## Troubleshooting

### `Connection refused` when running `adk web`

Purveyor is not running. Start it first:

```bash
uv run purveyor serve --local
```

### `No tools found` in the ADK UI

1. Check that Purveyor started successfully: `curl http://localhost:8000/health`
2. Verify `PURVEYOR_URL` in your `.env` matches the Purveyor address
3. Check `SKYFI_API_KEY` is set — Purveyor requires it to authenticate the MCP session

### Confirmation links don't work

If you're using stdio mode, the HTTP server is not running. Start a separate Purveyor HTTP instance on the same port that confirmation URLs point to (default `http://localhost:8000`).

### `ImportError: cannot import name 'SseConnectionParams'`

Your google-adk version may use a different import path. Try:

```python
# Newer ADK versions may use:
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

# And replace SseConnectionParams with:
StreamableHTTPConnectionParams(url=f"{PURVEYOR_URL}/mcp", headers=...)
```

Check your installed version: `pip show google-adk`

### `ModuleNotFoundError: No module named 'google.adk'`

Install ADK:

```bash
pip install google-adk python-dotenv
```

ADK requires Python 3.9+. Purveyor requires Python 3.11+. Use 3.11+ for both.

### Windows: `NotImplementedError` from subprocess transport

Run `adk web --no-reload` instead:

```bash
adk web --no-reload
```

## Important Notes

- **Stdio mode + HTTP confirmations:** Both the stdio subprocess and the HTTP server must use the same `CONFIRMATION_SECRET_KEY`. Generate one with `uv run purveyor generate-key`.
- **structlog in stdio mode:** Purveyor writes logs to stderr by default, which prevents contaminating the MCP JSON-RPC stream on stdout. Do not redirect stderr or change `LOG_FORMAT` to anything that writes to stdout.
- **ADK version:** This agent was written against google-adk 0.2.0+. The `McpToolset` API and connection parameter classes may differ in earlier or later versions.
- **Model choice:** `gemini-2.0-flash` is the default. You can change it to `gemini-2.5-pro` or any available Gemini model for better reasoning on complex multi-step tasks.
