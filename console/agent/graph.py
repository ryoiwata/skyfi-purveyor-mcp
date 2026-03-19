from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from system_prompt import SYSTEM_PROMPT


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_aoi: str | None
    active_confirmation: dict | None


def should_continue(state: AgentState) -> str:
    """Route to tools if last message has tool calls, else end."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END


def build_graph(tools: list):
    """Build and compile a LangGraph agent with the given tools."""
    model = ChatOpenAI(model="gpt-4o", streaming=True, temperature=0)
    model_with_tools = model.bind_tools(tools)

    async def call_model(state: AgentState) -> dict:
        """Agent node: call OpenAI with tools bound."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(state["messages"])
        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", tool_node)
    builder.set_entry_point("agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")

    return builder.compile()
