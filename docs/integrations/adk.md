# Connecting Purveyor to Google Agent Development Kit (ADK)

Integrate Purveyor's satellite imagery tools into Google ADK agents.

## Prerequisites

- Google ADK installed (`pip install google-adk`)
- Purveyor deployed or running locally
- SkyFi API key and Gemini API key

## Setup

```bash
pip install google-adk
```

### Basic ADK Agent with Purveyor

```python
import asyncio
import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

async def main():
    # Connect to Purveyor via MCP
    toolset = MCPToolset(
        connection_params=SseServerParams(
            url="https://your-server.com/mcp",
            headers={"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
        )
    )

    agent = Agent(
        name="satellite_imagery_agent",
        model="gemini-2.0-flash-exp",
        instruction=(
            "You are a satellite imagery assistant with access to SkyFi's platform. "
            "Help users search for imagery, check feasibility, and understand pricing."
        ),
        tools=[toolset],
    )

    response = await agent.run_async(
        "What are the latest high-resolution satellite images available for the Port of Rotterdam?"
    )
    print(response.text)

asyncio.run(main())
```

### Multi-Tool ADK Agent

```python
import asyncio
import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

async def main():
    toolset = MCPToolset(
        connection_params=SseServerParams(
            url="https://your-server.com/mcp",
            headers={"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
        )
    )

    agent = Agent(
        name="purveyor_agent",
        model="gemini-2.0-flash-exp",
        instruction="Help users with satellite imagery: search, price, feasibility, and monitoring.",
        tools=[toolset],
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="purveyor_demo", session_service=session_service)

    session = await session_service.create_session(app_name="purveyor_demo", user_id="user1")

    queries = [
        "Search for SAR imagery of the Suez Canal from the last 30 days.",
        "What would it cost to order a VERY HIGH resolution image of that area?",
        "Set up monitoring to alert me when new imagery is available.",
    ]

    for query in queries:
        response = await runner.run_async(
            user_id="user1",
            session_id=session.id,
            new_message=query,
        )
        print(f"Q: {query}")
        print(f"A: {response.text}\n")

asyncio.run(main())
```

## Troubleshooting

**"MCPToolset connection failed"**
- Verify Purveyor is accessible: `curl https://your-server.com/health`
- Check that the URL ends with `/mcp` (not just the base URL)

**Gemini model not using tools**
- Add explicit instruction: "Use the available tools to search satellite imagery"
- Check tool names with: `[t.name for t in await toolset.get_tools()]`

**"API key not configured" from Purveyor**
- Pass the SkyFi key in headers: `headers={"X-Skyfi-Api-Key": "your-key"}`
- Or use local mode with config.json for single-user deployments
