"""
Google ADK agent — Option B: Stdio connection (Purveyor runs as a subprocess).

This is an ALTERNATIVE to agent.py. To use it:
  1. Rename this file to agent.py (and rename the original to agent_sse.py), OR
  2. Update __init__.py to import from agent_stdio instead of agent.

Important: The confirmation flow requires an HTTP server. When using stdio mode,
confirmation URLs (e.g. http://localhost:8000/confirm/...) will not work unless
you ALSO run Purveyor's HTTP server separately with the same CONFIRMATION_SECRET_KEY.

Note: Purveyor writes logs via structlog. In stdio mode, structlog must write to
stderr (not stdout) to avoid corrupting the MCP JSON-RPC stream. Purveyor does this
by default — do not change LOG_FORMAT or redirect stderr.

Prerequisites:
  pip install google-adk python-dotenv
  cp .env.example .env  # fill in GOOGLE_GENAI_API_KEY and SKYFI_API_KEY

Usage:
  cd agents/google_adk
  # Rename this to agent.py first, then:
  adk web
"""

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

load_dotenv()

# Resolve project root: two directories up from agents/google_adk/
PURVEYOR_PROJECT = os.environ.get(
    "PURVEYOR_PROJECT",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

root_agent = LlmAgent(
    model="gemini-2.0-flash",
    name="satellite_imagery_agent",
    instruction="""You are a satellite imagery assistant powered by SkyFi via Purveyor.
You can help users search satellite image archives, get pricing, place orders,
and monitor deliveries. When placing orders, explain that they'll need to confirm
via a browser link.""",
    tools=[
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="uv",
                    args=["run", "purveyor", "serve", "--stdio"],
                    env={
                        "SKYFI_API_KEY": os.environ.get("SKYFI_API_KEY", ""),
                        "LOCAL_MODE": "true",
                        "PATH": os.environ.get("PATH", ""),
                    },
                    cwd=PURVEYOR_PROJECT,
                ),
            ),
        )
    ],
)
