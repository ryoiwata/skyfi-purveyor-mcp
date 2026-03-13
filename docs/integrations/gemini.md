# Connecting Purveyor to Google Gemini

Use Purveyor's satellite imagery tools with Gemini models via the Google AI Python SDK.

## Prerequisites

- Google AI API key or Vertex AI credentials
- Purveyor deployed with a public HTTPS URL
- SkyFi API key

## Setup

Gemini supports MCP servers as external tool providers through the `tools` parameter with MCP server definitions.

### Python Example (Google AI SDK)

```python
import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash-exp",
    tools=[
        genai.Tool.from_mcp_server(
            url="https://your-server.com/mcp",
            headers={"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
        )
    ],
)

chat = model.start_chat(enable_automatic_function_calling=True)
response = chat.send_message(
    "Search for recent high-resolution satellite imagery of the Port of Singapore."
)
print(response.text)
```

### Vertex AI Example

```python
import os
import vertexai
from vertexai.preview.generative_models import GenerativeModel, Tool

vertexai.init(project=os.environ["GCP_PROJECT"], location="us-central1")

model = GenerativeModel(
    "gemini-2.0-flash-exp",
    tools=[
        Tool.from_mcp_server(
            url="https://your-server.com/mcp",
            headers={"X-Skyfi-Api-Key": os.environ["SKYFI_API_KEY"]},
        )
    ],
)

response = model.generate_content(
    "What satellite providers are available and what are their pricing tiers?"
)
print(response.text)
```

## Troubleshooting

**"Tool not found" errors**
- Verify `from_mcp_server` is available in your SDK version (requires google-generativeai >= 0.8.0)
- Test Purveyor health: `curl https://your-server.com/health`

**Slow tool responses**
- First request may be slow due to MCP initialization. Subsequent requests will be faster due to caching.
- Archive searches and feasibility checks depend on SkyFi's API response time.

**Authentication errors**
- Check SkyFi API key is valid: `curl -H "X-Skyfi-Api-Key: your-key" https://app.skyfi.com/platform-api/auth/whoami`
