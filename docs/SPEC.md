# Purveyor — Technical Specification

**Version:** 1.0.0-draft
**Project:** SkyFi MCP Server (codename: Purveyor)
**Status:** Pre-implementation

## 1. Overview

Purveyor is a remote Model Context Protocol (MCP) server that wraps SkyFi's Platform API, enabling AI agents to conversationally search, order, and monitor satellite imagery. The server exposes SkyFi's capabilities as MCP tools and resources, supports both local single-user and cloud multi-user deployment, and integrates with any MCP-compatible AI client.

### 1.1 Design Principles

- **Progressive complexity** — Start with the minimum viable infrastructure; add services only when concrete limits are hit
- **Framework-agnostic** — The MCP server works with any compliant client; no coupling to a specific AI framework
- **Human-in-the-loop for payments** — Orders always require explicit human confirmation via out-of-band checkout
- **Stateless transport** — Streamable HTTP transport; no server-side session affinity required for the MCP layer
- **Cache-first for reads** — Reduce SkyFi API load and improve agent response latency through tiered caching

### 1.2 System Context

```
┌─────────────────┐        ┌──────────────────────┐        ┌─────────────────┐
│   MCP Clients   │───────▶│   Purveyor      │───────▶│  SkyFi Platform │
│                 │  MCP   │   MCP Server          │ HTTP   │  API            │
│ Claude Web      │ Stream │                       │        │                 │
│ OpenAI          │ HTTP   │ Tools · Resources     │        │ /archives       │
│ Gemini          │        │ Cache · Auth          │        │ /orders         │
│ LangChain       │        │ Rate Limiting         │        │ /pricing        │
│ Custom agents   │        │ Webhooks              │        │ /feasibility    │
└─────────────────┘        └──────────┬───────────┘        │ /notifications  │
                                      │                     └─────────────────┘
                           ┌──────────▼───────────┐
                           │   Data Layer          │        ┌─────────────────┐
                           │ SQLite (local)        │        │ OpenStreetMap   │
                           │ Postgres+PostGIS      │        │ Overpass API    │
                           │ Redis (optional)      │        └─────────────────┘
                           └──────────────────────┘
```

## 2. SkyFi Platform API Surface

Purveyor wraps the following SkyFi Platform API endpoints (v2.0.0). The full OpenAPI specification is at `https://app.skyfi.com/platform-api/openapi.json`.

### 2.1 Core

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ping` | GET | Health check |
| `/health_check` | GET | Service status |
| `/demo-delivery` | POST | Test delivery to a customer bucket |
| `/auth/whoami` | GET | Current user info, budget, payment status |

### 2.2 Archive Search

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/archives` | POST | Search catalog by AOI, product type, date range, resolution, cloud cover, provider, open data flag. Returns paginated results with `nextPage` cursor. |
| `/archives` | GET | Continue paging with `?page=<hash>` |
| `/archives/{archive_id}` | GET | Get full metadata for a single archive image |

Key request parameters for archive search:
- `aoi` — WKT POLYGON (max 500 vertices, max 500,000 sq km for searches)
- `fromDate` / `toDate` — ISO 8601 UTC datetime
- `maxCloudCoveragePercent` — 0–100
- `maxOffNadirAngle` — 0–50
- `resolutions` — `LOW`, `MEDIUM`, `HIGH`, `VERY HIGH`, `SUPER HIGH`, `ULTRA HIGH`, `CM 30`, `CM 50`, `SPOT`, `SPOT FINE`, `SLEA`, `DWELL`, `DWELL FINE`, `STRIP`, `SCAN`
- `productTypes` — `DAY`, `NIGHT`, `VIDEO`, `MULTISPECTRAL`, `HYPERSPECTRAL`, `SAR`, `STEREO`, `BASEMAP`
- `providers` — `SIWEI`, `SATELLOGIC`, `UMBRA`, `GEOSAT`, `SENTINEL1_CREODIAS`, `SENTINEL2`, `SENTINEL2_CREODIAS`, `PLANET`, `IMPRO`, `URBAN_SKY`, `NSL`, `VEXCEL`, `ICEYE_US`
- `openData` — boolean
- `pageSize` — 1–100 (default 100)

### 2.3 Ordering

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/order-tasking` | POST | Create a tasking order (future satellite capture) |
| `/order-archive` | POST | Create an archive order (existing imagery) |
| `/orders` | GET | List orders with pagination, sorting, type filter |
| `/orders/{order_id}` | GET | Get order details with status history |
| `/orders/{order_id}/{deliverable_type}` | GET | Redirect to deliverable download URL (`image`, `payload`, `cog`) |
| `/orders/{order_id}/redelivery` | POST | Reschedule delivery with new bucket credentials |

Order statuses (lifecycle): `CREATED` → `STARTED` → `PROVIDER_PENDING` → `PROVIDER_COMPLETE` → `PROCESSING_PENDING` → `PROCESSING_COMPLETE` → `DELIVERY_PENDING` → `DELIVERY_COMPLETED`

Failure branches: `PAYMENT_FAILED`, `PLATFORM_FAILED`, `PROVIDER_FAILED`, `PROCESSING_FAILED`, `DELIVERY_FAILED`

Delivery drivers: `S3`, `GS` (Google Cloud Storage), `AZURE`, `NONE`

### 2.4 Pricing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pricing` | POST | Get full pricing matrix for all product/resolution/provider combinations. Optionally pass an AOI for area-specific pricing. |

### 2.5 Feasibility

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/feasibility` | POST | Create a feasibility task for a specific AOI, product type, resolution, and date range. Returns task ID. |
| `/feasibility/{feasibility_id}` | GET | Poll feasibility task status and results. Returns overall score, weather score, and per-provider scores with opportunities. |
| `/feasibility/pass-prediction` | POST | Find satellite passes over an AOI within a time window. Returns per-satellite pass details including timing, angle, and pricing. |

### 2.6 Notifications

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/notifications` | POST | Create a monitoring notification (AOI + optional filters + webhook URL) |
| `/notifications` | GET | List active notifications with pagination |
| `/notifications/{notification_id}` | GET | Get notification details with event history |
| `/notifications/{notification_id}` | DELETE | Remove a notification |

### 2.7 Webhooks (Inbound to Purveyor)

SkyFi sends webhook events to Purveyor for two event types:

**Order events** — Fired on every order status transition. Payload includes full order info plus the triggering event. 2-second timeout, 3 retries.

**Archive notification events** — Fired when a new archive image matches a notification filter. Payload is the archive metadata with overlap info. Same retry policy.

## 3. MCP Server Specification

### 3.1 Transport

Purveyor implements **Streamable HTTP** transport per the updated MCP specification (March 2025). This replaces the older dual-endpoint HTTP+SSE pattern.

**Single endpoint:** `POST /mcp` (or configurable path)

- Client sends JSON-RPC messages via HTTP POST
- Server responds with either a standard JSON-RPC response or an SSE stream
- SSE streaming is used when the server needs to send notifications (e.g., webhook-triggered events)
- Session management via `Mcp-Session-Id` header
- Supports JSON-RPC batching

**Backwards compatibility:** An optional legacy `/sse` endpoint can be exposed for older clients, implemented as a thin adapter over the Streamable HTTP core.

### 3.2 Tools

Each tool maps to one or more SkyFi API calls with caching, validation, and user-friendly error handling layered on top.

#### 3.2.1 Archive Tools

**`search_archives`**

```
Input:
  location: string          # Place name OR WKT polygon
  product_type: string[]?   # DAY, SAR, MULTISPECTRAL, etc.
  resolution: string[]?     # LOW, HIGH, VERY HIGH, etc.
  from_date: string?        # ISO date
  to_date: string?          # ISO date
  max_cloud_cover: number?  # 0-100
  max_off_nadir: number?    # 0-50
  open_data: boolean?       # Filter for free imagery
  provider: string[]?       # PLANET, UMBRA, etc.
  page_size: number?        # 1-100, default 25
  next_page: string?        # Pagination cursor

Output:
  archives: Archive[]       # Matching images with metadata
  total: number?
  next_page: string?        # Cursor for next page
  search_summary: string    # Human-readable summary
```

Behavior:
- If `location` is a place name (not WKT), resolve to AOI via OpenStreetMap geocoding
- Cache results with TTL of 1 minute (keyed by full request parameters)
- Return thumbnail URLs when available
- Include pricing info per archive (price per sq km, full scene price)

**`get_archive_details`**

```
Input:
  archive_id: string        # UUID

Output:
  archive: Archive          # Full archive metadata
```

#### 3.2.2 Pricing Tools

**`get_pricing`**

```
Input:
  aoi: string?              # WKT polygon or place name (optional)
  product_type: string?     # Filter to specific product
  resolution: string?       # Filter to specific resolution

Output:
  pricing_matrix: object    # Full or filtered pricing options
  summary: string           # Human-readable pricing summary
```

Behavior:
- Cache with TTL of 5 minutes
- When `aoi` is provided, include area-based cost estimates

#### 3.2.3 Feasibility Tools

**`check_feasibility`**

```
Input:
  location: string          # Place name or WKT polygon
  product_type: string      # DAY, SAR, etc.
  resolution: string        # HIGH, VERY HIGH, etc.
  start_date: string        # ISO datetime
  end_date: string          # ISO datetime
  max_cloud_cover: number?  # 0-100
  provider: string?         # PLANET, UMBRA

Output:
  feasibility_id: string
  overall_score: number
  weather_score: object?
  provider_scores: ProviderScore[]
  opportunities: Opportunity[]
  summary: string           # Human-readable feasibility assessment
```

Behavior:
- Creates a feasibility task and polls until completion (or timeout)
- Cache results with TTL of 2 minutes
- Return human-readable interpretation of scores

**`get_pass_predictions`**

```
Input:
  location: string          # Place name or WKT polygon
  from_date: string
  to_date: string
  product_types: string[]?
  resolutions: string[]?
  max_off_nadir: number?

Output:
  passes: Pass[]            # Satellite passes with timing, pricing, angles
  summary: string
```

#### 3.2.4 Order Tools

**`create_tasking_order`**

```
Input:
  location: string          # Place name or WKT polygon
  product_type: string
  resolution: string
  window_start: string      # ISO datetime
  window_end: string        # ISO datetime
  delivery_driver: string   # S3, GS, AZURE
  delivery_params: object   # Bucket credentials
  max_cloud_cover: number?
  max_off_nadir: number?
  provider: string?
  provider_window_id: string?  # From feasibility for pass selection
  priority: boolean?
  metadata: object?

Output:
  confirmation_url: string  # URL for human to review and confirm
  estimated_cost: number    # In cents
  order_summary: string     # Human-readable order details for review
```

Behavior:
- **CRITICAL:** Does NOT immediately place the order
- Returns a confirmation URL where the human reviews the price and confirms
- The MCP tool response explicitly tells the agent to present the confirmation URL to the user
- After human confirms, Purveyor receives the webhook or detects confirmation via polling
- Tool annotations: `{ "destructive": true, "requiresConfirmation": true, "cost": "variable" }`

**`create_archive_order`**

```
Input:
  aoi: string               # WKT polygon
  archive_id: string
  delivery_driver: string
  delivery_params: object
  metadata: object?

Output:
  confirmation_url: string
  estimated_cost: number
  order_summary: string
```

Same human-confirmation flow as tasking orders.

**`get_order_status`**

```
Input:
  order_id: string

Output:
  order: OrderInfo          # Full order with status history
  download_urls: object?    # Available deliverables
  summary: string
```

**`list_orders`**

```
Input:
  order_type: string?       # ARCHIVE or TASKING
  page: number?
  page_size: number?
  sort_by: string?          # created_at, status, cost
  sort_dir: string?         # asc, desc

Output:
  orders: OrderSummary[]
  total: number
  summary: string
```

**`download_deliverable`**

```
Input:
  order_id: string
  deliverable_type: string  # image, payload, cog

Output:
  download_url: string      # Signed URL for download
  file_size: number?        # Bytes, if known
```

**`request_redelivery`**

```
Input:
  order_id: string
  delivery_driver: string
  delivery_params: object

Output:
  status: string
  order: OrderInfo
```

#### 3.2.5 Notification Tools

**`setup_monitoring`**

```
Input:
  location: string          # Place name or WKT polygon
  webhook_url: string       # Where to send notifications
  product_type: string?     # Filter
  gsd_min: number?          # Min ground sample distance
  gsd_max: number?          # Max ground sample distance

Output:
  notification_id: string
  summary: string
```

**`list_notifications`**

```
Input:
  page: number?
  page_size: number?

Output:
  notifications: Notification[]
  total: number
```

**`get_notification_history`**

```
Input:
  notification_id: string

Output:
  notification: NotificationWithHistory
```

**`delete_notification`**

```
Input:
  notification_id: string

Output:
  status: string
```

#### 3.2.6 Geospatial Tools

**`geocode_location`**

```
Input:
  place_name: string        # "Port of Los Angeles", "Manaus, Brazil", etc.

Output:
  coordinates: [number, number]  # [lat, lon]
  bounding_box: number[]?   # [south, north, west, east]
  display_name: string      # Full resolved name
  aoi_wkt: string?          # Suggested AOI polygon
```

Behavior:
- Uses OpenStreetMap Nominatim for geocoding
- Uses Overpass API for complex geographic features
- Cache OSM results with TTL of 1 hour

**`create_aoi_from_point`**

```
Input:
  latitude: number
  longitude: number
  area_sq_km: number        # Desired area

Output:
  aoi_wkt: string           # WKT POLYGON
  actual_area_sq_km: number
```

**`calculate_aoi_area`**

```
Input:
  aoi_wkt: string           # WKT POLYGON

Output:
  area_sq_km: number
  vertex_count: number
  is_valid: boolean
  validation_message: string?
```

#### 3.2.7 Account Tools

**`whoami`**

```
Input: (none)

Output:
  user_id: string
  email: string
  name: string
  budget_used: number       # In cents
  budget_total: number      # In cents
  has_payment_method: boolean
  is_demo_account: boolean
```

### 3.3 Tool Annotations

Per the updated MCP spec, tools include behavioral annotations:

```json
{
  "search_archives": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": true
  },
  "create_tasking_order": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "idempotentHint": false,
    "openWorldHint": true,
    "requiresConfirmation": true
  },
  "delete_notification": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "idempotentHint": true,
    "openWorldHint": false
  }
}
```

### 3.4 Resources

Resources provide contextual data that agents can reference without explicit tool calls.

| URI | Description | Update Frequency |
|-----|-------------|-----------------|
| `skyfi://pricing/current` | Full pricing matrix | Cached 5 min |
| `skyfi://orders/recent` | Last 10 orders for current user | Live |
| `skyfi://account/info` | Account details and budget | Live |
| `skyfi://providers/list` | Available satellite providers | Cached 1 hour |
| `skyfi://resolutions/list` | Supported resolution tiers | Cached 1 hour |

### 3.5 Capability Negotiation

The server supports capability negotiation per MCP spec. On `initialize`, the server responds with:

```json
{
  "capabilities": {
    "tools": { "listChanged": true },
    "resources": { "subscribe": true, "listChanged": true }
  },
  "serverInfo": {
    "name": "purveyor",
    "version": "1.0.0"
  }
}
```

Clients can discover available tools and their versions dynamically.

## 4. Authentication and Authorization

### 4.1 Auth Provider Interface

```python
class AuthProvider(Protocol):
    async def get_api_key(self, request: Request) -> str: ...
    async def validate_token(self, token: str) -> UserInfo: ...
```

Two implementations:

**LocalFileAuth** — Reads API key from `config.json`. Single-user, no multi-tenancy. Used for local development and self-hosted single-user deployments.

**CloudHeaderAuth** — Extracts `X-Skyfi-Api-Key` from request headers. Each MCP client session authenticates independently. Server stores no credentials.

### 4.2 Order Confirmation Flow

Orders use an out-of-band confirmation flow to ensure human approval:

```
1. Agent calls create_tasking_order or create_archive_order
2. Purveyor validates parameters and calculates estimated cost
3. Purveyor returns a confirmation_url (not an actual order)
4. Agent presents the URL to the user: "Please review and confirm your order"
5. User opens URL → sees order details, price, and confirm button
6. User clicks confirm → Purveyor places the actual order via SkyFi API
7. Purveyor receives order confirmation → notifies agent via SSE
```

The confirmation page is a lightweight FastAPI-served HTML page. For cloud deployments, this can be customized or replaced with a SkyFi-hosted checkout flow.

Confirmation tokens expire after 30 minutes. If the user does not confirm, the agent is notified of the timeout.

## 5. Data Layer

### 5.1 Database Schema (Minimal)

The initial schema tracks order state, confirmations, and cached webhook events. This is intentionally minimal — SkyFi's API is the source of truth for order and notification data.

```sql
-- Order confirmation tracking
CREATE TABLE order_confirmations (
    id UUID PRIMARY KEY,
    confirmation_token VARCHAR(255) UNIQUE NOT NULL,
    order_type VARCHAR(20) NOT NULL,  -- TASKING or ARCHIVE
    request_payload JSONB NOT NULL,
    estimated_cost_cents INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, confirmed, expired, placed
    skyfi_order_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);

-- Webhook event log
CREATE TABLE webhook_events (
    id UUID PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,   -- order_status, archive_notification
    payload JSONB NOT NULL,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Background task tracking
CREATE TABLE background_tasks (
    id UUID PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0
);
```

For PostGIS-enabled deployments, add spatial indexing on cached AOI data:

```sql
-- OSM geocoding cache (PostGIS only)
CREATE TABLE geocode_cache (
    id UUID PRIMARY KEY,
    place_name VARCHAR(500) NOT NULL,
    coordinates GEOMETRY(Point, 4326),
    bounding_box GEOMETRY(Polygon, 4326),
    display_name TEXT,
    raw_response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_geocode_place ON geocode_cache (place_name);
CREATE INDEX idx_geocode_coords ON geocode_cache USING GIST (coordinates);
```

### 5.2 SQLite Mode

For local single-user deployment, SQLite replaces Postgres. SpatiaLite provides geometry functions. The schema is identical minus PostGIS-specific index types. Alembic migrations include conditional logic for SQLite vs Postgres.

### 5.3 Caching Strategy

**Tier 1 — In-memory (Phase 1)**

Uses `cachetools.TTLCache` with per-key-type TTLs:

| Cache Target | TTL | Key Pattern |
|-------------|-----|-------------|
| Pricing matrix | 5 min | `pricing:{aoi_hash}` |
| Feasibility scores | 2 min | `feasibility:{request_hash}` |
| Archive search results | 1 min | `archives:{request_hash}` |
| OSM geocoding | 1 hour | `geocode:{place_name_normalized}` |
| Overpass queries | 1 hour | `overpass:{query_hash}` |
| User info (whoami) | 5 min | `whoami:{api_key_hash}` |

Cache invalidation: placing an order clears pricing and archive caches for the affected AOI.

**Tier 2 — Redis (Phase 2)**

Same TTLs, but backed by Redis. Adds cross-process cache sharing and persistence across restarts. Activated by setting `REDIS_URL` and `CACHE_BACKEND=redis`.

## 6. Rate Limiting

### 6.1 Inbound (Protecting Purveyor)

Phase 1: In-memory sliding window counters (per API key / IP).

Default limits:
- 60 requests/minute per API key for read operations
- 10 requests/minute per API key for write operations (orders, notifications)
- 5 order confirmations/hour per API key

Phase 2: Redis-backed sliding window for persistence across restarts and multi-instance deployments.

### 6.2 Outbound (Respecting SkyFi API)

Tenacity retry with exponential backoff + jitter:
- Max 3 retries
- Initial delay: 1 second
- Max delay: 30 seconds
- Jitter: ±0.5 seconds
- Retry on: 429 (rate limited), 500/502/503/504 (server errors)

The human confirmation requirement for orders is itself a natural rate limiter for the costliest operation.

## 7. Webhook Receiver

FastAPI application running alongside the MCP server (same process, different routes).

### 7.1 Endpoints

**`POST /webhooks/order-event`** — Receives order status change events from SkyFi. Logs the event, updates the order confirmation record if applicable, and pushes a notification to the connected MCP client via SSE stream.

**`POST /webhooks/archive-notification`** — Receives new archive match events from SkyFi's notification system. Logs the event and pushes to the connected MCP client for display (analogous to a ChatGPT Pulse item).

### 7.2 Webhook Security

- Validate webhook signatures (when SkyFi supports them)
- Rate limit inbound webhooks (100/minute)
- Idempotency: deduplicate by event ID before processing

## 8. Observability

### Phase 1 (Launch)

- **Logging:** structlog with JSON output in production, pretty-print in dev. Log all SkyFi API calls (method, status, latency), all MCP tool invocations, and all webhook events.
- **Health endpoint:** `GET /health` returning service status, database connectivity, and SkyFi API reachability.
- **Error tracking:** Sentry integration for unhandled exceptions and SkyFi API errors.

### Phase 2

- **OpenTelemetry:** Instrument SkyFi API calls, MCP tool invocations, cache hits/misses, and database queries with traces and spans.

### Phase 3

- **Grafana stack:** Tempo (traces) + Prometheus (metrics) + Grafana (dashboards). Available as optional docker-compose override.

## 9. Deployment

### 9.1 Local Development

```bash
uv run purveyor serve --local --reload
```

Single process, SQLite, in-memory cache, no external dependencies.

### 9.2 Docker Compose Profiles

**`minimal`** — Purveyor + Postgres+PostGIS. Suitable for single-user self-hosting.

**`standard`** — Adds Redis (caching, rate limiting) + Caddy (HTTPS/SSL termination). Suitable for small team self-hosting.

**`full`** — Adds Grafana + Tempo + Prometheus. For operators who need observability.

### 9.3 Cloud Targets

**AWS Fargate** — Terraform module provisions ECS Fargate service, RDS Postgres, ElastiCache Redis, ALB, and ACM certificate.

**Google Cloud Run** — Terraform module provisions Cloud Run service, Cloud SQL Postgres, Memorystore Redis, and Cloud Load Balancing.

Both share the same Docker image with configuration via environment variables.

## 10. Testing Strategy

### 10.1 Unit Tests

- All MCP tool handlers with mocked SkyFi client
- Caching logic (TTL expiry, invalidation)
- Rate limiter behavior
- AOI validation and geospatial calculations
- Auth provider implementations

### 10.2 Integration Tests

- SkyFi API client against real API responses (mocked with respx)
- Database operations via testcontainers (Postgres+PostGIS)
- Webhook receiver end-to-end
- Order confirmation flow

### 10.3 Property-Based Tests (Hypothesis)

- Geometry validation (arbitrary WKT polygons)
- Coordinate transformations (round-trip accuracy)
- AOI area calculations (edge cases near poles, antimeridian)
- Cache key generation (no collisions for distinct requests)

### 10.4 End-to-End Tests

- Full MCP client → Purveyor → mocked SkyFi API flow
- Claude Web integration smoke test
- Order confirmation flow end-to-end

## 11. Security Considerations

- API keys are never logged or cached in plaintext
- Confirmation tokens are cryptographically random, single-use, and time-limited
- Delivery credentials (S3/GCS/Azure bucket keys) are passed through to SkyFi and never persisted by Purveyor
- Cloud mode is stateless — no user credentials stored server-side
- All external HTTP calls use TLS
- Input validation via Pydantic on all tool inputs
- WKT polygon validation (max vertices, max area, convexity checks) before forwarding to SkyFi
