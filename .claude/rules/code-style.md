# Code Style Rules

## Python (Backend)

### General
- Python 3.11+ features are fine (StrEnum, ExceptionGroup, tomllib, etc.)
- All public functions and classes get docstrings. Skip for obvious private helpers.
- Use type hints everywhere — mypy strict mode is enforced.
- Prefer `async def` for all I/O-bound operations. Use `asyncio.to_thread` for CPU-bound work (Shapely geometry operations).
- Prefer returning explicit error types or None over raising exceptions for expected business conditions.

### Formatting
- `ruff format` is the standard. No debate. Line length: 100.
- Imports: stdlib → third-party → local, separated by blank lines.
- Use `from __future__ import annotations` at the top of every module for PEP 604 union syntax.

### Naming
- `snake_case` for functions, variables, module names.
- `PascalCase` for classes, type aliases, Pydantic models, enums.
- `UPPER_SNAKE_CASE` for constants and environment variable names.
- Prefix abstract classes/protocols with the behavior they describe (e.g., `AuthProvider`, `CacheBackend`), not `I` or `Abstract`.
- Pydantic model names match their purpose: `GetArchivesRequest`, `TaskingOrderResponse`, `ArchiveResponse`.

### Error Handling
- Always wrap errors with context: raise from the original exception with `from err`.
- Use structured error codes for business errors (see CLAUDE.md error codes section).
- Never swallow errors silently. If you don't raise it, log it with context.
- SkyFi API errors: 4xx → business error (isError in content), 5xx → check if retryable, then business error with `skyfi_unavailable` code.

### Pydantic Conventions
- All SkyFi API response models: `model_config = ConfigDict(extra="ignore")` — never strict.
- All SkyFi API request models: strict validation, explicit field types.
- Use `Field(description="...")` on tool input schemas — these become the tool descriptions agents read.
- Enum values match SkyFi's API exactly (e.g., `"VERY HIGH"` with space, not `"VERY_HIGH"`).

### FastAPI Conventions
- Route handlers are thin — extract request, call service, return response. No business logic in handlers.
- Use dependency injection (`Depends`) for auth, database sessions, config, and cached SkyFi client.
- Use lifespan context manager for startup/shutdown (init DB, create clients, start background tasks).
- Return proper HTTP status codes: 400 for bad input, 404 for not found, 409 for state conflicts, 422 for validation errors, 429 for rate limited, 500 for internal errors.
- CORS: defaults to `*` (API key headers are the auth boundary, not origin).

### MCP Tool Conventions
- Every tool returns both structured data AND a factual summary string.
- Summaries are agent-facing briefings: dense, factual, no first-person voice, no suggestions.
- Include tool annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`.
- Order-creating tools MUST include `destructiveHint=True` and return a confirmation URL, never place orders directly.
- Use `resolve_location()` helper in any tool that accepts a location — transparently handles place names or WKT.
- Geospatial tools that exceed SkyFi limits (500k sq km AOI) should clip and warn, not error.

### Async Patterns
- Use `httpx.AsyncClient` for all HTTP calls (SkyFi API, Nominatim, Overpass).
- Use `tenacity` for retry logic on SkyFi API calls (retry on 429, 5xx; exponential backoff with jitter).
- Use `asyncio.Lock` for in-memory cache writes and rate limiter updates.
- Use `asyncio.Semaphore(1)` for global Nominatim rate limiting (1 req/sec).
- Use `asyncio.to_thread` for CPU-bound Shapely operations (area calculation, polygon validation).
- FastAPI background tasks for fire-and-forget work; Postgres state machine is the source of truth.

### Logging
- `structlog` with JSON output in production, colored console in dev.
- Log all SkyFi API calls: method, path, status code, duration.
- Log all MCP tool invocations: tool name, key parameters (not full payloads).
- Log all webhook events: event type, order/notification ID.
- **Never log:** API keys, delivery credentials, confirmation token contents, full delivery_params.
- Redact fields matching: `api_key`, `secret_key`, `gs_credentials`, `azure_connection_string`, `aws_secret_key`.
- Use structured fields, not string interpolation: `log.info("order_placed", order_id=id, cost_cents=cost)`.

### Project-Specific
- **API keys never touch the database.** They live in Fernet-encrypted confirmation tokens or in-memory request context.
- **Webhooks are untrusted hints.** Always verify against SkyFi API before updating local state.
- **Confirmation tokens are single-use.** Enforce via `SELECT FOR UPDATE SKIP LOCKED` on confirmation status.
- **Background tasks must be idempotent.** If two instances both execute the same task, the result is the same.
- **SkyFi's API is the source of truth.** Purveyor caches for performance but never contradicts SkyFi on order state, pricing, or account info.
- **Delivery params are optional.** Default to `NONE` driver. When specified, validate with typed Pydantic schemas per driver.

## SQL (Migrations via Alembic)

- Use Alembic autogenerate for schema changes.
- Every table includes `created_at TIMESTAMPTZ DEFAULT NOW()`.
- Use `UUID` primary keys.
- Add indexes on columns used in WHERE clauses: `status`, `api_key_hash`, `notification_id`.
- PostGIS-specific operations get custom migration scripts (not autogenerated).
- Migrations must work for both SQLite and Postgres — use conditional logic where needed.
- `order_confirmations` table stores token hash and status only — never the payload or API key.
- `webhook_events` table has a `processed` boolean for reconnect delivery tracking.

## HTML (Confirmation Page)

- Single self-contained HTML file with inline CSS. No external dependencies, no JavaScript frameworks, no CDN.
- Clean, trustworthy appearance — users are approving real purchases on this page.
- Show: order type, location, product/resolution, estimated cost (prominently), confirm/cancel buttons, token expiry countdown.
- Both buttons are simple form POSTs — no JavaScript required.
- Include SkyFi logo (base64 SVG or static route).
- Accessible and readable on any device width.

## Testing

- Framework: `pytest` + `pytest-asyncio` + `respx` + `testcontainers` + `hypothesis`
- Use `respx` to mock all SkyFi HTTP calls in unit/integration tests.
- Use `testcontainers` for Postgres+PostGIS integration tests.
- Use `hypothesis` for property-based tests on geospatial logic.
- Live API tests behind `@pytest.mark.live` marker, gated on `SKYFI_TEST_API_KEY` env var.
- Test file naming: `test_<module>.py` in `tests/` directory.
- Use fixtures for common setup: `skyfi_client`, `cached_client`, `db_session`, `auth_provider`.
- Coverage target: >80% line coverage.
- Never create real orders or notifications in automated tests against the live SkyFi API.
- **After adding or fixing tests, always commit:** `test(<scope>): <description>` — do not leave test changes uncommitted.