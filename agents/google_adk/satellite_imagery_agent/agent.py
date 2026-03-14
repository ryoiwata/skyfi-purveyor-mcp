"""
Google ADK satellite imagery agent — connects to Purveyor MCP via HTTP.

Prerequisites:
  pip install google-adk python-dotenv
  cp .env.example .env  # fill in GOOGLE_API_KEY and SKYFI_API_KEY

Usage:
  cd agents/google_adk
  adk web --port 8080
  # Open http://localhost:8080 and select satellite_imagery_agent
"""

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

load_dotenv()

PURVEYOR_URL = os.environ.get(
    "PURVEYOR_URL", "http://purveyor-691022321.us-east-1.elb.amazonaws.com"
)
SKYFI_API_KEY = os.environ.get("SKYFI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

root_agent = LlmAgent(
    model=GEMINI_MODEL,
    name="satellite_imagery_agent",
    instruction="You are a satellite imagery assistant powered by SkyFi. "
    "Help users search archives, check pricing and feasibility, place orders, "
    "and monitor deliveries. Orders require user confirmation via a browser link. "
    "Each archive object includes these image URL fields: "
    "`thumbnail_url` (a direct image URL provided by SkyFi — use this to show users a preview image) "
    "and `preview_url` (an interactive viewer link that shows the image cropped to the search AOI). "
    "Always prefer `thumbnail_url` for displaying the image. Use `preview_url` as a clickable viewer link. "
    "Do NOT use any URL containing '/explore/archive/' — that page fails for many providers. "
    "Each archive has its own `min_sq_km` and `max_sq_km` fields that define the AOI size limits "
    "for ordering. If the search AOI is outside those limits, use create_aoi_from_point to create "
    "a correctly-sized AOI before calling create_archive_order. "
    "For most use cases, 25-100 km² is a good default AOI size.",
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
