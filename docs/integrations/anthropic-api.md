# Connecting Purveyor to the Anthropic API

Use Purveyor's satellite imagery tools with Claude models via the Anthropic Python SDK.

## Prerequisites

- Anthropic API key (`ANTHROPIC_API_KEY`)
- Purveyor deployed with a public HTTPS URL or running locally
- SkyFi API key

## Setup

The Anthropic API supports MCP servers via the `mcp_servers` parameter (available in claude-3-5-sonnet and later).

### Basic Example

```python
import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

response = client.beta.messages.create(
    model="claude-opus-4-6",
    max_tokens=4096,
    mcp_servers=[
        {
            "type": "url",
            "url": "https://your-server.com/mcp",
            "name": "purveyor",
            "headers": {
                "X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]
            },
        }
    ],
    messages=[
        {
            "role": "user",
            "content": "Search for recent satellite imagery of the Suez Canal and summarize what's available.",
        }
    ],
    betas=["mcp-client-2025-04-04"],
)

for block in response.content:
    if hasattr(block, "text"):
        print(block.text)
```

### Streaming Example

```python
import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

with client.beta.messages.stream(
    model="claude-opus-4-6",
    max_tokens=4096,
    mcp_servers=[
        {
            "type": "url",
            "url": "https://your-server.com/mcp",
            "name": "purveyor",
            "headers": {"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
        }
    ],
    messages=[
        {
            "role": "user",
            "content": "What satellite passes are predicted over Austin, TX in the next 7 days?",
        }
    ],
    betas=["mcp-client-2025-04-04"],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

### Purveyor Demo Agent (Built-in)

Purveyor ships with a built-in interactive demo that uses the Anthropic SDK:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export SKYFI_API_KEY=your-skyfi-key

# Interactive chat
uv run purveyor demo

# Pre-built workflows
uv run purveyor demo --workflow research --query "deforestation near Manaus"
uv run purveyor demo --workflow monitor --query "Port of Los Angeles"
uv run purveyor demo --workflow order --query "archive image of Rotterdam"
```

## Troubleshooting

**"mcp_servers parameter not supported"**
- Ensure you're using claude-3-5-sonnet-20241022 or later
- Add `betas=["mcp-client-2025-04-04"]` to your API call

**Tool calls returning errors**
- Check Purveyor logs: `uv run purveyor serve --local --reload` and watch stdout
- Verify your SkyFi API key with: `curl -H "X-Skyfi-Api-Key: your-key" https://app.skyfi.com/platform-api/auth/whoami`

**Local development**
- Use the demo agent: `uv run purveyor demo` — it handles the subprocess transport automatically
