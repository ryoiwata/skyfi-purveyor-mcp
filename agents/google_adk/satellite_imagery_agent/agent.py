"""
Google ADK agent — Option A: SSE/HTTP connection to a running Purveyor server.

Prerequisites:
  pip install google-adk python-dotenv
  cp .env.example .env  # fill in GOOGLE_GENAI_API_KEY, SKYFI_API_KEY, PURVEYOR_URL

Usage:
  cd agents/google_adk
  adk web
  # Then open http://localhost:8000 and select satellite_imagery_agent
"""

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

load_dotenv()

PURVEYOR_URL = os.environ.get("PURVEYOR_URL", "http://localhost:8000")
SKYFI_API_KEY = os.environ.get("SKYFI_API_KEY", "")

root_agent = LlmAgent(
    model="gemini-2.0-flash",
    name="satellite_imagery_agent",
    instruction="""You are a satellite imagery assistant powered by SkyFi via Purveyor.
You can help users:
- Search satellite image archives by location, date, resolution, and cloud cover
- Get pricing for imagery
- Check feasibility for new tasking orders
- Place archive and tasking orders (requires user confirmation via browser)
- Monitor order status and download deliverables
- Geocode locations and create areas of interest

When a user asks about satellite imagery for a location, start by geocoding the
location, then search archives. Always tell the user about pricing before ordering.
When placing orders, explain that they'll need to confirm via a browser link.""",
    tools=[
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=f"{PURVEYOR_URL}/mcp",
                headers={"X-Skyfi-Api-Key": SKYFI_API_KEY},
            ),
            # Optional: limit which tools are exposed to the agent
            # tool_filter=[
            #     "search_archives",
            #     "get_archive_details",
            #     "get_pricing",
            #     "geocode_location",
            #     "create_aoi_from_point",
            #     "list_orders",
            #     "get_order_status",
            # ],
        )
    ],
)
