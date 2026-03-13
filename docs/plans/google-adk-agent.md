# Plan: Google ADK Test Agent

**Status:** Implemented
**Date:** 2026-03-13
**Branch:** feat/tier2-auth-user-urls

## Goal

Create a test/demo agent in `agents/google_adk/` that connects to the Purveyor MCP server
via Google ADK (Agent Development Kit) and lets users conversationally search, order, and
monitor SkyFi satellite imagery through Gemini.

This is a **demo/integration layer** — it does not modify Purveyor source code. It demonstrates
how any MCP-compatible framework can connect to Purveyor.

## Files to Create

```
agents/
├── README.md                          # Agents directory overview
└── google_adk/
    ├── __init__.py                    # Package init, imports agent
    ├── agent.py                       # Option A: SSE/HTTP agent (primary)
    ├── agent_stdio.py                 # Option B: Stdio agent (alternative)
    ├── test_programmatic.py           # Option C: No-adk-web test script
    ├── .env.example                   # Env var template
    └── README.md                      # Full setup + usage guide
```

## Three Connection Options

### Option A: SSE/HTTP (Primary)
- Connects to a running Purveyor HTTP server via `SseConnectionParams`
- URL: `{PURVEYOR_URL}/mcp` with `X-Skyfi-Api-Key` header
- Run with `adk web` — full dev UI with conversation history
- **Recommended** for development and demos

### Option B: Stdio (Alternative)
- Spawns Purveyor as a subprocess via `StdioConnectionParams`
- Command: `uv run purveyor serve --stdio` in the project root
- Confirmation URLs still need HTTP server running with same Fernet key
- structlog must write to stderr in stdio mode (already Purveyor default)

### Option C: Programmatic (No adk web)
- Standalone `asyncio` script, no browser UI needed
- Creates `InMemorySessionService`, fires 3 test queries, prints responses
- Useful for CI/quick smoke testing the MCP connection

## Key Implementation Details

### Agent Instruction
The agent instruction covers:
- Search archives by location, date, resolution, cloud cover
- Get pricing before ordering
- Check tasking feasibility
- Place orders (directing users to confirm via browser link)
- Monitor orders and download deliverables
- Geocode locations and create AOIs

### Connection Parameters
```python
# Option A
SseConnectionParams(
    url=f"{PURVEYOR_URL}/mcp",
    headers={"X-Skyfi-Api-Key": SKYFI_API_KEY},
)

# Option B
StdioConnectionParams(
    server_params=StdioServerParameters(
        command="uv",
        args=["run", "purveyor", "serve", "--stdio"],
        env={"SKYFI_API_KEY": ..., "LOCAL_MODE": "true", "PATH": ...},
        cwd=PURVEYOR_PROJECT,
    )
)
```

### PURVEYOR_PROJECT Resolution (agent_stdio.py)
Defaults to two parent directories up from the file's location:
```python
PURVEYOR_PROJECT = os.environ.get(
    "PURVEYOR_PROJECT",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
```
This resolves to the project root regardless of where adk web is invoked from.

### .gitignore Update
Add `agents/**/.env` to `.gitignore` to prevent committing secrets in agent env files.

## Decisions

- **SSE not Streamable HTTP**: `SseConnectionParams` is the current google-adk API for HTTP
  MCP connections. The Purveyor `/mcp` endpoint supports both SSE and Streamable HTTP — ADK's
  SSE client should negotiate correctly. If ADK adds `StreamableHTTPConnectionParams` in a
  future version, the README notes how to update.
- **No tool_filter by default**: All tools exposed. The README documents how to add filtering
  for production use cases.
- **Gemini model**: `gemini-2.0-flash` — fast, capable, and the standard choice per the ADK
  integration guide examples.
- **Async test script**: The programmatic test follows the exact pattern from
  `docs/mcp/google-adk-mcp-tools.md` section "Using MCP Tools in your own Agent out of adk web".

## Dependencies

ADK is NOT added to Purveyor's `pyproject.toml`. It's a separate install for agent developers:
```bash
pip install google-adk python-dotenv
```

## What Was Decided Against

- **Adding google-adk to pyproject.toml**: Purveyor is an MCP server, not an ADK project.
  Bundling ADK would add significant dependency weight and couple the server to a specific
  client framework. The `agents/` folder is intentionally decoupled.
- **Modifying Purveyor source**: The integration uses the existing `/mcp` endpoint as-is.
  No changes to server.py, transport, or auth handling were needed.
