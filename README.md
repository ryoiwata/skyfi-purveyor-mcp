# Purveyor

**Give any AI agent the power to search, order, and monitor satellite imagery through conversation.**

[![CI](https://github.com/your-org/skyfi-purveyor-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/skyfi-purveyor-mcp/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Coverage: 81%+](https://img.shields.io/badge/coverage-81%25-brightgreen)](https://github.com/your-org/skyfi-purveyor-mcp/actions)

Purveyor is a remote **Model Context Protocol (MCP) server** that wraps [SkyFi's Platform API](https://app.skyfi.com), enabling AI agents to conversationally search, order, and monitor satellite imagery — with human-in-the-loop confirmation for any purchase.

Works with **Claude Web, OpenAI, Gemini, LangChain, Google ADK, Vercel AI SDK**, and any MCP-compatible client.

---

## Quick Start

### Local Mode (5 minutes, no external dependencies)

```bash
# 1. Clone and install
git clone https://github.com/your-org/skyfi-purveyor-mcp
cd skyfi-purveyor-mcp
uv sync

# 2. Configure your SkyFi API key
echo '{"skyfi_api_key": "your-key-here"}' > config.json

# 3. Start the server
uv run purveyor serve --local
# → Server running at http://localhost:8000/mcp
```

Connect any MCP client to `http://localhost:8000/mcp` — or try the built-in demo agent:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run purveyor demo
```

### Docker

```bash
docker compose --profile minimal up -d
# → Purveyor + Postgres at http://localhost:8000/mcp
```

---

## Demo Agent

Purveyor includes an interactive CLI agent powered by Claude:

```bash
# Interactive chat
uv run purveyor demo

# Pre-built workflows
uv run purveyor demo --workflow research --query "deforestation near Manaus"
uv run purveyor demo --workflow monitor  --query "Port of Los Angeles"
uv run purveyor demo --workflow order    --query "archive image of Rotterdam"
```

The demo uses stdio transport — no server needed, no ports, self-contained.

---

## Architecture

```
┌─────────────────┐        ┌──────────────────────┐        ┌─────────────────┐
│   MCP Clients   │───────▶│   Purveyor            │───────▶│  SkyFi Platform │
│                 │  MCP   │   MCP Server          │ HTTPS  │  API            │
│ Claude Web      │ Stream │                       │        │                 │
│ OpenAI          │ HTTP   │ 20 Tools · 5 Resources│        │ /archives       │
│ Gemini          │        │ Cache · Auth          │        │ /orders         │
│ LangChain       │        │ Rate Limiting         │        │ /pricing        │
│ Custom agents   │        │ Webhooks              │        │ /feasibility    │
└─────────────────┘        └──────────┬────────────┘        │ /notifications  │
                                      │                      └─────────────────┘
                           ┌──────────▼────────────┐
                           │   Data Layer          │
                           │ SQLite (local)        │
                           │ Postgres+PostGIS       │
                           │ Redis (optional)      │
                           └───────────────────────┘
```

**Transport:** Streamable HTTP (single `/mcp` endpoint). Client sends JSON-RPC via POST; server responds with standard HTTP or SSE stream for notifications.

**Order flow:** Orders are never placed automatically. The agent returns a confirmation URL → user reviews price and confirms → order is placed via SkyFi API. API keys are Fernet-encrypted into the URL token, never stored in the database.

---

## MCP Tools (20 total)

### Archive Search
| Tool | Description |
|------|-------------|
| `search_archives` | Search satellite catalog by location, date, resolution, provider, and cloud cover |
| `get_archive_details` | Get full metadata for a specific archive image |

### Pricing
| Tool | Description |
|------|-------------|
| `get_pricing` | Full pricing matrix for all product/resolution/provider combinations |

### Feasibility & Pass Prediction
| Tool | Description |
|------|-------------|
| `check_feasibility` | Check if a satellite capture is feasible for an AOI and date range |
| `get_pass_predictions` | List upcoming satellite passes over an area |

### Orders
| Tool | Description |
|------|-------------|
| `create_tasking_order` | Initiate a new satellite capture (requires human confirmation) |
| `create_archive_order` | Order an existing archive image (requires human confirmation) |
| `list_orders` | List previous orders with filtering and pagination |
| `get_order_status` | Get order details and status history |
| `download_deliverable` | Get signed download URL for completed orders |
| `request_redelivery` | Redeliver imagery to a different storage bucket |
| `cancel_pending_order` | Cancel a pending order before confirmation |

### Monitoring
| Tool | Description |
|------|-------------|
| `setup_monitoring` | Create an AOI monitor — alerts when new imagery is ingested |
| `list_notifications` | List active AOI monitors |
| `get_notification_history` | View event history for a monitor |
| `delete_notification` | Remove an AOI monitor |

### Geospatial
| Tool | Description |
|------|-------------|
| `geocode_location` | Resolve place names to coordinates and AOI polygons |
| `create_aoi_from_point` | Generate a WKT polygon from a center point and area |
| `calculate_aoi_area` | Calculate area in sq km and validate a WKT polygon |

### Account
| Tool | Description |
|------|-------------|
| `whoami` | Account info, budget usage, and payment status |

### MCP Resources (5 total)
- `skyfi://pricing/current` — Full pricing matrix (cached 5 min)
- `skyfi://orders/recent` — Last 10 orders
- `skyfi://account/info` — Account details and budget
- `skyfi://providers/list` — Available satellite providers
- `skyfi://resolutions/list` — Supported resolution tiers

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SKYFI_API_KEY` | Yes (cloud) | — | SkyFi Platform API key |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///purveyor.db` | Database connection |
| `REDIS_URL` | No | — | Enables Redis caching/rate limiting |
| `CONFIRMATION_SECRET_KEY` | Yes (cloud) | Auto-generated (local) | Fernet key for token encryption |
| `CONFIRMATION_BASE_URL` | No | Auto-detected | Base URL for confirmation pages |
| `SERVER_HOST` | No | `0.0.0.0` | Bind address |
| `SERVER_PORT` | No | `8000` | Bind port |
| `LOG_LEVEL` | No | `info` | Logging level (`debug`, `info`, `warning`, `error`) |
| `LOG_FORMAT` | No | `json` | `json` (production) or `console` (dev) |
| `SENTRY_DSN` | No | — | Sentry error tracking DSN |
| `CACHE_BACKEND` | No | `memory` | `memory` or `redis` |
| `ALLOWED_ORIGINS` | No | `*` | CORS allowed origins (comma-separated) |
| `GEOCODING_BASE_URL` | No | Nominatim public | Override for self-hosted geocoding |

Generate a `CONFIRMATION_SECRET_KEY`:
```bash
uv run purveyor generate-key
```

---

## Deployment

### Local Development

```bash
uv run purveyor serve --local --reload
```

### Docker Compose

```bash
# App + Postgres only
docker compose --profile minimal up -d

# + Redis + Caddy (HTTPS)
docker compose --profile standard up -d

# + Grafana + Prometheus + Tempo
docker compose --profile full up -d
```

### Cloud

See the Terraform modules:
- **AWS Fargate**: [`deploy/terraform/aws/`](deploy/terraform/aws/) — ECS + RDS + ALB
- **GCP Cloud Run**: [`deploy/terraform/gcp/`](deploy/terraform/gcp/) — Cloud Run + Cloud SQL

---

## Integration Guides

Connect Purveyor to your AI platform:

- [Claude Web](docs/integrations/claude-web.md)
- [Claude Code](docs/integrations/claude-code.md)
- [OpenAI](docs/integrations/openai.md)
- [Anthropic API](docs/integrations/anthropic-api.md)
- [Google Gemini](docs/integrations/gemini.md)
- [LangChain / LangGraph](docs/integrations/langchain.md)
- [Google ADK](docs/integrations/adk.md)
- [Vercel AI SDK](docs/integrations/ai-sdk.md)

---

## Development

```bash
# Install
git clone https://github.com/your-org/skyfi-purveyor-mcp
cd skyfi-purveyor-mcp
uv sync

# Test
uv run pytest -m "not live"           # All tests (no API key needed)
uv run pytest -m live                 # Live SkyFi API tests (needs SKYFI_TEST_API_KEY)
uv run pytest --cov=src/purveyor      # With coverage

# Lint & type check
uv run ruff check src/ tests/
uv run mypy src/

# Database migrations
uv run alembic upgrade head
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

## License

MIT — see [LICENSE](LICENSE)
