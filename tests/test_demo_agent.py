"""Tests for the demo agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.demo.agent import WORKFLOWS, DemoAgent


def test_workflows_defined() -> None:
    """All three workflow types are defined."""
    assert "research" in WORKFLOWS
    assert "monitor" in WORKFLOWS
    assert "order" in WORKFLOWS


def test_workflow_templates_use_query() -> None:
    """Workflow templates contain {query} placeholder."""
    for name, template in WORKFLOWS.items():
        assert "{query}" in template, f"Workflow '{name}' missing {{query}} placeholder"


def test_demo_agent_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """DemoAgent raises SystemExit when ANTHROPIC_API_KEY is not set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        DemoAgent()


def test_demo_agent_initializes_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """DemoAgent initializes successfully when ANTHROPIC_API_KEY is set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent()
    assert agent._api_key == "sk-ant-test-key"
    assert agent.workflow is None
    assert agent.query is None


def test_demo_agent_workflow_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow system prompts are generated correctly."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent(workflow="research", query="the Suez Canal")
    prompt = agent._build_system_prompt()
    assert "the Suez Canal" in prompt
    assert "imagery" in prompt.lower()


def test_demo_agent_monitor_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monitor workflow prompt contains query."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent(workflow="monitor", query="Port of Los Angeles")
    prompt = agent._build_system_prompt()
    assert "Port of Los Angeles" in prompt
    assert "monitoring" in prompt.lower()


def test_demo_agent_order_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order workflow prompt contains query."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent(workflow="order", query="archive image of Austin TX")
    prompt = agent._build_system_prompt()
    assert "archive image of Austin TX" in prompt


def test_demo_agent_default_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default system prompt is used when no workflow is specified."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent()
    prompt = agent._build_system_prompt()
    assert "SkyFi" in prompt
    assert "satellite" in prompt.lower()


def test_convert_mcp_tool_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP tool definition is correctly converted to Anthropic format."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent()

    mock_tool = MagicMock()
    mock_tool.name = "search_archives"
    mock_tool.description = "Search satellite imagery archives"
    mock_tool.inputSchema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    }

    result = agent._convert_mcp_tool_to_anthropic(mock_tool)
    assert result["name"] == "search_archives"
    assert result["description"] == "Search satellite imagery archives"
    assert result["input_schema"]["type"] == "object"
    assert "location" in result["input_schema"]["properties"]


@pytest.mark.asyncio
async def test_call_mcp_tool_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns error message when MCP client is not connected."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent()
    agent._mcp_client = None

    result = await agent._call_mcp_tool("search_archives", {"location": "Austin TX"})
    assert "Error" in result
    assert "not connected" in result


@pytest.mark.asyncio
async def test_call_mcp_tool_with_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool call is forwarded to MCP client and result is returned."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    agent = DemoAgent()

    mock_content = MagicMock()
    mock_content.text = "Found 5 archives near Austin TX."
    mock_result = MagicMock()
    mock_result.content = [mock_content]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    agent._mcp_client = mock_session

    result = await agent._call_mcp_tool("search_archives", {"location": "Austin TX"})
    assert "Found 5 archives" in result
    mock_session.call_tool.assert_called_once_with("search_archives", {"location": "Austin TX"})
