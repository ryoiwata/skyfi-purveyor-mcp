# Connecting Purveyor to Claude Code

Use Purveyor's satellite imagery tools directly in your Claude Code sessions.

## Prerequisites

- Claude Code installed (`npm install -g @anthropic-ai/claude-code`)
- Purveyor running locally or deployed remotely
- SkyFi API key

## Setup

### Option A: Remote Server (Streamable HTTP)

```bash
# Add a remote Purveyor deployment
claude mcp add purveyor --transport http https://your-server.com/mcp

# Or with authentication header
claude mcp add purveyor --transport http https://your-server.com/mcp \
  --header "X-Skyfi-Api-Key: your-skyfi-api-key"
```

### Option B: Local Server (stdio)

```bash
# Install Purveyor locally first
git clone https://github.com/your-org/skyfi-purveyor-mcp
cd skyfi-purveyor-mcp
uv sync

# Configure your API key
echo '{"skyfi_api_key": "your-skyfi-api-key"}' > config.json

# Add as stdio MCP server
claude mcp add purveyor -- uv run purveyor serve --transport stdio --local
```

### Verify

```bash
claude mcp list
# Should show: purveyor  stdio/http  connected
```

## Example Session

```
$ claude
> Search for recent SAR imagery of the Suez Canal

Using search_archives...
Found 12 SAR archives near Suez Canal. Date range: 2026-01-15 to 2026-03-01.
Providers: UMBRA (4), ICEYE_US (8). Price range: $180–$650/scene.
Best resolution: VERY HIGH (0.5m) from UMBRA, captured 2026-02-14.
```

## Troubleshooting

**"Server not found" after `claude mcp add`**
- For stdio: verify `uv run purveyor serve --transport stdio --local` works in your terminal first
- For HTTP: test with `curl http://localhost:8000/health`

**"Tool not found" errors**
- Run `claude mcp list` to confirm Purveyor shows as connected
- Restart Claude Code: `claude restart`

**API key errors in local mode**
- Create `config.json` in your working directory: `{"skyfi_api_key": "your-key"}`
- Or set the environment variable: `export SKYFI_API_KEY=your-key`
