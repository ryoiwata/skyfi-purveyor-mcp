# Connecting Purveyor to LangChain / LangGraph

Integrate Purveyor's satellite imagery tools into LangChain or LangGraph agents.

## Prerequisites

- LangChain and LangGraph installed
- Purveyor deployed or running locally
- SkyFi API key and an LLM API key

## Setup

LangChain supports MCP tools via the `langchain-mcp-adapters` package.

```bash
pip install langchain langchain-anthropic langgraph langchain-mcp-adapters
```

### Basic Agent Example

```python
import asyncio
import os
from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

async def main():
    # Connect to Purveyor
    mcp_client = MultiServerMCPClient(
        {
            "purveyor": {
                "url": "https://your-server.com/mcp",
                "transport": "streamable_http",
                "headers": {"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
            }
        }
    )

    # Get tools from Purveyor
    tools = await mcp_client.get_tools()

    # Create agent with Claude
    llm = ChatAnthropic(model="claude-opus-4-6", api_key=os.environ["ANTHROPIC_API_KEY"])
    agent = create_react_agent(llm, tools)

    # Run the agent
    result = await agent.ainvoke({
        "messages": [
            ("user", "Find recent SAR imagery of the Suez Canal and tell me the price range.")
        ]
    })

    print(result["messages"][-1].content)

asyncio.run(main())
```

### LangGraph Workflow Example

```python
import asyncio
import os
from typing import Annotated, TypedDict
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

async def create_imagery_workflow():
    mcp_client = MultiServerMCPClient(
        {
            "purveyor": {
                "url": "https://your-server.com/mcp",
                "transport": "streamable_http",
                "headers": {"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
            }
        }
    )

    tools = await mcp_client.get_tools()
    llm = ChatAnthropic(model="claude-opus-4-6").bind_tools(tools)

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    async def call_model(state: AgentState) -> dict:
        response = await llm.ainvoke(state["messages"])
        return {"messages": [response]}

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(tools))
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    return workflow.compile()

async def main():
    app = await create_imagery_workflow()
    result = await app.ainvoke({
        "messages": [HumanMessage(content="What is the feasibility for a new satellite capture of Austin, TX next week?")]
    })
    print(result["messages"][-1].content)

asyncio.run(main())
```

### Local Development

```python
# For local Purveyor (no server needed — uses stdio)
mcp_client = MultiServerMCPClient(
    {
        "purveyor": {
            "command": "uv",
            "args": ["run", "purveyor", "serve", "--transport", "stdio", "--local"],
            "transport": "stdio",
            "env": {"SKYFI_API_KEY": os.environ["SKYFI_API_KEY"]},
        }
    }
)
```

## Troubleshooting

**"langchain-mcp-adapters not found"**
- Install: `pip install langchain-mcp-adapters`
- Requires Python 3.11+

**Tool calls not executing**
- Ensure you called `.bind_tools(tools)` on the LLM
- Verify ToolNode is wired correctly in the graph

**Connection timeouts**
- Increase timeout: add `"timeout": 30` to the MCP client config
- Check Purveyor health endpoint
