# Connecting Purveyor to OpenAI

Use Purveyor's satellite imagery tools with OpenAI's GPT models via remote MCP support.

## Prerequisites

- OpenAI API key with access to gpt-4o or gpt-4o-mini
- Purveyor deployed with a public HTTPS URL
- SkyFi API key

## Setup

OpenAI supports MCP servers as remote tool providers in the Responses API.

### Python Example

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

response = client.responses.create(
    model="gpt-4o",
    tools=[
        {
            "type": "mcp",
            "server_label": "purveyor",
            "server_url": "https://your-server.com/mcp",
            "headers": {
                "X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]
            },
        }
    ],
    input="Find recent high-resolution imagery of the Port of Rotterdam.",
)

print(response.output_text)
```

### Multi-Turn Conversation

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

mcp_tool = {
    "type": "mcp",
    "server_label": "purveyor",
    "server_url": "https://your-server.com/mcp",
    "headers": {"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
}

# Step 1: Search
resp1 = client.responses.create(
    model="gpt-4o",
    tools=[mcp_tool],
    input="Search for SAR imagery of Manaus, Brazil from the last 60 days.",
)
print("Search results:", resp1.output_text)

# Step 2: Check pricing
resp2 = client.responses.create(
    model="gpt-4o",
    tools=[mcp_tool],
    previous_response_id=resp1.id,
    input="What would a VERY HIGH resolution tasking order cost for a 100 sq km area there?",
)
print("Pricing:", resp2.output_text)
```

## Troubleshooting

**"Connection refused" errors**
- Ensure Purveyor is running and publicly accessible
- Test: `curl https://your-server.com/health`

**MCP tool calls not happening**
- Verify the `server_url` is correct and includes `/mcp` path
- Check that `X-Skyfi-Api-Key` header is being passed

**Rate limit errors**
- Purveyor's default rate limit is 60 reads/min per API key. Add delays between requests if needed.
