# Purveyor — Implementation Plan for Claude Code

This document is a step-by-step implementation plan designed to be executed by Claude Code. Each phase is broken into discrete tasks with clear inputs, outputs, and acceptance criteria. Tasks within a phase can be worked sequentially.

The plan references:
- **SPEC.md** for technical details
- **PRD.md** for requirements (F-xxx IDs)
- **openapi.json** at `/mnt/user-data/uploads/openapi.json` for the SkyFi API specification

---

## Phase 0 — Project Scaffolding

**Goal:** Set up the project structure, tooling, and CI foundation so all subsequent work builds on a solid base.

### Task 0.1: Initialize Project with uv

```
Create a new Python project using uv.

1. Create the directory structure:
   skyfi-purveyor-mcp/
   ├── src/purveyor/
   │   ├── __init__.py          # Package with __version__
   │   ├── server.py            # MCP server entry point (stub)
   │   ├── cli.py               # CLI entry point (stub)
   │   ├── tools/
   │   │   └── __init__.py
   │   ├── resources/
   │   │   └── __init__.py
   │   ├── core/
   │   │   └── __init__.py
   │   ├── models/
   │   │   └── __init__.py
   │   └── webhooks/
   │       └── __init__.py
   ├── tests/
   │   ├── __init__.py
   │   ├── conftest.py
   │   └── test_placeholder.py  # One passing test
   ├── docs/
   │   └── integrations/
   ├── deploy/
   │   ├── docker/
   │   │   └── Dockerfile
   │   └── terraform/
   ├── alembic/
   ├── pyproject.toml
   ├── README.md
   └── .gitignore

2. pyproject.toml should include:
   - name = "purveyor"
   - python requires >= 3.11
   - Dependencies: mcp, fastapi, uvicorn[standard], httpx, pydantic>=2.0,
     sqlalchemy[asyncio]>=2.0, alembic, geoalchemy2, shapely, pyproj,
     geopy, tenacity, structlog, cachetools, sentry-sdk[fastapi]
   - Dev dependencies: pytest, pytest-asyncio, respx, testcontainers,
     hypothesis, mypy, ruff, types-cachetools
   - CLI entry point: purveyor = "purveyor.cli:main"
   - mypy strict mode config
   - ruff config (line-length=100, target python 3.11)
   - pytest config (asyncio_mode=auto)

3. Run `uv sync` to install all dependencies
4. Run `uv run pytest` to verify the placeholder test passes
5. Run `uv run mypy src/` to verify type checking works
6. Run `uv run ruff check src/` to verify linting works

Acceptance: All three commands pass cleanly.
```

### Task 0.2: Configure structlog

```
Create src/purveyor/core/logging.py

1. Configure structlog with two modes:
   - Production: JSON output, timestamps, log level, module name
   - Development: Human-readable colored output with timestamps

2. Selection based on environment variable LOG_FORMAT (default: "json")
   - "json" → JSON processor chain
   - "console" → dev/console processor chain

3. Create a setup_logging() function that should be called at application startup
4. Add LOG_LEVEL environment variable support (default: "info")

Write tests in tests/test_logging.py:
- Test that JSON mode produces valid JSON
- Test that log level filtering works

Acceptance: structlog outputs JSON by default, colorized output when LOG_FORMAT=console.
```

### Task 0.3: Configuration Management

```
Create src/purveyor/core/config.py

1. Define a Pydantic Settings model (BaseSettings) for all configuration:
   - skyfi_api_key: str | None (optional — required in cloud mode, not local)
   - database_url: str (default: "sqlite+aiosqlite:///purveyor.db")
   - redis_url: str | None (optional)
   - server_host: str (default: "0.0.0.0")
   - server_port: int (default: 8000)
   - log_level: str (default: "info")
   - log_format: str (default: "json")
   - sentry_dsn: str | None (optional)
   - cache_backend: Literal["memory", "redis"] (default: "memory")
   - local_mode: bool (default: False)
   - config_file: Path | None (optional — path to config.json for local mode)

2. When local_mode=True, also load settings from config.json file:
   - Read the JSON file
   - Merge values (env vars override file values)

3. Create a get_settings() function that returns a cached singleton

4. Create config.example.json with documented defaults

Write tests in tests/test_config.py:
- Test default values
- Test env var override
- Test config file loading in local mode

Acceptance: Settings load from env vars, with optional config.json overlay in local mode.
```

### Task 0.4: Database Setup with SQLAlchemy 2.0 Async

```
Create src/purveyor/models/base.py and src/purveyor/models/database.py

1. base.py:
   - Define the declarative base with a mapped_column helper
   - Define common mixins (TimestampMixin with created_at)
   - Use UUID primary keys

2. database.py:
   - Create async engine factory that handles both SQLite and Postgres
   - Create async session factory
   - Database initialization function (create tables or verify connection)
   - For SQLite: load SpatiaLite extension if available, otherwise skip
   - For Postgres: assume PostGIS is installed

3. Create the initial models in src/purveyor/models/tables.py:
   - OrderConfirmation (see SPEC.md §5.1)
   - WebhookEvent (see SPEC.md §5.1)
   - BackgroundTask (see SPEC.md §5.1)
   - GeocodeCache (see SPEC.md §5.1 — skip spatial columns for SQLite)

4. Set up Alembic:
   - alembic init alembic
   - Configure alembic/env.py for async SQLAlchemy
   - Create initial migration from the models
   - Ensure migrations work for both SQLite and Postgres

Write tests in tests/test_database.py:
- Test engine creation for SQLite
- Test creating tables
- Test basic CRUD on OrderConfirmation model

Acceptance: `alembic upgrade head` works against SQLite. Models create cleanly.
```

### Task 0.5: Dockerfile and Docker Compose

```
Create deploy/docker/Dockerfile and deploy/docker-compose.yml

1. Dockerfile:
   - Multi-stage build
   - Stage 1: Install uv, copy pyproject.toml, install dependencies
   - Stage 2: Copy source, set up non-root user
   - ENTRYPOINT: uv run purveyor serve
   - EXPOSE 8000
   - HEALTHCHECK: curl http://localhost:8000/health

2. docker-compose.yml with profiles:
   - minimal: purveyor + postgres (postgis/postgis:16-3.4)
   - standard: minimal + redis:7-alpine + caddy:2-alpine
   - full: standard + grafana + tempo + prometheus (stubs for now)
   - Volume mounts for postgres data and redis data
   - Environment variable passthrough
   - Sensible defaults (POSTGRES_DB=purveyor, etc.)

3. Create deploy/docker/Caddyfile for HTTPS termination:
   - Reverse proxy to purveyor:8000
   - Automatic HTTPS with configurable domain

Acceptance: `docker compose --profile minimal build` succeeds.
```

---

## Phase 1 — SkyFi API Client and Caching

**Goal:** Build the HTTP client wrapper for SkyFi's API with retry logic and the tiered caching layer.

### Task 1.1: SkyFi API Client

```
Create src/purveyor/core/skyfi_client.py

Read the full OpenAPI spec at /mnt/user-data/uploads/openapi.json to understand
all endpoints, request/response schemas, and authentication.

1. Create Pydantic models for all SkyFi API types in src/purveyor/core/skyfi_types.py:
   - ApiProvider (enum)
   - ProductType (enum)
   - Resolution (enum — note the space-separated format like "VERY HIGH")
   - DeliveryDriver (enum)
   - DeliveryStatus (enum)
   - OrderType (enum)
   - Archive (response model)
   - ArchiveResponse (with overlap fields)
   - GetArchivesRequest / GetArchivesResponse
   - TaskingOrderRequest / TaskingOrderResponse
   - ArchiveOrderRequest / ArchiveOrderResponse
   - OrderInfo (union of tasking and archive)
   - ListOrdersResponse
   - PricingRequest
   - FeasibilityRequest / FeasibilityResponse / FeasibilityScore
   - PassPredictionRequest / PassPredictionResponse / Pass
   - CreateNotificationRequest / NotificationResponse
   - ListNotificationsResponse / NotificationWithHistory
   - OrderRedeliveryRequest
   - WhoamiUser
   - DemoDeliveryRequest / DemoDeliveryResponse
   - Webhook payloads: OrderInfoWithEvent, ArchiveResponse (notification)

2. Create the SkyFiClient class:
   - Constructor takes base_url (default https://app.skyfi.com/platform-api)
     and an API key
   - Uses httpx.AsyncClient with:
     - Default headers: X-Skyfi-Api-Key, Accept: application/json
     - Timeout: 30 seconds
     - Base URL
   - Implement tenacity retry decorator:
     - Retry on 429, 500, 502, 503, 504
     - Exponential backoff: wait_exponential(multiplier=1, min=1, max=30)
     - Jitter: wait_random(0, 0.5)
     - Max retries: 3
   - structlog logging on every request (method, path, status, duration)

3. Implement all API methods:
   - ping() -> PongResponse
   - health_check() -> StatusResponse
   - whoami() -> WhoamiUser
   - search_archives(request: GetArchivesRequest) -> GetArchivesResponse
   - search_archives_page(page: str) -> GetArchivesResponse
   - get_archive(archive_id: str) -> Archive
   - get_pricing(request: PricingRequest | None) -> dict
   - create_tasking_order(request: TaskingOrderRequest) -> TaskingOrderResponse
   - create_archive_order(request: ArchiveOrderRequest) -> ArchiveOrderResponse
   - list_orders(order_type, page, page_size, sort_columns, sort_directions) -> ListOrdersResponse
   - get_order(order_id: str) -> OrderInfo
   - get_deliverable_url(order_id: str, deliverable_type: str) -> str
   - request_redelivery(order_id: str, request: OrderRedeliveryRequest) -> OrderInfo
   - create_feasibility_task(request: FeasibilityRequest) -> FeasibilityResponse
   - get_feasibility_status(feasibility_id: str) -> FeasibilityResponse
   - get_pass_predictions(request: PassPredictionRequest) -> PassPredictionResponse
   - create_notification(request: CreateNotificationRequest) -> NotificationResponse
   - list_notifications(page, page_size) -> ListNotificationsResponse
   - get_notification(notification_id: str) -> NotificationWithHistory
   - delete_notification(notification_id: str) -> StatusResponse
   - demo_delivery(request: DemoDeliveryRequest) -> DemoDeliveryResponse

Write tests in tests/test_skyfi_client.py using respx to mock HTTP responses:
- Test successful API calls for each method
- Test retry behavior on 429 and 500
- Test timeout handling
- Test authentication header is sent

Acceptance: All SkyFi API endpoints are callable through typed methods with retry logic.
```

### Task 1.2: Tiered Cache Layer

```
Create src/purveyor/core/cache.py

1. Define an abstract CacheBackend protocol:
   - async get(key: str) -> bytes | None
   - async set(key: str, value: bytes, ttl_seconds: int) -> None
   - async delete(key: str) -> None
   - async delete_pattern(pattern: str) -> None

2. Implement MemoryCacheBackend:
   - Uses cachetools.TTLCache under the hood
   - Thread-safe (asyncio.Lock for writes)
   - Max size configurable (default 1000 entries)

3. Implement RedisCacheBackend:
   - Uses redis.asyncio client
   - Supports pattern-based deletion (SCAN + DELETE)
   - Falls back to MemoryCacheBackend if Redis is unavailable

4. Create a CachedSkyFiClient that wraps SkyFiClient:
   - Caches these methods with the TTLs from SPEC.md §5.3:
     - search_archives: 1 min
     - get_pricing: 5 min
     - check_feasibility: 2 min
     - whoami: 5 min
     - geocode: 1 hour
   - Cache keys are deterministic hashes of the request parameters
   - Cache invalidation: create_*_order clears archive and pricing caches
   - Non-cached methods pass through directly

5. Create a get_cache_backend(settings) factory that returns the right backend

Write tests in tests/test_cache.py:
- Test MemoryCacheBackend get/set/delete/TTL expiry
- Test CachedSkyFiClient caches search results
- Test cache invalidation on order placement
- Test cache miss falls through to real client

Acceptance: Cached client wraps SkyFi client with TTL caching and invalidation.
```

### Task 1.3: Auth Provider Interface

```
Create src/purveyor/core/auth.py

1. Define the AuthProvider protocol:
   - async get_api_key(request_context: dict) -> str
   - async validate_request(request_context: dict) -> UserContext

2. Define UserContext:
   - api_key: str
   - user_id: str | None
   - email: str | None

3. Implement LocalFileAuthProvider:
   - Reads API key from config.json (via Settings)
   - Always returns the same key
   - validate_request calls whoami to get user info (cached)

4. Implement CloudHeaderAuthProvider:
   - Extracts X-Skyfi-Api-Key from request headers
   - Each request may have a different key (multi-tenant)
   - validate_request calls whoami per-key (cached)

5. Create get_auth_provider(settings) factory

Write tests in tests/test_auth.py:
- Test LocalFileAuthProvider returns configured key
- Test CloudHeaderAuthProvider extracts from headers
- Test missing header raises appropriate error

Acceptance: Both auth providers work and return UserContext.
```

---

## Phase 2 — Core MCP Tools (Read Operations)

**Goal:** Stand up the MCP server and implement all read-only tools.

### Task 2.1: MCP Server Setup

```
Create src/purveyor/server.py

1. Initialize the MCP server using the `mcp` Python SDK:
   - Server name: "purveyor"
   - Server version: from __version__
   - Capabilities: tools (listChanged=True), resources (subscribe=True, listChanged=True)

2. Set up Streamable HTTP transport:
   - Single endpoint at configurable path (default: /mcp)
   - Handle initialize, tools/list, tools/call, resources/list, resources/read
   - Session management via Mcp-Session-Id header

3. Create the FastAPI application in src/purveyor/app.py:
   - Mount the MCP server at /mcp
   - Add /health endpoint (returns DB status, SkyFi API reachability)
   - Add webhook routes (stubs for now)
   - CORS middleware for browser-based MCP clients
   - Lifespan handler for startup/shutdown (init DB, cache, etc.)

4. Create the CLI in src/purveyor/cli.py:
   - `purveyor serve` — run the server
     - --local flag (sets local_mode=True, uses SQLite)
     - --reload flag (uvicorn reload for dev)
     - --host / --port flags
   - `purveyor demo` — run the demo agent (stub for now)

5. Wire up dependencies:
   - On startup: load settings, setup logging, init DB, create SkyFi client,
     create cached client, create auth provider
   - Make these available to tool handlers via the MCP server context

Write tests in tests/test_server.py:
- Test /health endpoint returns 200
- Test MCP initialize handshake
- Test tools/list returns registered tools

Acceptance: Server starts, /health works, MCP initialize returns capabilities.
```

### Task 2.2: Geospatial Tools

```
Create src/purveyor/tools/geospatial.py

Implement these MCP tools (see SPEC.md §3.2.6):

1. geocode_location:
   - Uses geopy.geocoders.Nominatim for place name → coordinates
   - Returns coordinates, bounding box, display name, and a suggested AOI polygon
   - For the AOI polygon: if the result has a bounding box, use it;
     otherwise create a small square AOI around the point
   - Cache results for 1 hour
   - Respect Nominatim usage policy (user-agent, 1 req/sec)

2. create_aoi_from_point:
   - Takes lat, lon, area_sq_km
   - Uses pyproj for accurate projection
   - Creates a square polygon centered on the point with the desired area
   - Returns WKT POLYGON and actual computed area

3. calculate_aoi_area:
   - Takes WKT polygon string
   - Uses Shapely for parsing and pyproj for area calculation
   - Returns area in sq km, vertex count, validity check
   - Validates against SkyFi limits: max 500 vertices, max 500k sq km for searches

4. Internal helper: resolve_location(location: str) -> str:
   - If the input looks like WKT (starts with POLYGON), return as-is
   - Otherwise, geocode it and return a WKT polygon
   - This helper is used by other tools to accept either format

Write tests in tests/test_geospatial.py:
- Test geocoding a known place name
- Test AOI creation from a point (verify area is close to requested)
- Test area calculation for known polygons
- Test WKT validation (too many vertices, too large area)
- Hypothesis tests for coordinate round-trips

Acceptance: All three tools registered and working. resolve_location helper works.
```

### Task 2.3: Archive Search Tool

```
Create src/purveyor/tools/archives.py

Implement these MCP tools (see SPEC.md §3.2.1):

1. search_archives:
   - Accept location as place name or WKT (use resolve_location helper)
   - Map tool input parameters to GetArchivesRequest
   - Handle pagination via next_page parameter
   - Return structured results with a human-readable summary
   - Summary should include: total results, date range covered,
     resolution range, price range, and a suggestion for next steps
   - Include tool annotations: readOnlyHint=true, idempotentHint=true

2. get_archive_details:
   - Simple pass-through to SkyFi client
   - Return full archive metadata with human-readable summary
   - Annotations: readOnlyHint=true, idempotentHint=true

Write tests in tests/test_archives_tool.py:
- Test search with place name (mocked geocoding + mocked SkyFi API)
- Test search with WKT polygon
- Test pagination with next_page
- Test summary generation
- Test error handling (invalid AOI, no results)

Acceptance: Both tools registered, working with cached SkyFi client.
```

### Task 2.4: Pricing Tool

```
Create src/purveyor/tools/pricing.py

Implement get_pricing tool (see SPEC.md §3.2.2):

1. Accept optional AOI (place name or WKT), product_type filter, resolution filter
2. Call SkyFi pricing endpoint
3. If product_type or resolution filters are provided, filter the response
4. Generate a human-readable pricing summary that:
   - Groups by product type
   - Shows price per sq km for each resolution/provider combo
   - If AOI is provided, shows estimated total cost for that area
5. Cache with 5-minute TTL
6. Annotations: readOnlyHint=true, idempotentHint=true

Write tests in tests/test_pricing_tool.py:
- Test pricing with no filters
- Test pricing with AOI (cost estimate included)
- Test filtering by product type
- Test caching behavior

Acceptance: Pricing tool registered, returns clear pricing breakdowns.
```

### Task 2.5: Feasibility and Pass Prediction Tools

```
Create src/purveyor/tools/feasibility.py

Implement (see SPEC.md §3.2.3):

1. check_feasibility:
   - Resolve location to WKT
   - Create a feasibility task via SkyFi API
   - Poll get_feasibility_status every 2 seconds until status is COMPLETE or ERROR
   - Timeout after 60 seconds
   - Return scores and opportunities with a human-readable assessment:
     "Feasibility is HIGH (0.85). Weather conditions are favorable.
      PLANET has 3 available passes. Best opportunity: Jan 20 at 14:30 UTC."
   - Cache results for 2 minutes
   - Annotations: readOnlyHint=true

2. get_pass_predictions:
   - Resolve location to WKT
   - Call pass prediction endpoint
   - Return passes sorted by date
   - Include human-readable summary with best options highlighted
   - Annotations: readOnlyHint=true, idempotentHint=true

Write tests in tests/test_feasibility_tool.py:
- Test feasibility check with successful completion
- Test feasibility polling timeout
- Test pass predictions
- Test human-readable summary generation

Acceptance: Both tools registered, feasibility polling works, summaries are clear.
```

### Task 2.6: Order Management Tools (Read-Only)

```
Create src/purveyor/tools/orders.py (read operations only — write ops in Phase 3)

Implement (see SPEC.md §3.2.4, read-only subset):

1. list_orders:
   - Support filtering by order type, pagination, sorting
   - Return order summaries with status, cost, creation date
   - Human-readable summary: "You have 15 orders. 3 are pending delivery.
     Most recent: archive order for Port of LA, delivered Jan 15."
   - Annotations: readOnlyHint=true

2. get_order_status:
   - Return full order details with status history timeline
   - Include download URLs for completed orders
   - Human-readable status narrative
   - Annotations: readOnlyHint=true

3. download_deliverable:
   - Return the signed download URL for the requested deliverable type
   - Validate the deliverable type (image, payload, cog)
   - Annotations: readOnlyHint=true

Write tests in tests/test_orders_tool.py:
- Test list_orders with various filters
- Test get_order_status with complete and in-progress orders
- Test download_deliverable URL generation

Acceptance: All three read-only order tools working.
```

### Task 2.7: Account and Resources

```
Create src/purveyor/tools/account.py and src/purveyor/resources/skyfi_resources.py

1. Account tool — whoami:
   - Returns user info, budget usage, payment status
   - Human-readable: "You're logged in as jane@acme.com. Budget: $450 of $1000 used.
     Payment method: active."
   - Cached for 5 minutes
   - Annotations: readOnlyHint=true

2. MCP Resources:
   - skyfi://pricing/current — Returns cached pricing matrix
   - skyfi://orders/recent — Returns last 10 orders
   - skyfi://account/info — Returns whoami info
   - skyfi://providers/list — Returns list of available providers
   - skyfi://resolutions/list — Returns list of supported resolutions

Write tests in tests/test_account_tool.py and tests/test_resources.py

Acceptance: whoami tool and all resources registered and returning data.
```

---

## Phase 3 — Order Placement and Webhooks

**Goal:** Implement the order creation flow with human-in-the-loop confirmation, and the webhook receiver.

### Task 3.1: Order Confirmation Flow

```
Create src/purveyor/core/confirmation.py

1. Confirmation token management:
   - generate_confirmation_token() -> str (cryptographically random, URL-safe)
   - Store token in OrderConfirmation table with:
     - The full order request payload
     - Estimated cost
     - Status: pending
     - Expiry: 30 minutes from creation
   - Look up token: get_confirmation(token) -> OrderConfirmation | None
   - Confirm: confirm_order(token) -> OrderInfo (places the actual order)
   - Expire: cleanup job for expired confirmations

2. Confirmation page (FastAPI route):
   - GET /confirm/{token} — Renders a simple HTML page showing:
     - Order type (tasking/archive)
     - AOI description
     - Product type and resolution
     - Estimated cost
     - Confirm / Cancel buttons
   - POST /confirm/{token} — Processes confirmation:
     - Validates token exists and is not expired
     - Places the order via SkyFi API
     - Updates OrderConfirmation status to "placed"
     - Stores the SkyFi order ID
     - Returns success page with order ID

3. Add routes to the FastAPI app at /confirm/{token}

Write tests in tests/test_confirmation.py:
- Test token generation and storage
- Test confirmation page renders with order details
- Test successful confirmation places order
- Test expired token returns error
- Test already-confirmed token returns error

Acceptance: Full confirmation flow works end-to-end with test database.
```

### Task 3.2: Order Creation Tools

```
Add to src/purveyor/tools/orders.py (write operations):

1. create_tasking_order:
   - Validate all inputs (AOI, dates, product type, resolution, delivery params)
   - Calculate estimated cost using pricing endpoint
   - Create an OrderConfirmation record with the request payload
   - Return:
     - confirmation_url pointing to /confirm/{token}
     - estimated_cost in cents
     - order_summary: human-readable description of what will be ordered
     - Explicit instruction: "Please ask the user to review and confirm
       at the provided URL before the order is placed."
   - Annotations: destructiveHint=true, readOnlyHint=false

2. create_archive_order:
   - Same flow as tasking but with archive-specific parameters
   - Validate archive_id exists (call get_archive first)
   - Include archive metadata in the confirmation page
   - Annotations: destructiveHint=true, readOnlyHint=false

3. request_redelivery:
   - Pass through to SkyFi API
   - Annotations: destructiveHint=false, readOnlyHint=false

Write tests in tests/test_order_creation.py:
- Test tasking order creates confirmation and returns URL
- Test archive order creates confirmation and returns URL
- Test full flow: create → confirm → order placed
- Test invalid inputs return clear errors
- Test redelivery works

Acceptance: Order creation tools return confirmation URLs. Confirmation places real orders.
```

### Task 3.3: Webhook Receiver

```
Create src/purveyor/webhooks/receiver.py

1. FastAPI routes:
   - POST /webhooks/order-event
     - Parse OrderInfoWithEvent payload
     - Log the event
     - Store in WebhookEvent table
     - If the event relates to a pending OrderConfirmation, update its status
     - TODO (Phase 4): Push notification to connected MCP client via SSE
   - POST /webhooks/archive-notification
     - Parse ArchiveResponse payload
     - Log the event
     - Store in WebhookEvent table
     - TODO (Phase 4): Push notification to connected MCP client via SSE

2. Webhook security:
   - Rate limit: 100 requests/minute per source IP
   - Idempotency: check webhook_events table for duplicate event IDs
   - Input validation via Pydantic

3. Mount webhook routes in the FastAPI app at /webhooks/*

Write tests in tests/test_webhooks.py:
- Test order event webhook receives and stores events
- Test archive notification webhook receives and stores events
- Test duplicate event is rejected (idempotency)
- Test invalid payload returns 422

Acceptance: Webhook endpoints receive and store events from SkyFi.
```

### Task 3.4: Notification Tools

```
Create src/purveyor/tools/notifications.py

Implement (see SPEC.md §3.2.5):

1. setup_monitoring:
   - Resolve location to WKT
   - Construct the webhook URL pointing to Purveyor's webhook receiver
   - Create notification via SkyFi API
   - Return notification ID and summary
   - Annotations: readOnlyHint=false, destructiveHint=false

2. list_notifications:
   - Paginated list of active monitors
   - Human-readable summary of each

3. get_notification_history:
   - Return notification with event history
   - Summary of how many events have fired

4. delete_notification:
   - Delete via SkyFi API
   - Annotations: destructiveHint=true

Write tests in tests/test_notifications_tool.py:
- Test creating a notification
- Test listing notifications
- Test viewing history
- Test deletion

Acceptance: All notification tools working.
```

### Task 3.5: Background Task Infrastructure

```
Create src/purveyor/core/tasks.py

1. Background task runner using FastAPI background tasks:
   - run_background_task(task_type, payload, handler_fn)
   - Creates a BackgroundTask record in DB (status=pending)
   - Runs the handler_fn asynchronously
   - Updates status to running, then completed or failed
   - Logs results and errors

2. Startup recovery sweep:
   - On server startup, query BackgroundTask where status in (pending, running)
   - Re-queue them for execution
   - Log how many orphaned tasks were recovered

3. Task types to support:
   - poll_feasibility: poll a feasibility task until completion
   - poll_order_confirmation: check if a pending confirmation has been confirmed
     (with timeout)

4. Use asyncio.to_thread for CPU-bound Shapely operations

Write tests in tests/test_tasks.py:
- Test task creation and completion tracking
- Test startup recovery finds orphaned tasks
- Test failed task records error

Acceptance: Background tasks run, are tracked, and recovered on restart.
```

---

## Phase 4 — Rate Limiting, Observability, and Hardening

**Goal:** Add inbound rate limiting, Sentry integration, and comprehensive test coverage.

### Task 4.1: Inbound Rate Limiting

```
Create src/purveyor/core/rate_limiter.py

1. Define RateLimiter protocol:
   - async check_rate_limit(key: str, limit: int, window_seconds: int) -> bool
   - Returns True if allowed, False if rate limited

2. Implement MemoryRateLimiter:
   - Sliding window counter using dict + deque of timestamps
   - Cleanup expired entries periodically

3. Implement RedisRateLimiter:
   - Redis sorted set sliding window
   - Falls back to MemoryRateLimiter if Redis unavailable

4. Add rate limiting middleware to FastAPI:
   - Extract rate limit key from API key or IP
   - Apply limits per SPEC.md §6.1:
     - Read operations: 60/min
     - Write operations: 10/min
     - Order confirmations: 5/hour
   - Return 429 with Retry-After header when limited

5. Add rate limit headers to responses:
   - X-RateLimit-Limit
   - X-RateLimit-Remaining
   - X-RateLimit-Reset

Write tests in tests/test_rate_limiter.py:
- Test allowing requests under limit
- Test blocking requests over limit
- Test sliding window behavior
- Test 429 response with Retry-After header

Acceptance: Rate limiting active on all endpoints.
```

### Task 4.2: Error Tracking and Health

```
Update src/purveyor/app.py:

1. Sentry integration:
   - Initialize Sentry SDK with DSN from settings
   - Capture unhandled exceptions
   - Capture SkyFi API errors (4xx and 5xx)
   - Add user context (api_key hash) to Sentry events
   - Exclude 429s and expected errors from Sentry

2. Enhanced /health endpoint:
   - Check database connectivity
   - Check SkyFi API reachability (ping endpoint)
   - Check Redis connectivity (if configured)
   - Return structured health response:
     { "status": "healthy", "database": "ok", "skyfi_api": "ok", "redis": "ok|skipped" }
   - Return 503 if any critical component is down

3. /ready endpoint for Kubernetes readiness probes:
   - Returns 200 only when the server is fully initialized

Write tests in tests/test_health.py:
- Test healthy status with all components up
- Test degraded status when SkyFi API is unreachable
- Test 503 when database is down

Acceptance: Sentry captures errors. Health endpoint reflects real system state.
```

### Task 4.3: Comprehensive Test Suite

```
Expand test coverage across all modules:

1. Integration tests (using testcontainers for Postgres+PostGIS):
   - Full MCP tool call flow: initialize → tools/list → tools/call
   - Order creation → confirmation → webhook receipt
   - Cache behavior across tool calls

2. Property-based tests (hypothesis):
   - tests/test_geospatial_properties.py:
     - Arbitrary WKT polygons: validate → calculate area → verify positive
     - create_aoi_from_point: for any valid lat/lon/area, result is a valid polygon
       with area close to requested
     - Coordinate round-trips through projections maintain accuracy
   - tests/test_cache_properties.py:
     - Cache key generation: distinct inputs produce distinct keys
     - TTL: entries expire after their TTL

3. Edge case tests:
   - AOIs crossing the antimeridian
   - AOIs near the poles
   - Empty search results
   - SkyFi API returning unexpected status codes
   - Malformed webhook payloads
   - Unicode in place names

4. Run full test suite and verify:
   - `uv run pytest --cov=src/purveyor --cov-report=term-missing`
   - Target: >80% line coverage

Acceptance: Test suite passes, coverage >80%.
```

---

## Phase 5 — Demo Agent and Documentation

**Goal:** Build the demo agent and write all integration documentation.

### Task 5.1: Demo Agent

```
Create src/purveyor/demo/agent.py

1. A thin Claude API wrapper using the Anthropic SDK:
   - Connects to Purveyor as an MCP client
   - Presents an interactive CLI chat interface
   - Sends user messages to Claude with Purveyor tools available
   - Streams Claude's responses to the terminal
   - Handles tool calls by forwarding to Purveyor

2. Pre-built workflow mode:
   - --workflow research: "Find recent high-resolution imagery of [query],
     check feasibility for a new capture, compare pricing options,
     and recommend the best approach."
   - --workflow monitor: "Set up monitoring for [location] and explain
     what will happen when new imagery is available."
   - --workflow order: "Walk me through ordering an archive image of [location]."

3. CLI entry point:
   - `purveyor demo --provider anthropic`
   - `purveyor demo --workflow research --query "deforestation near Manaus"`
   - Requires ANTHROPIC_API_KEY environment variable

Write tests in tests/test_demo_agent.py:
- Test agent initialization
- Test tool call routing (mocked)

Acceptance: Demo agent runs interactively and can execute all three workflows.
```

### Task 5.2: Integration Documentation

```
Create integration guides in docs/integrations/:

1. docs/integrations/claude-web.md
   - Step-by-step: Settings → Integrations → Add Custom MCP
   - Screenshot descriptions of each step
   - Example conversations
   - Troubleshooting common issues

2. docs/integrations/claude-code.md
   - `claude mcp add purveyor <url>`
   - Using tools in Claude Code sessions

3. docs/integrations/openai.md
   - Using OpenAI's remote MCP support
   - Configuration in the API request
   - Example code snippet

4. docs/integrations/anthropic-api.md
   - Using Anthropic's MCP support in the API
   - Example with the Python SDK

5. docs/integrations/gemini.md
   - Using Gemini's function calling with MCP
   - Example configuration

6. docs/integrations/langchain.md
   - LangChain/LangGraph MCP tools integration
   - Example agent setup code

7. docs/integrations/adk.md
   - Google ADK MCP tools integration
   - Example agent configuration

8. docs/integrations/ai-sdk.md
   - Vercel AI SDK MCP tools integration
   - Example Next.js code

Each guide should include:
- Prerequisites
- Step-by-step setup
- Example conversation or code
- Troubleshooting section

Acceptance: All 8 integration guides written with working examples.
```

### Task 5.3: CI/CD Pipeline

```
Create .github/workflows/ci.yml

1. Trigger on: push to main, pull requests

2. Jobs:
   - lint:
     - Run ruff check src/ tests/
     - Run ruff format --check src/ tests/
   - typecheck:
     - Run mypy src/
   - test:
     - Matrix: Python 3.11, 3.12
     - Run pytest with coverage
     - Upload coverage report
   - build:
     - Build Docker image
     - Run health check against the built image
   - docs:
     - Verify all docs/ files are valid markdown

3. Create .github/workflows/release.yml:
   - Trigger on: tag push (v*)
   - Build and push Docker image to ghcr.io
   - Create GitHub release with changelog

Acceptance: CI pipeline runs on push, all checks pass.
```

### Task 5.4: IaC Templates

```
Create Terraform modules in deploy/terraform/:

1. deploy/terraform/aws/:
   - ECS Fargate service with the Purveyor Docker image
   - RDS Postgres with PostGIS
   - ElastiCache Redis (optional, controlled by variable)
   - ALB with HTTPS (ACM certificate)
   - Security groups, IAM roles, VPC (or use existing)
   - Variables: domain, image_tag, db_instance_class, etc.
   - Outputs: service URL, RDS endpoint

2. deploy/terraform/gcp/:
   - Cloud Run service
   - Cloud SQL Postgres with PostGIS
   - Memorystore Redis (optional)
   - Cloud Load Balancing with managed SSL
   - Variables: project_id, region, domain, image_tag
   - Outputs: service URL, Cloud SQL connection

Both modules should:
- Use sensible defaults
- Include a terraform.tfvars.example
- Be documented in a local README.md

Acceptance: `terraform plan` succeeds for both modules (no apply needed).
```

### Task 5.5: Final Polish

```
Final tasks before open source release:

1. Update README.md:
   - Verify all instructions work end-to-end
   - Add badges (CI status, Python version, license)
   - Add a "Quick Demo" GIF or screenshot description

2. Create CONTRIBUTING.md:
   - Development setup instructions
   - Code style guide (ruff, mypy)
   - PR process
   - Issue templates

3. Create LICENSE (MIT)

4. Create CHANGELOG.md with initial release notes

5. Create .github/ISSUE_TEMPLATE/ with bug report and feature request templates

6. Review and update all docstrings in src/

7. Run full test suite one final time:
   - uv run pytest --cov=src/purveyor
   - uv run mypy src/
   - uv run ruff check src/

Acceptance: Repository is clean, documented, tested, and ready for public release.
```

---

## Dependency Summary

| Phase | Depends On | Deliverables |
|-------|-----------|-------------|
| Phase 0 | Nothing | Project skeleton, tooling, Docker |
| Phase 1 | Phase 0 | SkyFi client, cache, auth |
| Phase 2 | Phase 1 | MCP server, all read-only tools |
| Phase 3 | Phase 2 | Order creation, webhooks, notifications |
| Phase 4 | Phase 3 | Rate limiting, Sentry, test suite |
| Phase 5 | Phase 4 | Demo agent, docs, CI/CD, IaC |

## Estimated Effort

| Phase | Tasks | Estimated Effort |
|-------|-------|-----------------|
| Phase 0 | 5 tasks | 1–2 days |
| Phase 1 | 3 tasks | 2–3 days |
| Phase 2 | 7 tasks | 3–4 days |
| Phase 3 | 5 tasks | 3–4 days |
| Phase 4 | 3 tasks | 2–3 days |
| Phase 5 | 5 tasks | 3–4 days |
| **Total** | **28 tasks** | **14–20 days** |
