# Security Rules

## Secrets Management

- **Never hardcode API keys, tokens, credentials, or database URLs.** All secrets come from environment variables.
- Load secrets via `.env` file locally (gitignored). In Docker, use `env_file` in docker-compose.yml.
- Required env vars (cloud mode): `SKYFI_API_KEY`, `CONFIRMATION_SECRET_KEY`, `DATABASE_URL`.
- Optional env vars: `REDIS_URL`, `SENTRY_DSN`, `GEOCODING_BASE_URL`, `WEBHOOK_BASE_URL`.
- In local mode, `CONFIRMATION_SECRET_KEY` is auto-generated ephemerally. In cloud mode (`local_mode=False`), fail fast without it.
- Never log secret values. Log only that a variable "is set" or "is missing".
- `CONFIRMATION_SECRET_KEY` must be consistent across all instances in multi-instance deployments.
- If `CONFIRMATION_SECRET_KEY` changes (key rotation), all pending confirmation tokens (up to 30 min old) become invalid. Document this in ops docs.

## .gitignore

The following must always be gitignored:
```
.env
.env.*
*.pem
*.key
config.json
purveyor.db
__pycache__/
.mypy_cache/
.pytest_cache/
.ruff_cache/
dist/
build/
*.egg-info/
.venv/
node_modules/
```

## Credential Handling (Critical)

Purveyor handles two types of sensitive credentials:

### SkyFi API Keys
- **Cloud mode:** Arrive in `X-Skyfi-Api-Key` request headers. Never stored server-side in any database or file (NF-08).
- **Local mode:** Read from `config.json` on disk. File should have 600 permissions.
- **Confirmation tokens:** API key is Fernet-encrypted into the URL token. Decrypted in-memory only at confirmation time. The token IS the credential carrier.
- **Logging:** Never log API keys. Hash them (`api_key_hash`) for correlation in logs and database records.

### Cloud Storage Delivery Credentials
- S3 (access key, secret key), GCS (service account JSON), Azure (connection string, client secret) credentials are passed through from the user to SkyFi.
- Purveyor holds these in-memory during the confirmation token lifecycle only.
- **Never log delivery credentials.** Apply a structlog filter that redacts any field matching: `delivery_params`, `aws_secret_key`, `aws_access_key`, `gs_credentials`, `azure_connection_string`, `azure_client_secret`.
- Delivery credentials live inside the Fernet-encrypted confirmation token alongside the API key — never in the database.

## Confirmation Token Security

- Tokens use **Fernet encryption** (AES-128-CBC + HMAC-SHA256) from Python's `cryptography` library.
- Token payload: API key + order parameters + expiry timestamp.
- 30-minute TTL enforced by Fernet's built-in `ttl` parameter on `decrypt()`.
- Tokens are single-use — enforced by `order_confirmations.status` with `SELECT FOR UPDATE SKIP LOCKED`.
- Database stores only a SHA-256 hash of the token, never the token itself.
- URL tokens are URL-safe base64 (Fernet's native output format).
- The `CONFIRMATION_SECRET_KEY` is a symmetric Fernet key. Generate with: `purveyor generate-key`.

## Webhook Security

Until SkyFi implements webhook signatures, Purveyor uses defense in depth:

1. **Shared secret in URL:** Register webhooks with `?token=<random>` query param. Validate on every inbound request.
2. **Verification calls:** Never trust webhook payloads to update state. Always verify against SkyFi's API (`GET /orders/{id}`, `GET /archives/{id}`) before updating local records or notifying agents.
3. **Rate limiting:** 100 requests/minute per source IP on webhook endpoints.
4. **Idempotency:** Deduplicate by checking `webhook_events` table before processing.
5. **Logging discrepancies:** If webhook claims a state that SkyFi API contradicts, log the discrepancy for the operator.

## API Input Validation

- All tool inputs validated via Pydantic with strict schemas.
- **WKT polygons:** Validate max 500 vertices, max 500k sq km area, convexity for searches. For oversized AOIs, clip and warn rather than error.
- **Dates:** Must be timezone-aware ISO 8601 UTC datetimes.
- **Enums:** Validate against SkyFi's exact enum values (including spaces like `"VERY HIGH"`).
- **Delivery params:** When a driver is specified, validate with typed per-driver Pydantic schemas (S3DeliveryParams, GCSDeliveryParams, AzureDeliveryParams). When driver is `NONE`, skip validation.
- Never pass raw user input directly into SQL queries. Use SQLAlchemy parameterized queries exclusively.

## Rate Limiting

- **Inbound (protecting Purveyor):**
  - Read operations: 60/min per API key
  - Write operations: 10/min per API key
  - Order confirmations: 5/hour per API key
  - Webhook endpoints: 100/min per source IP
- **Outbound (respecting external services):**
  - SkyFi API: tenacity with exponential backoff + jitter (max 3 retries)
  - Nominatim: 1 req/sec global semaphore
  - Overpass API: cache results for 1 hour

## CORS

- Default: `*` (allow all origins). The API key in headers is the actual auth boundary, not the browser origin.
- Configurable via `ALLOWED_ORIGINS` env var (comma-separated).
- The `/confirm/{token}` page is opened directly by users — same CORS policy applies.
- Rationale: CORS protects against CSRF with ambient credentials (cookies). Purveyor uses explicit API key headers which browsers don't attach automatically.

## Authentication

- **Local mode:** API key from `config.json`. Single-user, no multi-tenancy.
- **Cloud mode:** `X-Skyfi-Api-Key` from request headers. Each MCP session authenticates independently. Server stores no credentials.
- Auth middleware validates the key by calling SkyFi's `whoami` endpoint (cached 5 min).
- Anonymous requests are rejected with 401.

## Multi-Instance Safety

- Background task claiming uses `SELECT FOR UPDATE SKIP LOCKED` in Postgres — prevents duplicate execution across instances.
- SQLite deployments are single-instance by definition (no row locking needed).
- Runtime check: if database is SQLite, use simple SELECT; if Postgres, use SKIP LOCKED.
- Confirmation tokens are encrypted with a shared key (`CONFIRMATION_SECRET_KEY`) — any instance can decrypt.

## Dependencies

- Pin Python dependencies via `uv.lock` (committed to git).
- Pin skills via `skills-lock.json` (committed to git).
- Key dependencies and their purposes:
  - `mcp` — MCP Python SDK (server, transport, types)
  - `fastapi` + `uvicorn` — HTTP server for webhooks and confirmation pages
  - `httpx` — Async HTTP client for SkyFi API and OSM
  - `sqlalchemy[asyncio]` — Async ORM + Alembic migrations
  - `cryptography` — Fernet encryption for confirmation tokens
  - `shapely` + `pyproj` + `geopy` — Geospatial operations
  - `pydantic` — Data validation and settings
  - `structlog` — Structured logging
  - `tenacity` — Retry logic with backoff
  - `cachetools` — In-memory TTL caching
  - `sentry-sdk` — Error tracking
- Before adding a new dependency, check if an existing dep covers the need. Keep the dependency tree minimal.

## Docker Security

- Don't run as root in the container. Use a non-root user in the Dockerfile.
- Don't expose Postgres or Redis ports to the host unless needed for local development.
- Use specific image tags (e.g., `python:3.11-slim`), not `latest`.
- Don't copy `.env` or `config.json` files into the Docker image.
- Multi-stage build: build stage installs deps, runtime stage copies only what's needed.

## Error Responses

- Never expose stack traces, internal error details, or SQL errors to MCP clients.
- Business errors: `isError=true` with structured `{code, message, detail}` in content.
- Infrastructure errors: JSON-RPC error codes (-32603 for internal, -32601 for method not found).
- Log the full error internally with request context. Return only the safe code and message to the client.
