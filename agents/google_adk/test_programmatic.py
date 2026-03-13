"""
Google ADK agent — Option C: Programmatic test (no adk web required).

Fires 3 test queries against Purveyor and prints the agent's responses.
Useful for smoke testing the MCP connection without a browser UI.

Prerequisites:
  pip install google-adk python-dotenv
  cp .env.example .env  # fill in GOOGLE_GENAI_API_KEY, SKYFI_API_KEY, PURVEYOR_URL
  uv run purveyor serve --local  # Purveyor must be running

Usage:
  cd agents/google_adk
  python test_programmatic.py
"""

import asyncio
import os

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams
from google.genai import types

load_dotenv()

PURVEYOR_URL = os.environ.get("PURVEYOR_URL", "http://localhost:8000")
SKYFI_API_KEY = os.environ.get("SKYFI_API_KEY", "")


async def get_agent() -> tuple[LlmAgent, McpToolset]:
    """Create the agent and return it along with the toolset for cleanup."""
    toolset = McpToolset(
        connection_params=SseConnectionParams(
            url=f"{PURVEYOR_URL}/mcp",
            headers={"X-Skyfi-Api-Key": SKYFI_API_KEY},
        ),
    )
    agent = LlmAgent(
        model="gemini-2.0-flash",
        name="satellite_imagery_agent",
        instruction="You are a satellite imagery assistant. Help users search, "
        "order, and monitor satellite imagery via SkyFi.",
        tools=[toolset],
    )
    return agent, toolset


async def main() -> None:
    """Run test queries and print agent responses."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        state={}, app_name="purveyor_test", user_id="test_user"
    )

    agent, toolset = await get_agent()
    runner = Runner(
        app_name="purveyor_test",
        agent=agent,
        session_service=session_service,
    )

    queries = [
        "Who am I?",
        "Geocode 'Central Park, New York'",
        "Search for recent satellite imagery of Central Park with less than 20% cloud cover",
    ]

    for query in queries:
        print(f"\n{'=' * 60}")
        print(f"Query: {query}")
        print("=" * 60)

        content = types.Content(role="user", parts=[types.Part(text=query)])
        events = runner.run_async(
            session_id=session.id,
            user_id=session.user_id,
            new_message=content,
        )
        async for event in events:
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        print(f"Agent: {part.text}")

    await toolset.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
