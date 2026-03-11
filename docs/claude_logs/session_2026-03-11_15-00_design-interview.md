# Session Log: Purveyor Design Interview & Decision Documentation

**Date:** 2026-03-11
**Duration:** ~90 minutes
**Focus:** Structured design interview to surface gaps, ambiguities, and unstated assumptions across all Purveyor docs, followed by writing DESIGN_DECISIONS.md

---

## What Got Done

- Read all four project documents in full: `SPEC.md`, `PRD.md`, `IMPLEMENTATION_PLAN.md`, `purveyor-architecture.mermaid`, and `README.md`
- Conducted a 26-question design interview spanning 10 topic areas
- Created `docs/DESIGN_DECISIONS.md` — a structured record of every question, answer, resulting decision, and downstream implications for the SPEC and IMPLEMENTATION_PLAN
- Created `docs/claude_logs/` directory
- Saved a persistent project memory entry summarizing key design deviations

---

## Issues & Troubleshooting

No technical troubleshooting occurred this session. This was a pure design/planning session.

---

## Decisions Made

### 1. Cloud Mode Order Confirmation — Encrypted Token (was: unresolved contradiction)
The SPEC said "zero credentials stored server-side" but the confirmation flow required using the API key after the MCP session ended. **Decision:** Fernet-encrypt the API key + order parameters into the URL token itself. No credentials in the DB. `CONFIRMATION_SECRET_KEY` env var required in cloud mode; auto-generated (ephemeral, logged warning) in local mode.

### 2. Order Confirmations DB Schema — Stripped Down
With the payload in the token, the `order_confirmations` table no longer needs `request_payload`. **Decision:** Store only `token_hash`, `status`, `order_type`, `api_key_hash`, `mcp_session_id`, `skyfi_order_id`, and timestamps. Adds `cancelled` as a new status value.

### 3. SSE Notification Reliability — Persist-First Pattern
MCP sessions disconnect before users confirm orders. **Decision:** Always write to `webhook_events` first. SSE push is opportunistic. On MCP `initialize`, query undelivered events by `api_key_hash` and push them, then mark delivered. `webhook_events` gains `api_key_hash` and `delivered` columns.

### 4. Webhook Ownership (Cloud Multi-Tenant)
SkyFi webhooks carry no Purveyor user identity. **Decision:** Order events are traced via `order_confirmations.api_key_hash`. Archive notification events are traced via a new `notification_registry` table (`notification_id` → `api_key_hash`), populated when `setup_monitoring` is called.

### 5. Confirmation URL Base URL — Layered Resolution
No BASE_URL config existed. **Decision:** Precedence: (1) `CONFIRMATION_BASE_URL` env var → (2) `X-Forwarded-Host` / `X-Forwarded-Proto` headers → (3) `http://localhost:{SERVER_PORT}`. Warn at startup if cloud mode and no config/headers yet available. Same `resolve_base_url()` helper used for monitoring webhook URLs.

### 6. Large AOI Geocoding — Clip with Warning
Geocoding "Russia" returns a bounding box far exceeding SkyFi's 500k sq km limit. **Decision:** Clip to a 500k sq km box centered on the OSM centroid/capital. Return search results but include a `location_note` field explaining the original area, clipped area, and center point used. Suggest refining the location.

### 7. Tool Error Format — Split by Error Type
No error taxonomy existed. **Decision:** Business/user errors → `isError=true` with structured `{code, message, detail}`. Infrastructure/protocol errors → JSON-RPC `-32603`. Defined error codes: `aoi_too_large`, `no_results`, `rate_limited`, `invalid_input`, `skyfi_api_error`, `skyfi_unavailable`, `order_expired`, `order_already_placed`, `open_data_limit_reached`, `feasibility_pending`.

### 8. `check_feasibility` — Dual-Mode, No Blocking Poll
The spec called for a 60-second blocking poll, which is poor UX. **Decision:** Dual-mode tool based on input. Create mode (with location params): create task, quick 2-3s initial poll; if ready return results, if not return `feasibility_id + status: "pending"` (not an error). Check mode (with `feasibility_id`): single poll, return whatever's available including partial provider scores.

### 9. Delivery Credentials — Default NONE, Typed Validation, Never Log
No delivery driver default or security guidance existed. **Decision:** `delivery_driver` defaults to `NONE` (SkyFi custody; user downloads via `download_deliverable`). When a driver is specified, validate with typed Pydantic models (`S3DeliveryParams`, etc.). Add a structlog processor that explicitly scrubs `delivery_params` and credential-like field names from all log output.

### 10. CORS Policy — Allow `*` by Default
No CORS policy was defined. **Decision:** Default `allow_origins=["*"]`. Auth boundary is the API key header, not origin. `ALLOWED_ORIGINS` env var overrides with a comma-separated list.

### 11. Demo Agent — stdio Transport In-Process
The spec described connecting to Purveyor as an MCP client but didn't specify how. **Decision:** `purveyor demo` spawns the MCP server as a subprocess over stdio pipes (same pattern as Claude Code's MCP integration). Single command, no ports, no network config. Demo sessions use in-memory SQLite. The MCP server supports both stdio and Streamable HTTP transports.

### 12. OSM Nominatim Rate Limiting — Cache + Semaphore + Configurable Base URL
No strategy existed for the 1 req/sec policy in multi-user cloud mode. **Decision:** Rely primarily on the 1-hour geocode cache. Add a global `asyncio.Semaphore(1)` as a safety net. Add `GEOCODING_BASE_URL` env var for operators who need to swap in a self-hosted Nominatim or Photon instance.

### 13. Background Task Recovery — `SELECT FOR UPDATE SKIP LOCKED` + Idempotency
Multi-instance cloud deployments would cause duplicate task execution on startup sweep. **Decision:** Postgres: `SELECT FOR UPDATE SKIP LOCKED` atomically claims tasks. SQLite (local/single-instance only): plain select. All task types designed to be idempotent as defense-in-depth.

### 14. Tool Summary Audience — Agent Briefing Notes
Summaries were undefined in terms of audience. **Decision:** Dense, factual briefing notes for the agent — not user-facing prose. Format: key stats, notable items, ranges/extremes. No first-person voice, no conversational filler. Full structured data is always returned alongside the summary.

### 15. V1 Scope — All P0 + P1 + P2
The P2 items (legacy SSE, order metadata, OAuth stub) are small enough to include. No deferral.

### 16. In-Memory Rate Limiter Memory Growth — Inline Pruning
Unbounded memory growth from many API keys was unaddressed. **Decision:** Prune stale timestamps inline on every `check_rate_limit` call. Periodic asyncio cleanup sweep every 5 minutes drops fully-idle keys.

### 17. Open Data Limits — SkyFi Enforces, Friendly Error
No tracking in Purveyor. **Decision:** Map SkyFi's limit error to `open_data_limit_reached` with a helpful message. Enrich `whoami` response with inferred account tier so the agent can proactively inform users.

### 18. SkyFi API Drift — Lenient Parsing + Weekly Schema Diff CI
**Decision:** Runtime: `extra='ignore'` + liberal `Optional` on all response models, structured warning logged for unexpected nulls. Detection: commit `docs/openapi.json`, weekly GitHub Actions workflow diffs against live SkyFi spec and auto-opens a tagged GitHub issue on meaningful changes.

### 19. Confirmation Page UX — Self-Contained Jinja2 Template
**Decision:** Single Jinja2 template with inline CSS, no CDN dependencies, no JavaScript. Shows: SkyFi logo (embedded), order details, cost with calculation breakdown, expiry countdown, Confirm/Cancel form POSTs. Post-confirm: success state with order ID and "your agent has been notified." Post-cancel: clean cancelled state.

### 20. Monitoring Webhook URL — Three-Behavior Logic + Localhost Warning
**Decision:** (1) User provides explicit `webhook_url` → use it directly. (2) No URL provided → use `resolve_base_url()` + `/webhooks/archive-notification`. (3) Resolved URL is localhost → create the monitor anyway, but add a `warning` field to the response explaining SkyFi can't reach it.

### 21. Priority Tasking Orders — Pass Through with Description
The `priority: boolean?` parameter was unexplained. **Decision:** Include in schema as `priority: bool = False` with description "Request priority scheduling. May result in higher cost." Pass to SkyFi. Confirmation page shows SkyFi's actual cost including any premium.

### 22. Estimated vs. Actual Cost Accuracy
**Decision:** Archive orders: high-confidence estimate from search result's `priceForOneSquareKm × aoi_area`, labeled "Estimated cost." Tasking orders: rougher estimate from pricing matrix, labeled "Estimated cost based on current pricing" with "may vary slightly" caveat. Show calculation breakdown. `get_order_status` shows actual charged amount after placement.

### 23. Order Cancellation from Agent — `cancel_pending_order` Tool (new)
No mechanism existed for agents to cancel pending orders without user visiting the URL. **Decision:** New tool `cancel_pending_order` sets status to `cancelled`, invalidates the token. Idempotent: already-expired or already-cancelled returns success no-op. Already-placed returns error. Annotation: `destructiveHint=false`.

### 24. Confirmation Token Encryption — Fernet
**Decision:** `cryptography.fernet.Fernet` — AES-128-CBC + HMAC-SHA256 + built-in TTL. Token is `Fernet(key).encrypt(json_bytes)`. Decryption with `ttl=1800` enforces 30-minute expiry automatically.

### 25. `CONFIRMATION_SECRET_KEY` Provisioning — Mode-Differentiated
**Decision:** Local mode: auto-generate ephemeral key at startup with info log warning. Cloud mode (`local_mode=False`): require env var, refuse to start without it. Add `purveyor generate-key` CLI subcommand that prints a fresh Fernet key.

### 26. Testing Strategy — Mocked Always, Live Behind Flag
**Decision:** `tests/` (respx mocked, runs every push), `tests/live/` (requires `--live` + `SKYFI_TEST_API_KEY`, read-only ops only, skipped gracefully if no key). Separate weekly GitHub Actions workflow for live tests using a stored secret. Open source contributors only need mocked tests.

---

## Current State

The project is **pre-implementation** — documentation phase only. No code has been written yet.

What exists:
- `docs/SPEC.md` — Technical specification (v1.0.0-draft)
- `docs/PRD.md` — Product requirements document
- `docs/IMPLEMENTATION_PLAN.md` — 28-task, 5-phase implementation plan for Claude Code
- `docs/purveyor-architecture.mermaid` — System architecture diagram
- `docs/DESIGN_DECISIONS.md` — **Created this session** — 26 design decisions with full rationale and impl implications
- `README.md` — Complete project README

What does NOT exist yet: any `src/` code, `tests/`, `pyproject.toml`, Docker files, CI config, or Terraform modules.

---

## Next Steps

1. **Start Phase 0 (Project Scaffolding)** — Task 0.1 through 0.5 per IMPLEMENTATION_PLAN.md. The DESIGN_DECISIONS.md should be treated as additive to the SPEC — read it alongside the SPEC before implementing any task.

2. **Update SPEC.md** with the schema changes from DESIGN_DECISIONS.md §2 before starting Phase 0 Task 0.4 (Database Setup), specifically:
   - Revised `order_confirmations` table schema
   - New `notification_registry` table
   - Updated `webhook_events` table (add `api_key_hash`, `delivered`)

3. **Add new tool to SPEC.md** — `cancel_pending_order` in §3.2.4 Order Tools.

4. **Add new env vars to SPEC.md** — `CONFIRMATION_BASE_URL`, `CONFIRMATION_SECRET_KEY`, `GEOCODING_BASE_URL`, `ALLOWED_ORIGINS` to the environment variables table.

5. **Phase 0 → Phase 1 → Phase 2** — Follow the implementation plan sequentially. Each phase has explicit acceptance criteria.
