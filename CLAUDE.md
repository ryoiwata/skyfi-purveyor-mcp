# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Purveyor (skyfi-purveyor-mcp) is a remote Model Context Protocol (MCP) server that wraps SkyFi's Platform API, enabling AI agents to conversationally search, order, and monitor satellite imagery. Users interact through any MCP-compatible client (Claude Web, OpenAI, Gemini, LangChain, etc.) and the server handles archive search, feasibility checks, pricing exploration, order placement with human-in-the-loop confirmation, and AOI monitoring with webhook notifications.

**Stack:** Python 3.11+ · MCP Python SDK · FastAPI · SQLAlchemy 2.0 async · Postgres+PostGIS · SQLite+SpatiaLite (local) · Shapely · httpx · Pydantic · structlog · Fernet encryption · Docker

**Do not suggest switching frameworks or languages.** The stack is finalized per the SPEC and DESIGN_DECISIONS documents.

## Commands

### Local Development (Single User)
```bash
uv sync                              # Install all dependencies
uv run purveyor serve --local         # Run with SQLite, no external deps
uv run purveyor serve --local --reload  # With hot reload
```

### Docker
```bash
docker compose --profile minimal up -d   # App + Postgres only
docker compose --profile standard up -d  # + Redis + Caddy
docker compose --profile full up -d      # + Grafana stack
```

### Testing
```bash
uv run pytest                         # All tests
uv run pytest --cov=src/purveyor      # With coverage
uv run pytest -m "not live"           # Skip live API tests
uv run pytest -m live                 # Run live SkyFi API tests only (needs SKYFI_TEST_API_KEY)
```

### Type Checking & Linting
```bash
uv run mypy src/                      # Type checking (strict mode)
uv run ruff check src/ tests/         # Lint
uv run ruff format src/ tests/        # Format
```

### Demo Agent
```bash
uv run purveyor demo                  # Interactive CLI agent (stdio transport, no server needed)
uv run purveyor demo --workflow research --query "imagery of the Suez Canal"
```

### Database Migrations
```bash
uv run alembic upgrade head           # Apply migrations
uv run alembic revision --autogenerate -m "description"  # Generate migration
```

### Utilities
```bash
uv run purveyor generate-key          # Generate a new Fernet CONFIRMATION_SECRET_KEY
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SKYFI_API_KEY` | Yes (cloud) | — | SkyFi Platform API key |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///purveyor.db` | Database connection |
| `REDIS_URL` | No | — | Enables Redis caching/rate limiting |
| `CONFIRMATION_SECRET_KEY` | Yes (cloud) | Auto-generated (local) | Fernet key for token encryption |
| `CONFIRMATION_BASE_URL` | No | Auto-detected from request | Base URL for confirmation pages |
| `WEBHOOK_BASE_URL` | No | Same as CONFIRMATION_BASE_URL | Base URL for webhook registration |
| `SERVER_HOST` | No | `0.0.0.0` | Bind address |
| `SERVER_PORT` | No | `8000` | Bind port |
| `LOG_LEVEL` | No | `info` | Logging level |
| `LOG_FORMAT` | No | `json` | `json` (production) or `console` (dev) |
| `SENTRY_DSN` | No | — | Sentry error tracking |
| `CACHE_BACKEND` | No | `memory` | `memory` or `redis` |
| `ALLOWED_ORIGINS` | No | `*` | CORS allowed origins (comma-separated) |
| `GEOCODING_BASE_URL` | No | Nominatim public | Override for self-hosted Nominatim |

In local mode, `CONFIRMATION_SECRET_KEY` is auto-generated ephemerally. In cloud mode (`local_mode=False`), server refuses to start without it.

## Project Structure

```
skyfi-purveyor-mcp/
├── src/purveyor/
│   ├── __init__.py                # Package with __version__
│   ├── server.py                  # MCP server setup, Streamable HTTP transport
│   ├── app.py                     # FastAPI application (health, webhooks, confirm pages)
│   ├── cli.py                     # CLI entry point (serve, demo, generate-key)
│   ├── tools/                     # MCP tool implementations
│   │   ├── archives.py            # search_archives, get_archive_details
│   │   ├── orders.py              # create_*_order, list_orders, get_order_status, download, cancel
│   │   ├── pricing.py             # get_pricing
│   │   ├── feasibility.py         # check_feasibility, get_pass_predictions
│   │   ├── notifications.py       # setup_monitoring, list/get/delete notifications
│   │   ├── geospatial.py          # geocode_location, create_aoi_from_point, calculate_aoi_area
│   │   └── account.py             # whoami
│   ├── resources/                 # MCP resource implementations
│   │   └── skyfi_resources.py     # skyfi://pricing/current, skyfi://orders/recent, etc.
│   ├── core/
│   │   ├── skyfi_client.py        # SkyFi API wrapper (httpx + tenacity)
│   │   ├── skyfi_types.py         # Pydantic models for all SkyFi API types
│   │   ├── cache.py               # Tiered caching (memory TTL / Redis)
│   │   ├── auth.py                # Auth provider interface (local JSON / cloud headers)
│   │   ├── rate_limiter.py        # Sliding window (memory / Redis)
│   │   ├── confirmation.py        # Fernet token encrypt/decrypt, confirmation flow
│   │   ├── config.py              # Pydantic Settings
│   │   └── logging.py             # structlog setup
│   ├── models/                    # SQLAlchemy 2.0 async models
│   │   ├── base.py                # Declarative base, mixins
│   │   ├── database.py            # Engine/session factories (SQLite + Postgres)
│   │   └── tables.py              # order_confirmations, webhook_events, background_tasks, etc.
│   ├── webhooks/                  # FastAPI webhook receiver
│   │   └── receiver.py            # /webhooks/order-event, /webhooks/archive-notification
│   └── demo/                      # Demo agent
│       └── agent.py               # Claude API wrapper, stdio MCP transport
├── tests/
│   ├── conftest.py
│   ├── test_skyfi_client.py       # respx-mocked API tests
│   ├── test_cache.py
│   ├── test_geospatial.py         # + hypothesis property tests
│   ├── test_confirmation.py       # Token encrypt/decrypt, flow tests
│   ├── test_webhooks.py
│   └── ...
├── docs/
│   ├── SPEC.md                    # Technical specification
│   ├── PRD.md                     # Product requirements
│   ├── IMPLEMENTATION_PLAN.md     # Phased build plan
│   ├── DESIGN_DECISIONS.md        # Interview-derived decisions
│   ├── openapi.json               # SkyFi API spec (pinned)
│   ├── purveyor-architecture.mermaid
│   └── integrations/              # Per-platform setup guides
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile
│   │   └── Caddyfile
│   ├── terraform/
│   │   ├── aws/                   # ECS Fargate + RDS + ElastiCache
│   │   └── gcp/                   # Cloud Run + Cloud SQL + Memorystore
│   └── docker-compose.yml
├── alembic/
│   ├── alembic.ini
│   └── versions/
├── .claude/
│   ├── TOOLS.md                   # MCP servers and skills reference
│   └── skills/                    # Installed Claude Code skills
├── config.example.json
├── pyproject.toml
├── skills-lock.json
└── README.md
```

## Architecture

### MCP Transport

Purveyor uses **Streamable HTTP** (single `/mcp` endpoint). Client sends JSON-RPC via POST; server responds with standard HTTP or upgrades to SSE stream for notifications. Session management via `Mcp-Session-Id` header.

### Order Confirmation Flow (Critical Path)

This is the most architecturally complex flow — read DESIGN_DECISIONS.md §1–§6 before modifying:

1. Agent calls `create_tasking_order` / `create_archive_order`
2. Purveyor validates params, estimates cost from pricing matrix
3. Purveyor encrypts (API key + order params) into a Fernet token → becomes the URL
4. Returns `confirmation_url` to agent (NOT an order)
5. Agent tells user to click the URL
6. User opens `/confirm/{token}` → sees order details, cost, confirm/cancel buttons
7. User clicks Confirm → Purveyor decrypts token in-memory, places order via SkyFi API
8. `order_confirmations` table tracks only: token hash, status, skyfi_order_id, timestamps

**Key constraints:**
- API key is NEVER stored in the database (NF-08)
- Token is Fernet-encrypted (AES-128-CBC + HMAC-SHA256), 30-minute TTL
- `CONFIRMATION_SECRET_KEY` must be consistent across all instances in multi-instance deployments
- Confirmation is single-use (enforced via DB status check with `SELECT FOR UPDATE SKIP LOCKED`)

### Webhook Security

Webhooks from SkyFi are treated as **untrusted hints**:
1. Validate shared secret token in webhook URL query param
2. Verify actual state by calling SkyFi's API before updating local records
3. SkyFi's API is always the source of truth, never the webhook payload

### Error Handling

Two-tier error model (see DESIGN_DECISIONS.md §7):
- **Business errors** → `isError=true` in MCP content with structured code/message/detail
- **Infrastructure errors** → JSON-RPC error codes (-32603, etc.)

Error codes: `aoi_too_large`, `no_results`, `rate_limited`, `invalid_input`, `skyfi_api_error`, `skyfi_unavailable`, `order_expired`, `feasibility_timeout`, `open_data_limit_reached`

### Tool Response Format

All tool responses include structured data AND a factual summary (see DESIGN_DECISIONS.md §13):
- Summary is written for the agent to relay, NOT verbatim user-facing prose
- No first-person voice, no suggestions, no conversational filler
- Dense and factual: counts, ranges, notable items, next-step context

## Key Design Decisions

Read `docs/DESIGN_DECISIONS.md` for full rationale. Critical decisions:

- **Encrypted confirmation tokens** — API key lives in the URL token, not the database
- **Ephemeral key in local mode** — `CONFIRMATION_SECRET_KEY` auto-generated; required in cloud
- **Layered base URL resolution** — explicit config → request headers → localhost fallback
- **Webhook verification** — always verify against SkyFi API, never trust webhook payload directly
- **Reconnect delivery** — missed notifications delivered on next session init from `webhook_events` table
- **Notification registry** — lightweight table mapping notification_id → api_key_hash for webhook routing
- **Lenient API parsing** — Pydantic `extra='ignore'`, weekly OpenAPI spec diff in CI
- **Global Nominatim semaphore** — 1 req/sec rate limit + 1-hour geocode cache
- **Async feasibility** — quick initial poll, return pending status if not ready, agent follows up
- **DB row locking** — `SELECT FOR UPDATE SKIP LOCKED` for multi-instance task claiming
- **CORS allow-all** — API key in headers is the auth boundary, not browser origin
- **Stdio demo agent** — `purveyor demo` uses MCP stdio transport, no HTTP server needed
- **Delivery optional** — default `NONE` driver, validate typed schemas only when driver specified

## SkyFi API

- **Base URL:** `https://app.skyfi.com/platform-api`
- **Auth:** `X-Skyfi-Api-Key` header
- **Pinned spec:** `docs/openapi.json` — weekly CI job diffs against live spec
- **Key limits:** AOI max 500 vertices, search max 500k sq km, webhook 2s timeout + 3 retries
- **Pydantic config:** `extra='ignore'` on all response models for forward compatibility

## Testing

- **Framework:** pytest + pytest-asyncio + respx (mocked HTTP) + testcontainers (Postgres) + hypothesis (geospatial)
- **Mocked tests** run always in CI, no credentials needed
- **Live tests** behind `@pytest.mark.live`, gated on `SKYFI_TEST_API_KEY` env var, read-only operations only
- **Weekly scheduled CI** runs live test suite to catch SkyFi API drift
- **Coverage target:** >80% line coverage
- **Property tests:** hypothesis for geometry validation, coordinate round-trips, AOI edge cases

## Git Workflow

### Conventional Commits

```
<type>(scope): <description>
```

**Types:** feat, fix, test, docs, refactor, chore, style, perf

**Scopes:** tools, core, models, webhooks, demo, deploy, docs, tests

**Rules:**
- Lowercase type and description. No period at end.
- Imperative mood: "add", "fix", "update" — not "added", "fixes", "updated".
- Keep the first line under 72 characters.

**Examples:**
```
feat(tools): add search_archives with pagination and caching
feat(core): implement fernet-based confirmation token flow
feat(webhooks): add order event receiver with verification
feat(tools): add geocode_location with nominatim rate limiting
test(core): add confirmation token encrypt/decrypt tests
test(tools): add hypothesis property tests for aoi validation
chore(deploy): add docker-compose with minimal/standard/full profiles
docs: add claude web integration guide
```

### Commit Cadence

One logical unit of work = one commit. Don't batch unrelated changes. Don't commit half-finished features.

## Rules

- Read `docs/DESIGN_DECISIONS.md` before modifying the confirmation flow, webhook handling, or error model
- Read `docs/SPEC.md` for full tool schemas and SkyFi API surface
- Never store API keys in the database — the Fernet token IS the credential carrier
- Never log API keys, delivery credentials, or confirmation token contents
- Scrub `delivery_params`, `aws_secret_key`, `gs_credentials`, `azure_connection_string` from all log output
- All SkyFi response models use `model_config = ConfigDict(extra='ignore')` — never strict mode
- Webhooks are hints, not truth — always verify against SkyFi API before updating state
- Background tasks must be idempotent — safe to run multiple times
- Use `SELECT FOR UPDATE SKIP LOCKED` for task claiming in Postgres (simple SELECT for SQLite)
- Nominatim rate limit: 1 req/sec enforced by global asyncio semaphore
- Use `asyncio.to_thread` for CPU-bound Shapely operations
- Tool summaries are agent-facing briefings, not user-facing prose
- CORS defaults to `*` — API key headers are the auth boundary
