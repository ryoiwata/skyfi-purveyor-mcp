# Purveyor — SkyFi MCP Server

> A Model Context Protocol (MCP) server that lets AI agents conversationally search, order, and monitor satellite imagery through [SkyFi's Earth Intelligence Platform](https://skyfi.com).

Purveyor gives any MCP-compatible AI agent — Claude, ChatGPT, Gemini, or your own — the ability to browse satellite archives, check imaging feasibility, explore pricing, place orders with human-in-the-loop confirmation, and set up area-of-interest monitoring. All through natural conversation.

## Why Purveyor?

As AI agents take on more autonomous workflows, they need standardized ways to interact with commercial services. Purveyor bridges the gap between conversational AI and SkyFi's satellite imagery marketplace, letting agents act as intelligent procurement assistants for earth observation data.

- **Conversational ordering** — Search archives, compare pricing, check feasibility, and place orders through natural language
- **Human-in-the-loop** — Orders require explicit human confirmation via out-of-band checkout before any money is spent
- **Framework-agnostic** — Works with Claude Web, OpenAI, Gemini, LangChain, ADK, AI SDK, and any MCP-compatible client
- **Self-hostable** — Run locally with SQLite or deploy to the cloud with Postgres. Your choice of complexity
- **Geospatial-native** — Built-in OpenStreetMap integration for resolving place names to coordinates

## Features

### MCP Tools

| Tool | Description |
|------|-------------|
| `search_archives` | Browse SkyFi's satellite imagery catalog with filters (AOI, date range, resolution, cloud cover, product type) |
| `get_archive_details` | Get full metadata for a specific archive image |
| `get_pricing` | Explore pricing options for tasking orders by product type, resolution, and provider |
| `check_feasibility` | Run feasibility checks for a tasking request — returns scores, weather, and provider availability |
| `get_pass_predictions` | Find upcoming satellite passes over an area of interest |
| `create_tasking_order` | Place a new tasking order (returns confirmation URL for human approval) |
| `create_archive_order` | Order an existing archive image (returns confirmation URL for human approval) |
| `get_order_status` | Check order status, history, and delivery events |
| `list_orders` | Browse previous orders with filtering and pagination |
| `download_deliverable` | Get download URLs for ordered imagery (image, payload, COG) |
| `request_redelivery` | Reschedule delivery to a different storage bucket |
| `setup_monitoring` | Create AOI monitoring notifications with webhook delivery |
| `list_notifications` | View active monitoring configurations |
| `get_notification_history` | See notification event history for a monitor |
| `delete_notification` | Remove an active monitor |
| `geocode_location` | Resolve a place name to coordinates via OpenStreetMap |
| `create_aoi_from_point` | Generate an AOI polygon from a center point and area size |
| `calculate_aoi_area` | Compute the area of a WKT polygon in square kilometers |
| `whoami` | Get current user info, budget, and account status |

### MCP Resources

| Resource | Description |
|----------|-------------|
| `skyfi://pricing/current` | Current pricing matrix for all product types and resolutions |
| `skyfi://orders/recent` | Most recent orders for the authenticated user |
| `skyfi://account/info` | Account details, budget usage, and payment status |

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management
- A SkyFi account and API key ([get one here](https://app.skyfi.com))

### Local Mode (Single User)

```bash
# Clone and install
git clone https://github.com/ryoiwata/skyfi-purveyor-mcp.git
cd skyfi-purveyor-mcp
uv sync

# Configure credentials
cp config.example.json config.json
# Edit config.json with your SkyFi API key

# Run the server
uv run purveyor serve --local
```

The server starts on `http://localhost:8000` using SQLite for local storage. No Postgres or Redis required.

### Connect to Claude Web

1. Go to Claude Settings → Integrations → Add Custom MCP
2. Enter the server URL: `http://localhost:8000/mcp`
3. Start chatting: *"Search for recent high-resolution satellite images of the Port of Los Angeles"*

### Connect to Claude Code

```bash
claude mcp add purveyor http://localhost:8000/mcp
```

### Docker (Self-Hosted)

```bash
# Minimal — app + Postgres only
docker compose --profile minimal up -d

# Standard — adds Redis + Caddy for HTTPS
docker compose --profile standard up -d

# Full — adds Grafana observability stack
docker compose --profile full up -d
```

### Cloud Deployment

```bash
# AWS Fargate
cd deploy/terraform/aws
terraform init && terraform apply

# Google Cloud Run
cd deploy/terraform/gcp
terraform init && terraform apply
```

## Architecture

```
┌──────────────────────┐     ┌─────────────────────┐
│   MCP Client         │     │   SkyFi Platform    │
│  (Claude, GPT, etc.) │────▶│   API               │
│                      │     │  app.skyfi.com      │
└──────────┬───────────┘     └──────────▲──────────┘
           │                            │
           │ Streamable HTTP            │ httpx
           │ (JSON-RPC over SSE)        │ + tenacity
           │                            │
┌──────────▼───────────────────────────┐│
│        Purveyor MCP Server      ││
│  ┌─────────┐ ┌──────────┐ ┌───────┐ ││
│  │  Tools  │ │Resources │ │Prompts│ ││
│  └────┬────┘ └────┬─────┘ └───┬───┘ ││
│       │           │           │      ││
│  ┌────▼───────────▼───────────▼────┐ ││
│  │        Core Services            │─┘│
│  │  SkyFi Client · Cache · Auth   │  │
│  └────────────┬───────────────────┘  │
│               │                      │
│  ┌────────────▼───────────────────┐  │
│  │     Storage (pluggable)        │  │
│  │  SQLite (local) │ Postgres     │  │
│  └────────────────────────────────┘  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │   Webhook Receiver (FastAPI)   │  │
│  │  Order events · AOI monitors   │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SKYFI_API_KEY` | Yes (cloud mode) | — | SkyFi Platform API key |
| `DATABASE_URL` | No | `sqlite:///purveyor.db` | Database connection string |
| `REDIS_URL` | No | — | Redis URL (enables Redis caching/rate limiting) |
| `SERVER_HOST` | No | `0.0.0.0` | Server bind address |
| `SERVER_PORT` | No | `8000` | Server bind port |
| `LOG_LEVEL` | No | `info` | Logging level |
| `LOG_FORMAT` | No | `json` | `json` for production, `console` for dev |
| `SENTRY_DSN` | No | — | Sentry DSN for error tracking |
| `CACHE_BACKEND` | No | `memory` | `memory` or `redis` |

### Local Config File

For local single-user mode, credentials are stored in `config.json`:

```json
{
  "skyfi_api_key": "your-api-key-here",
  "database_url": "sqlite:///purveyor.db",
  "server": {
    "host": "localhost",
    "port": 8000
  }
}
```

### Cloud Multi-User Mode

In cloud deployment, each MCP client sends credentials in the request headers:

```
X-Skyfi-Api-Key: <user's API key>
```

The server is stateless — no user credentials are stored server-side.

## Integration Guides

Purveyor works with any MCP-compatible client. See the full documentation for setup instructions:

- [Claude Web (Remote MCP)](docs/integrations/claude-web.md)
- [Claude Code](docs/integrations/claude-code.md)
- [OpenAI (Remote MCP)](docs/integrations/openai.md)
- [Anthropic API](docs/integrations/anthropic-api.md)
- [Google Gemini](docs/integrations/gemini.md)
- [LangChain / LangGraph](docs/integrations/langchain.md)
- [Google ADK](docs/integrations/adk.md)
- [Vercel AI SDK](docs/integrations/ai-sdk.md)

## Demo Agent

A reference agent implementation is included for testing and demonstration:

```bash
# Interactive CLI agent using Claude
uv run purveyor demo --provider anthropic

# Run the demo research workflow
uv run purveyor demo --workflow research \
  --query "Monitor deforestation in the Amazon basin near Manaus"
```

See [docs/demo-agent.md](docs/demo-agent.md) for details.

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Type checking
uv run mypy src/

# Lint
uv run ruff check src/

# Run locally with hot reload
uv run purveyor serve --local --reload
```

## Project Structure

```
skyfi-purveyor-mcp/
├── src/purveyor/
│   ├── __init__.py
│   ├── server.py              # MCP server setup and transport
│   ├── tools/                 # MCP tool implementations
│   │   ├── archives.py        # search, get details
│   │   ├── orders.py          # create, list, status, download
│   │   ├── pricing.py         # pricing exploration
│   │   ├── feasibility.py     # feasibility checks, pass prediction
│   │   ├── notifications.py   # AOI monitoring
│   │   └── geospatial.py      # OSM, AOI helpers
│   ├── resources/             # MCP resource implementations
│   ├── core/
│   │   ├── skyfi_client.py    # SkyFi API wrapper
│   │   ├── cache.py           # Tiered caching (memory / Redis)
│   │   ├── auth.py            # Auth provider interface
│   │   ├── rate_limiter.py    # Inbound/outbound rate limiting
│   │   └── config.py          # Configuration management
│   ├── models/                # SQLAlchemy models
│   ├── webhooks/              # FastAPI webhook receiver
│   └── cli.py                 # CLI entry point
├── tests/
├── docs/
│   └── integrations/
├── deploy/
│   ├── docker/
│   ├── terraform/
│   └── docker-compose.yml
├── alembic/
├── config.example.json
├── pyproject.toml
└── README.md
```

## License

[MIT](LICENSE)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Links

- [SkyFi Platform](https://skyfi.com)
- [SkyFi API Documentation](https://app.skyfi.com/platform-api/redoc)
- [MCP Specification](https://modelcontextprotocol.io)
- [Streamable HTTP Transport](https://blog.christianposta.com/ai/understanding-mcp-recent-change-around-http-sse/)
