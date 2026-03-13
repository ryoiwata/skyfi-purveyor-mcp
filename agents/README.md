# Purveyor Test Agents

This directory contains test and demo agents for different MCP client frameworks connecting to [Purveyor](../README.md) — the remote MCP server wrapping SkyFi's satellite imagery API.

## Contents

| Directory | Framework | Description |
|-----------|-----------|-------------|
| [`google_adk/`](google_adk/README.md) | Google ADK + Gemini | Conversational satellite imagery agent using `McpToolset` over SSE/HTTP |

## What These Are

These agents are **integration demos**, not part of the Purveyor package. They demonstrate how any MCP-compatible framework can connect to a running Purveyor server and use its tools conversationally.

Purveyor exposes its tools via Streamable HTTP at `/mcp`. Any framework that speaks MCP over HTTP or stdio can connect — the agents here show how to do that with specific frameworks.

## Running Purveyor

Before using any agent, start Purveyor locally:

```bash
# From the project root
uv run purveyor serve --local
# Server runs at http://localhost:8000
```

See the [main README](../README.md) for full setup instructions including `SKYFI_API_KEY` and other environment variables.
