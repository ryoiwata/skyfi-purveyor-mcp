# Purveyor MCP — Google ADK Integration

Add SkyFi satellite imagery to any [Google ADK](https://google.github.io/adk-docs/) agent in three lines.

## Add SkyFi Satellite Imagery to Your ADK Agent

Copy this into your agent's `tools` list:

```python
import os
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp",
        headers={"X-Skyfi-Api-Key": os.environ.get("SKYFI_API_KEY", "")},
    ),
)
```

Set your keys in `.env`:

```env
GOOGLE_API_KEY=your-gemini-api-key
SKYFI_API_KEY=your-skyfi-api-key
```

That's it. Your agent now has 20 satellite imagery tools.

## Run the Example Agent

If you don't have an existing agent and want to try it out:

```bash
pip install google-adk python-dotenv
cp .env.example .env  # fill in your keys
cd agents/google_adk
adk web --port 8080
```

Open `http://localhost:8080` and select `satellite_imagery_agent`.

**Example prompts:**

```
Show me recent satellite imagery of the Port of Rotterdam with less than 10% cloud cover
What would it cost to get high-resolution imagery of the Suez Canal?
Check feasibility for tasking over Kyiv, Ukraine in the next 2 weeks
Who am I?
```

## Test the Connection

Verify Purveyor is reachable and your API key works — no Gemini key required:

```bash
python test_connection.py
```

Expected output:

```
Connecting to http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp ...

✅ Connected! Found 20 tools:

  calculate_aoi_area: Calculate the area of a WKT polygon in sq km...
  cancel_pending_order: Cancel a pending confirmation before the user confirms...
  ...

Purveyor MCP is working. Add McpToolset to your agent's tools list to get started.
```

## Available Tools

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

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SKYFI_API_KEY` | Yes | — | SkyFi API key from [app.skyfi.com](https://app.skyfi.com) |
| `GOOGLE_API_KEY` | Yes | — | Gemini API key from [aistudio.google.com](https://aistudio.google.com/apikey) |
| `PURVEYOR_URL` | No | AWS deployment | Purveyor server base URL |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model name |

To limit which tools are exposed to the agent, use `tool_filter` in `McpToolset`:

```python
McpToolset(
    connection_params=...,
    tool_filter=["search_archives", "get_pricing", "geocode_location", "whoami"],
)
```

## Self-Hosted Purveyor

Running your own Purveyor instance? Change `PURVEYOR_URL`:

```env
PURVEYOR_URL=http://localhost:8000
```

See the [main README](../../README.md) for Purveyor setup instructions. For advanced use cases like stdio transport (embedding Purveyor as a subprocess), see the [ADK MCP docs](https://google.github.io/adk-docs/tools/mcp-tools/).

## Troubleshooting

**`No tools found` in the ADK UI**
- Verify Purveyor is reachable: `curl http://purveyor-691022321.us-east-1.elb.amazonaws.com/health`
- Check `SKYFI_API_KEY` is set — Purveyor requires it to authenticate the MCP session
- Run `python test_connection.py` to isolate connection issues from ADK issues

**`429` with `limit: 0`**
The Gemini model has no free-tier quota on your API key. Try `gemini-2.0-flash` or enable billing.

**`ModuleNotFoundError: No module named 'google.adk'`**

```bash
pip install google-adk python-dotenv
```

ADK requires Python 3.9+. Use Python 3.11+ to match Purveyor.
