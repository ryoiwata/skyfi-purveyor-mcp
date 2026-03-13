# Connecting Purveyor to Claude.ai (Web)

Connect Purveyor to the Claude.ai web interface to use satellite imagery tools directly in your conversations.

## Prerequisites

- A deployed Purveyor server with a public HTTPS URL
- A SkyFi API key from [app.skyfi.com](https://app.skyfi.com)
- Claude Pro or higher plan (remote MCP requires a paid plan)

## Setup

### Step 1: Deploy Purveyor

Deploy Purveyor to a cloud provider or use ngrok for local testing:

```bash
# Local with ngrok
uv run purveyor serve --local &
ngrok http 8000
# Note the ngrok URL, e.g. https://abc123.ngrok.io
```

For production, see the [AWS](../deploy/terraform/aws/) or [GCP](../deploy/terraform/gcp/) Terraform modules.

### Step 2: Add Purveyor to Claude.ai

1. Open [claude.ai](https://claude.ai) and sign in
2. Click on your profile picture → **Settings**
3. Navigate to **Integrations**
4. Click **Add Custom Integration** (or **Add MCP Server**)
5. Fill in the details:
   - **Name**: `Purveyor`
   - **URL**: `https://your-server.com/mcp`
   - **API Key Header**: `X-Skyfi-Api-Key: your-skyfi-api-key`
6. Click **Save**

### Step 3: Verify the Connection

Start a new conversation and try:

> "Can you search for satellite imagery of the Port of Rotterdam from the last 30 days?"

Claude should use the `search_archives` tool and return imagery results.

## Example Conversations

### Archive Search

> **You**: Find me recent high-resolution satellite imagery of the Port of Los Angeles.
>
> **Claude**: I'll search for recent high-resolution imagery of the Port of Los Angeles... [uses `geocode_location` then `search_archives`]
> Found 8 archives. Best match: PLANET VERY HIGH (0.5m) captured 2026-02-28, $245/scene. 3 are open data (free Sentinel-2).

### Pricing Exploration

> **You**: What would it cost to order a VERY HIGH resolution day image of a 50 sq km area?
>
> **Claude**: [uses `get_pricing`] For a VERY HIGH resolution DAY image: PLANET charges approximately $8.50/sq km → $425 for 50 sq km.

### Order Placement

> **You**: Order the best archive image from those results.
>
> **Claude**: I'll prepare the order for you. [uses `create_archive_order`] Here's your order summary: Archive ID abc-123, PLANET VERY HIGH, $245. Please review and confirm at: https://your-server.com/confirm/...
> **Important**: Click the link above to complete your purchase.

## Troubleshooting

**"Connection failed" when adding the integration**
- Verify the URL is accessible from the internet (test with `curl https://your-server.com/health`)
- Check the server is running: the `/health` endpoint should return `{"status": "healthy"}`
- Ensure you're using HTTPS, not HTTP

**"Authentication failed" errors**
- Verify your SkyFi API key is correct at [app.skyfi.com/settings](https://app.skyfi.com/settings)
- Check the API key header name is exactly `X-Skyfi-Api-Key` (case-sensitive)

**Tools not appearing in conversations**
- Claude only shows tools when they're relevant. Try explicitly asking: "What SkyFi tools do you have available?"
- Re-save the integration in Settings to refresh the tool list

**Order confirmation URL not working**
- The confirmation URL must be publicly reachable. Set `CONFIRMATION_BASE_URL=https://your-server.com` in your deployment environment.
- Confirmation links expire after 30 minutes.
