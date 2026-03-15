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
    "\n\n"
    "ARCHIVE PREVIEWS: Each archive object includes: "
    "`thumbnail_url` (SkyFi-provided image — use this to show users a preview image) and "
    "`preview_url` (interactive viewer with AOI overlay). "
    "Always prefer `thumbnail_url` for displaying images. "
    "NEVER use any URL containing '/explore/archive/' — that page fails for many providers. "
    "\n\n"
    "ORDER URLS: Each order object includes `skyfi_order_url` — use this as the clickable "
    "link for users to view their order on the SkyFi website. "
    "NEVER use `download_image_url` as a browser link — it is an authenticated API endpoint "
    "that requires headers and will show 'Missing api key' in a browser. "
    "To provide a download link for a completed order, call download_deliverable to get a "
    "signed URL, then share that with the user. "
    "\n\n"
    "NOTIFICATIONS: When listing notifications, each notification includes `skyfi_explore_url` — "
    "share this as a clickable link so users can browse current imagery in their monitored area. "
    "When showing notification history, each event includes `skyfi_preview_url` — "
    "use this to show users a preview of the specific image that triggered the alert. "
    "The notification itself also includes `skyfi_explore_url` for the monitored AOI. "
    "\n\n"
    "AOI SIZING: Each archive has `min_sq_km` and `max_sq_km` fields. "
    "If the search AOI is outside those limits, use create_aoi_from_point to create "
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
