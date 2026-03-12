"""Demo agent — interactive CLI agent backed by Claude with stdio MCP transport."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import structlog

log = structlog.get_logger(__name__)

WORKFLOWS: dict[str, str] = {
    "research": (
        "Find recent high-resolution imagery of {query}, check feasibility for a new capture, "
        "compare pricing options, and recommend the best approach."
    ),
    "monitor": (
        "Set up monitoring for {query} and explain what will happen when new imagery is available."
    ),
    "order": (
        "Walk me through ordering an {query}. Start by searching the archive, "
        "show me options, and help me place an order."
    ),
}

WELCOME_MESSAGE = """
╔══════════════════════════════════════════════════════════════╗
║         Purveyor — SkyFi Satellite Imagery Demo Agent        ║
╚══════════════════════════════════════════════════════════════╝

I'm an AI assistant with access to SkyFi's satellite imagery platform.
I can help you:
  • Search the archive catalog (DAY, SAR, multispectral imagery)
  • Check feasibility for new satellite captures
  • Explore pricing by product type and resolution
  • Set up AOI monitoring for new imagery alerts
  • Walk you through the order confirmation flow

Type your question below, or 'quit' to exit.
"""


class DemoAgent:
    """Interactive demo agent using Claude with Purveyor as an MCP server via stdio."""

    def __init__(
        self,
        workflow: str | None = None,
        query: str | None = None,
    ) -> None:
        """Initialize the demo agent.

        Args:
            workflow: Optional pre-built workflow name (research, monitor, order).
            query: Optional query for the workflow.

        Raises:
            SystemExit: If ANTHROPIC_API_KEY is not set.
        """
        self.workflow = workflow
        self.query = query
        self._api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            print(
                "Error: ANTHROPIC_API_KEY environment variable is not set.\n"
                "Set it with: export ANTHROPIC_API_KEY=sk-ant-...",
                file=sys.stderr,
            )
            sys.exit(1)

        self._client: Any = None  # anthropic.AsyncAnthropic
        self._mcp_tools: list[dict[str, Any]] = []
        self._mcp_client: Any = None  # mcp.ClientSession

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        if self.workflow and self.query:
            template = WORKFLOWS.get(self.workflow, "")
            return template.format(query=self.query)
        return (
            "You are a helpful assistant with access to SkyFi's satellite imagery platform "
            "through the Purveyor MCP server. Help users search for imagery, check feasibility, "
            "explore pricing, set up monitoring, and understand the ordering process. "
            "When users want to place an order, guide them through the confirmation flow — "
            "they will need to click a confirmation URL to finalize any purchase."
        )

    def _convert_mcp_tool_to_anthropic(self, tool: Any) -> dict[str, Any]:
        """Convert an MCP tool definition to Anthropic's tool format.

        Args:
            tool: MCP tool definition with name, description, inputSchema.

        Returns:
            Anthropic-format tool dict.
        """
        input_schema: dict[str, Any] = {"type": "object", "properties": {}}
        if hasattr(tool, "inputSchema") and tool.inputSchema is not None:
            input_schema = tool.inputSchema
        return {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": input_schema,
        }

    async def _call_mcp_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Call a Purveyor MCP tool and return the result as a string.

        Args:
            tool_name: Name of the MCP tool to call.
            tool_input: Input parameters for the tool.

        Returns:
            Tool result as a string.
        """
        if self._mcp_client is None:
            return "Error: MCP client not connected"

        try:
            result = await self._mcp_client.call_tool(tool_name, tool_input)
            if result.content:
                parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                return "\n".join(parts) if parts else "Tool returned no output"
            return "Tool returned no output"
        except Exception as e:
            log.error("mcp_tool_error", tool=tool_name, error=str(e))
            return f"Error calling tool {tool_name}: {e}"

    async def _chat_turn(
        self, messages: list[dict[str, Any]], user_input: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """Execute one conversation turn with Claude, handling tool calls.

        Args:
            messages: Conversation history so far.
            user_input: The user's message.

        Returns:
            Tuple of (assistant_text_response, updated_messages).
        """
        messages = [*messages, {"role": "user", "content": user_input}]

        response_text = ""
        while True:
            response = await self._client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=self._build_system_prompt(),
                tools=self._mcp_tools,
                messages=messages,
            )

            # Collect assistant content
            assistant_content: list[Any] = []
            for block in response.content:
                assistant_content.append(block)
                if block.type == "text":
                    response_text += block.text

            messages = [*messages, {"role": "assistant", "content": assistant_content}]

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                # Handle tool calls
                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"\n[Calling tool: {block.name}...]", flush=True)
                        result = await self._call_mcp_tool(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )

                messages = [*messages, {"role": "user", "content": tool_results}]
            else:
                break

        return response_text, messages

    async def run(self) -> None:
        """Run the demo agent — spawn server, connect, and start chat loop."""
        import anthropic
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # Spawn Purveyor server as subprocess with stdio transport
        # Use in-memory SQLite, local mode
        env = os.environ.copy()
        env["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
        env["LOCAL_MODE"] = "true"
        env["LOG_FORMAT"] = "json"  # suppress colored output in subprocess

        server_params = StdioServerParameters(
            command="purveyor",
            args=["serve", "--transport", "stdio", "--local"],
            env=env,
        )

        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    self._mcp_client = session
                    await session.initialize()

                    # Discover tools
                    tools_result = await session.list_tools()
                    self._mcp_tools = [
                        self._convert_mcp_tool_to_anthropic(t) for t in tools_result.tools
                    ]
                    log.info("mcp_tools_discovered", count=len(self._mcp_tools))

                    if self.workflow and self.query:
                        await self._run_workflow()
                    else:
                        await self._run_interactive()
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
        except Exception as e:
            print(f"\nError: {e}", file=sys.stderr)
            raise

    async def _run_interactive(self) -> None:
        """Run the interactive chat loop."""
        print(WELCOME_MESSAGE)
        print(f"Connected to Purveyor with {len(self._mcp_tools)} tools available.\n")

        messages: list[dict[str, Any]] = []

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nGoodbye!")
                break

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            try:
                response, messages = await self._chat_turn(messages, user_input)
                print(f"\nAssistant: {response}\n")
            except Exception as e:
                print(f"\nError: {e}\n", file=sys.stderr)

    async def _run_workflow(self) -> None:
        """Run a pre-built workflow."""
        if not self.workflow or not self.query:
            return

        template = WORKFLOWS.get(self.workflow, "")
        prompt = template.format(query=self.query)

        print(f"\n[Running '{self.workflow}' workflow for: {self.query}]\n")
        print(f"Prompt: {prompt}\n")
        print("─" * 60)

        messages: list[dict[str, Any]] = []
        try:
            response, _ = await self._chat_turn(messages, prompt)
            print(f"\n{response}\n")
        except Exception as e:
            print(f"\nError: {e}\n", file=sys.stderr)


def run_demo(workflow: str | None = None, query: str | None = None) -> None:
    """Entry point for the demo agent.

    Args:
        workflow: Optional workflow name.
        query: Optional workflow query.
    """
    agent = DemoAgent(workflow=workflow, query=query)
    asyncio.run(agent.run())
