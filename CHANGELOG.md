# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-03-12

### Added

#### MCP Tools (20 total)
- `search_archives` — Search satellite catalog by location, date, resolution, provider, and cloud cover. Accepts place names or WKT polygons.
- `get_archive_details` — Full metadata for a specific archive image
- `get_pricing` — Full pricing matrix for all product/resolution/provider combinations with optional AOI cost estimates
- `check_feasibility` — Dual-mode tool: creates a SkyFi feasibility task and returns results when ready, or polls a pending task
- `get_pass_predictions` — Upcoming satellite passes over an AOI with timing, angle, and pricing
- `create_tasking_order` — Initiate a new satellite capture (returns confirmation URL, does NOT place order)
- `create_archive_order` — Order an existing archive image (returns confirmation URL)
- `cancel_pending_order` — Cancel a pending order before confirmation
- `list_orders` — List previous orders with filtering and pagination
- `get_order_status` — Order details with status history and download URLs
- `download_deliverable` — Signed download URL for completed orders (image, payload, cog)
- `request_redelivery` — Redeliver imagery to a different storage bucket
- `setup_monitoring` — Create an AOI monitor that alerts when new imagery is ingested
- `list_notifications` — List active AOI monitors
- `get_notification_history` — View event history for a monitor
- `delete_notification` — Remove an AOI monitor
- `geocode_location` — Resolve place names to coordinates and AOI polygons via OpenStreetMap
- `create_aoi_from_point` — Generate WKT polygon from center point and desired area (sq km)
- `calculate_aoi_area` — Calculate area in sq km and validate vertex count
- `whoami` — Account info, budget usage, payment status, and inferred account tier

#### MCP Resources (5 total)
- `skyfi://pricing/current` — Full pricing matrix (cached 5 min)
- `skyfi://orders/recent` — Last 10 orders for current user
- `skyfi://account/info` — Account details and budget
- `skyfi://providers/list` — Available satellite providers (cached 1 hour)
- `skyfi://resolutions/list` — Supported resolution tiers (cached 1 hour)

#### Core Infrastructure
- **Streamable HTTP transport** — Single `/mcp` endpoint per updated MCP spec (March 2025)
- **stdio transport** — For demo agent and local development
- **Tiered caching** — In-memory TTL cache (Phase 1) + Redis (Phase 2) with configurable TTLs
- **Auth providers** — LocalFileAuth (config.json) and CloudHeaderAuth (X-Skyfi-Api-Key header)
- **Rate limiting** — Sliding window counters: 60/min reads, 10/min writes, 5/hour confirmations
- **Inbound rate limiting** — In-memory or Redis-backed, with X-RateLimit-* headers
- **Background tasks** — FastAPI background tasks with DB state tracking and startup recovery

#### Security
- **Fernet-encrypted confirmation tokens** — API key + order params encrypted into the URL; never stored in the database
- **Order confirmation flow** — All orders require human approval via `/confirm/{token}` page before placement
- **Webhook security** — Shared secret validation + verify-against-SkyFi-API before updating local state
- **Log scrubbing** — structlog processor redacts API keys, delivery credentials, and token contents
- **Single-use enforcement** — `SELECT FOR UPDATE SKIP LOCKED` prevents duplicate order placement

#### Observability
- **structlog** — JSON output in production, colored console in development
- **Sentry integration** — Captures unhandled exceptions and SkyFi API errors; excludes business errors and 429s
- **Health endpoint** — `/health` checks DB, SkyFi API, Redis connectivity
- **Readiness endpoint** — `/ready` for Kubernetes readiness probes

#### Deployment
- **Docker** — Multi-stage Dockerfile with non-root user
- **Docker Compose** — `minimal` (app + Postgres), `standard` (+ Redis + Caddy), `full` (+ Grafana stack)
- **Terraform AWS** — ECS Fargate + RDS Postgres + ALB + ElastiCache (optional)
- **Terraform GCP** — Cloud Run + Cloud SQL + Memorystore (optional) + Secret Manager

#### Developer Experience
- **Demo agent** — Interactive CLI powered by Claude with stdio MCP transport; no server setup needed
- **Pre-built workflows** — `research`, `monitor`, `order` demo workflows
- **277+ tests** — pytest + respx + testcontainers + hypothesis (property tests)
- **81%+ coverage** — mypy strict mode, ruff linting
- **8 integration guides** — Claude Web, Claude Code, OpenAI, Anthropic API, Gemini, LangChain, Google ADK, Vercel AI SDK
- **CI/CD** — GitHub Actions for lint, typecheck, test matrix, Docker build, weekly live tests, OpenAPI drift detection
