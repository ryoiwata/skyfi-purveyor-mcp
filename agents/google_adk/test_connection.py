"""Quick connection test for Purveyor MCP server.

Verifies the MCP handshake and lists available tools.
Does NOT require GOOGLE_API_KEY — just SKYFI_API_KEY.

Usage:
  cd agents/google_adk
  python test_connection.py
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

PURVEYOR_URL = os.environ.get(
    "PURVEYOR_URL", "http://purveyor-691022321.us-east-1.elb.amazonaws.com"
)
SKYFI_API_KEY = os.environ.get("SKYFI_API_KEY", "")


async def main() -> None:
    """Connect to Purveyor, list tools, and confirm the integration works."""
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    print(f"Connecting to {PURVEYOR_URL}/mcp ...")

    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=f"{PURVEYOR_URL}/mcp",
            headers={"X-Skyfi-Api-Key": SKYFI_API_KEY},
        ),
    )

    tools = await toolset.get_tools()
    print(f"\n✅ Connected! Found {len(tools)} tools:\n")
    for tool in sorted(tools, key=lambda t: t.name):
        description = (tool.description or "")[:80]
        print(f"  {tool.name}: {description}...")

    await toolset.close()
    print("\nPurveyor MCP is working. Add McpToolset to your agent's tools list to get started.")


if __name__ == "__main__":
    asyncio.run(main())
