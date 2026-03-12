# Session Log: Phase 0 — Project Scaffolding

**Date:** 2026-03-11, ~21:19
**Duration:** ~30 minutes
**Focus:** Verify and fix Phase 0 scaffolding (project structure, config, database, Docker)

## What Got Done

- Audited all existing Phase 0 files — the scaffold was largely pre-built and correct
- Ran full test suite: **43 tests passing** across `test_placeholder`, `test_config`, `test_database`, `test_logging`
- Ran `uv run mypy src/` — clean (no issues in 15 source files)
- Ran `uv run ruff check src/` — found 4 linting errors; fixed 3 automatically + 1 manually
- Ran `uv run alembic upgrade head` against SQLite — initial migration applies cleanly
- Validated `docker compose --profile minimal config` — YAML is valid
- Committed all Phase 0 files to `main` (34 files, 4105 insertions)

**Files committed:**
- `pyproject.toml` — all deps including `cryptography`, `aiosqlite`, `redis`, `jinja2`, `click`; mypy strict + ruff + pytest config
- `src/purveyor/__init__.py` — package with `__version__ = "0.1.0"`
- `src/purveyor/core/logging.py` — structlog JSON/console dual-mode, sensitive field redaction
- `src/purveyor/core/config.py` — Pydantic Settings for all env vars, ephemeral Fernet key in local mode, required in cloud mode
- `src/purveyor/models/base.py` — `DeclarativeBase`, `UUIDPrimaryKeyMixin`, `TimestampMixin`
- `src/purveyor/models/database.py` — async engine/session factory (SQLite + Postgres)
- `src/purveyor/models/tables.py` — `OrderConfirmation` (DESIGN_DECISIONS §2 schema), `WebhookEvent`, `BackgroundTask`, `NotificationRegistry`, `GeocodeCache`
- `alembic/env.py` — async Alembic env with `render_as_batch=True` for SQLite compat
- `alembic/versions/a96bf3d3af8d_initial_schema.py` — initial migration
- `deploy/docker/Dockerfile` — multi-stage build, non-root user, healthcheck
- `deploy/docker-compose.yml` — minimal/standard/full profiles
- `deploy/docker/Caddyfile` — HTTPS reverse proxy
- `config.example.json` — documented defaults
- `tests/test_config.py`, `tests/test_database.py`, `tests/test_logging.py`, `tests/test_placeholder.py`

## Issues & Troubleshooting

- **Problem:** `ruff check` reported 4 errors
  - **Cause 1:** Import block unsorted in `core/logging.py` (I001)
  - **Cause 2:** Unused `timezone` import in `models/base.py` (F401)
  - **Cause 3:** Unused `JSONB` import from `sqlalchemy.dialects.postgresql` in `models/tables.py` (F401)
  - **Cause 4:** `**kwargs: Any` in `models/database.py:create_engine()` triggers ANN401 (dynamically typed expressions disallowed in strict mode)
  - **Fix (1–3):** `uv run ruff check src/ --fix` auto-resolved the import sort and two unused imports
  - **Fix (4):** Manually refactored `create_engine()` to drop `**kwargs: Any` entirely. Replaced with explicit `echo: bool = False` parameter and inline branching for SQLite vs Postgres options. This is cleaner and mypy-safe.

## Decisions Made

- **Dropped `**kwargs: Any` from `create_engine()`** — the only callers needed `echo` at most; adding an explicit parameter instead of a generic kwargs bag is simpler, type-safe, and avoids the ANN401 violation. If new engine options are needed later, they can be added as explicit parameters.

- **Used DESIGN_DECISIONS §2 schema for `order_confirmations`**, not the original SPEC §5.1 schema — the SPEC schema stored `request_payload JSONB` and the raw API key. The DESIGN_DECISIONS version stores only `token_hash`, `api_key_hash`, `status`, `mcp_session_id`, and `skyfi_order_id`. This satisfies NF-08 (zero credentials stored server-side).

- **`render_as_batch=True` in Alembic** — required for SQLite, which does not support `ALTER TABLE` natively. Alembic's batch mode rewrites the full table to emulate it. This is set in both online and offline migration modes.

- **`model_config = SettingsConfigDict(extra="ignore")` in Settings** — allows the config file to contain unknown keys without crashing. Matches the lenient parsing policy used across all SkyFi response models.

## Current State

Phase 0 is fully complete and committed to `main`.

**Working:**
- All 43 tests pass
- mypy strict: 0 errors
- ruff: 0 errors
- `alembic upgrade head` on SQLite: success
- `docker compose --profile minimal config`: valid

**Database tables defined (SQLite-compatible, Alembic-managed):**
- `order_confirmations` — token hash, status, order type, api_key_hash, mcp_session_id, skyfi_order_id, estimated_cost_cents, timestamps
- `webhook_events` — event_type, payload (Text), api_key_hash, delivered (bool), event_id (for dedup)
- `background_tasks` — task_type, payload, status, result, timestamps, retry_count
- `notification_registry` — notification_id (PK) → api_key_hash mapping
- `geocode_cache` — place_name, display_name, lat/lon, raw_response, expires_at

**Stubs in place (not yet implemented):**
- `src/purveyor/server.py` — MCP server entry point stub
- `src/purveyor/app.py` — FastAPI application stub
- `src/purveyor/cli.py` — CLI entry point stub
- All `tools/`, `resources/`, `webhooks/`, `demo/` subdirectories have `__init__.py` only

## Next Steps

1. **Phase 1, Task 1.1** — Build `src/purveyor/core/skyfi_client.py` and `src/purveyor/core/skyfi_types.py`
   - Read `docs/openapi.json` via the `apidog` MCP server to get all endpoint schemas
   - Define Pydantic models for all SkyFi API types (`Archive`, `TaskingOrderRequest`, `FeasibilityResponse`, etc.)
   - Implement `SkyFiClient` with httpx + tenacity retry logic (retry on 429, 5xx; exponential backoff)
   - All response models must use `model_config = ConfigDict(extra="ignore")`
   - Write `tests/test_skyfi_client.py` using respx to mock all endpoints

2. **Phase 1, Task 1.2** — Tiered cache layer (`src/purveyor/core/cache.py`)
   - `CacheBackend` protocol, `MemoryCacheBackend` (cachetools TTLCache), `RedisCacheBackend`
   - `CachedSkyFiClient` wrapping `SkyFiClient` with TTLs per SPEC §5.3
   - Cache invalidation on order placement

3. **Phase 1, Task 1.3** — Auth provider (`src/purveyor/core/auth.py`)
   - `LocalFileAuthProvider` (reads from config.json)
   - `CloudHeaderAuthProvider` (extracts `X-Skyfi-Api-Key` from request headers)
