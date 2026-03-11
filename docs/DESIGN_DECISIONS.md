# Purveyor — Design Decisions

**Date:** 2026-03-11
**Status:** Finalized (pre-implementation)
**Method:** Design interview covering gaps, ambiguities, and unstated assumptions in SPEC.md, PRD.md, and IMPLEMENTATION_PLAN.md

This document captures decisions made during a structured design interview. Each entry includes the gap identified, the question asked, the developer's answer, the resulting decision, and any implications for the SPEC or IMPLEMENTATION_PLAN.

---

## 1. Cloud Mode Authentication for Order Confirmation

**Gap:** The SPEC states "zero credentials stored server-side in cloud mode" (NF-08) and "the server is stateless." But the order confirmation flow requires placing an actual order via SkyFi API when the user clicks Confirm on `/confirm/{token}` — potentially minutes after the original MCP session and its `X-Skyfi-Api-Key` header are gone. No mechanism for re-authentication at confirmation time was specified.

**Question asked:** In cloud mode, when a user calls `create_tasking_order`, their API key arrives in the `X-Skyfi-Api-Key` header. But when they later click Confirm on `/confirm/{token}` — potentially minutes later from a browser — the original MCP session and its header are gone. How should Purveyor authenticate to SkyFi to place the actual order at that point?

**Answer:** Option 4 — Signed/encrypted token approach. The confirmation token is an encrypted payload containing the API key and order parameters. It is decrypted in-memory at confirmation time. No credentials at rest. The encryption key is server-side config (an env var). The token expires in 30 minutes. The URL is already a sensitive single-use artifact regardless. If SkyFi later offers a hosted checkout page, migrate to that approach and drop the API key from the token entirely.

**Decision:** Confirmation tokens are Fernet-encrypted payloads containing the API key and full order parameters. The ciphertext becomes the URL token. No API key is stored in the database. The `order_confirmations` table stores only a hash of the token, not the payload.

**Implications for SPEC:**
- The `request_payload JSONB` column in the `order_confirmations` table schema (§5.1) should be removed.
- Add `CONFIRMATION_SECRET_KEY` to the environment variables table (§9.3 / Configuration).
- NF-08 ("Zero credentials stored server-side in cloud mode") is satisfied by this approach.
- Add a migration path note: if SkyFi introduces a hosted checkout, the token format can be simplified.

**Implications for IMPLEMENTATION_PLAN:**
- Task 3.1 (Order Confirmation Flow): replace `generate_confirmation_token()` with a Fernet-based encrypt/decrypt pair. The token IS the payload.
- Add `cryptography` to dependencies in pyproject.toml (Task 0.1).

---

## 2. Order Confirmations Database Schema

**Gap:** With the API key moving into the encrypted token, the `order_confirmations` table schema in SPEC §5.1 becomes partially redundant.

**Question asked:** If the API key and order parameters are in the encrypted token (not stored server-side), what does the `order_confirmations` table actually need to track?

**Answer:** Option 1 — Lightweight tracking record only. Store: a hash of the token (for lookup without storing the token itself), status (`pending` → `confirmed` → `placed`, or `expired`, or `cancelled`), the resulting `skyfi_order_id` once placed, timestamps, and the MCP session identifier so we can route the "order placed" notification back to the correct agent session via SSE. Order details for the confirmation page come from decrypting the URL token, not from the database. This gives us single-use enforcement, agent notification routing, and a minimal operational record without storing credentials or redundant payload data.

**Decision:** `order_confirmations` schema:
```sql
CREATE TABLE order_confirmations (
    id UUID PRIMARY KEY,
    token_hash VARCHAR(64) UNIQUE NOT NULL,   -- SHA-256 of the Fernet token
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, confirmed, placed, expired, cancelled
    order_type VARCHAR(20) NOT NULL,          -- TASKING or ARCHIVE
    api_key_hash VARCHAR(64) NOT NULL,        -- SHA-256 of the API key (for routing)
    mcp_session_id VARCHAR(255),              -- MCP session for SSE notification routing
    skyfi_order_id UUID,                      -- Set after order is placed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);
```

**Implications for SPEC:** Replace the schema in §5.1 with the above. Add `cancelled` as a valid status value.

**Implications for IMPLEMENTATION_PLAN:** Task 3.1 updated accordingly.

---

## 3. SSE Notification Reliability / Offline Delivery

**Gap:** The SPEC mentions pushing notifications to the connected MCP client via SSE after webhook events arrive, but doesn't address what happens when the SSE stream is disconnected — which is common for transient Claude Web sessions that may disconnect before a user confirms an order.

**Question asked:** What should happen when the SSE stream is gone at notification time?

**Answer:** Option 1, implemented simply. The `webhook_events` table already captures all inbound events from SkyFi. Add a `delivered` boolean (the existing `processed` column). When a new MCP session initializes and authenticates, query for unprocessed events matching that API key and deliver them as part of session startup. Mark them processed after delivery. This covers both order confirmation notifications and AOI monitoring alerts. SSE delivery (when stream is open) is opportunistic and a bonus. The reliable path is: persist to `webhook_events` first → deliver on reconnect.

**Decision:** Notification delivery pattern:
1. All inbound SkyFi webhooks are persisted to `webhook_events` with `delivered=false`.
2. If the SSE stream is open at delivery time, push immediately and mark `delivered=true`.
3. On MCP session `initialize`, query `webhook_events WHERE delivered=false AND api_key_hash=<hash>`, deliver them in order, mark `delivered=true`.
4. `webhook_events` must include `api_key_hash` to support the reconnect query.

**Implications for SPEC:**
- Update §7.1 (Webhook Endpoints) to describe the persist-then-deliver pattern.
- Add `api_key_hash` and `delivered` columns to `webhook_events` table schema (§5.1). The existing `processed` column may be renamed `delivered` for clarity.

**Implications for IMPLEMENTATION_PLAN:**
- Task 2.1 (MCP Server Setup): add reconnect delivery logic to the `initialize` handler.
- Task 3.3 (Webhook Receiver): ensure `api_key_hash` is resolved and stored on every inbound webhook.

---

## 4. Webhook Ownership Tracking (Cloud Multi-Tenant)

**Gap:** In cloud mode, a SkyFi webhook arrives at Purveyor's `/webhooks/order-event` or `/webhooks/archive-notification`. The webhook contains order/archive data but no Purveyor user identity. There was no mechanism to determine which user's MCP session to notify.

**Question asked:** When a SkyFi webhook fires, how should Purveyor know which API key to attribute it to for reconnect delivery?

**Answer:** Option 1 — Dual lookup approach. For order events: look up `order_id` in `order_confirmations` to find the `api_key_hash`. For archive notification events: maintain a lightweight `notification_registry` table. When a user calls `setup_monitoring`, record the `notification_id` SkyFi returns alongside the `api_key_hash` of the user who created it. When the archive notification webhook arrives, look up the `notification_id` to find the owning user.

**Decision:** Add `notification_registry` table:
```sql
CREATE TABLE notification_registry (
    notification_id UUID PRIMARY KEY,
    api_key_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```
On `delete_notification`, remove the corresponding row from `notification_registry`.

**Implications for SPEC:** Add `notification_registry` to §5.1 database schema. Update §7.1 to describe the lookup logic for webhook routing.

**Implications for IMPLEMENTATION_PLAN:** Task 3.4 (Notification Tools): store to `notification_registry` in `setup_monitoring`. Task 3.3 (Webhook Receiver): add lookup logic.

---

## 5. Confirmation URL Base URL Resolution

**Gap:** The confirmation URL returned by order creation tools needs to point to a publicly reachable URL. In local mode, `localhost` is correct but only works if the user's browser is on the same machine. In cloud mode, the server must be reachable externally. No BASE_URL config was defined.

**Question asked:** How should the confirmation URL base be determined?

**Answer:** Layered resolution in order of precedence: (1) If `CONFIRMATION_BASE_URL` is explicitly set in config, use it — always wins. (2) If not set, derive from the incoming MCP request's `Host` header and scheme, respecting `X-Forwarded-Host` and `X-Forwarded-Proto` for reverse proxy scenarios. (3) If neither is available, fall back to `http://localhost:{SERVER_PORT}`. In local mode, localhost is the correct default and needs no configuration. In cloud mode behind Caddy or an ALB, forwarded headers handle it automatically. Log a warning at startup if running in cloud mode with no `CONFIRMATION_BASE_URL` set and no requests yet to derive from — a nudge, not a hard failure.

**Decision:** Add `CONFIRMATION_BASE_URL` optional env var. Implement a `resolve_base_url(request)` helper that applies the three-tier logic above. Use this same helper for `setup_monitoring` webhook URL resolution (see §20).

**Implications for SPEC:** Add `CONFIRMATION_BASE_URL` to environment variables table (§9.3). Add a note to §4.2 (Order Confirmation Flow) describing the URL resolution logic.

**Implications for IMPLEMENTATION_PLAN:** Task 0.3 (Configuration Management): add `confirmation_base_url: str | None` to Settings. Task 3.1 (Confirmation Flow): implement `resolve_base_url()` helper.

---

## 6. Large AOI Geocoding (Exceeds SkyFi Limits)

**Gap:** If a user asks to search for imagery of a country (e.g., "Russia," "United States"), OpenStreetMap returns a bounding box far exceeding SkyFi's 500,000 sq km search limit. The spec mentions the limit but doesn't specify what Purveyor should do when geocoding returns an oversized AOI.

**Question asked:** If a user says "search for imagery of Russia" or "the United States," what should Purveyor do?

**Answer:** Option 4 — Warn and proceed with clipped AOI. When the geocoded bounding box exceeds 500,000 sq km, clip to a box centered on the geometric centroid (or the city/capital point if OSM provides one distinct from the geometric centroid). Return search results for the clipped area but include in the tool response: the original area size, the clipped area size, what center point was chosen, and a suggestion to refine the location. For moderate overages (up to ~2×), results are probably fine. For extreme overages (country-scale), the warning is the most important part.

**Decision:** In `resolve_location()` helper and in `search_archives`, after geocoding:
1. Calculate bounding box area.
2. If area ≤ 500,000 sq km: use as-is.
3. If area > 500,000 sq km: clip to a 500,000 sq km box centered on the OSM-provided `centroid` or geometric center. Include in the response a `location_note` field describing the clip.

**Implications for SPEC:** Update §3.2.6 (`calculate_aoi_area`) to note this clip behavior. Add `location_note` to `search_archives` output schema (§3.2.1).

**Implications for IMPLEMENTATION_PLAN:** Task 2.2 (Geospatial Tools): implement clip logic in `resolve_location()`.

---

## 7. Tool Error Format

**Gap:** The SPEC doesn't define whether tool errors should use MCP's `isError=true` in content (conversational) or JSON-RPC error responses (protocol failures). No error codes are defined.

**Question asked:** Which error model should Purveyor use, and are there cases where the choice differs by error type?

**Answer:** Split by error type, with structured error content. Business/user errors return `isError=true` with a structured object: `{code: str, message: str, detail?: any}`. Infrastructure/protocol errors raise JSON-RPC errors (e.g., `-32603`).

Error codes:
- `aoi_too_large` — AOI exceeds SkyFi search limits
- `no_results` — Search returned no matching archives
- `rate_limited` — Purveyor inbound rate limit hit
- `invalid_input` — Pydantic validation failure on tool input
- `skyfi_api_error` — 4xx from SkyFi (bad auth, insufficient budget, etc.)
- `skyfi_unavailable` — 5xx or timeout from SkyFi (transient)
- `order_expired` — Confirmation token has expired
- `order_already_placed` — Attempted to cancel or re-confirm an already-placed order
- `open_data_limit_reached` — Daily open data order limit hit
- `feasibility_pending` — Feasibility task still running (not an error, informational)

SkyFi 401/403 → `skyfi_api_error` (business error, goes through `isError` content). SkyFi 5xx/timeout → `skyfi_unavailable` (infrastructure, but recoverable — also `isError` content, not JSON-RPC error). Unhandled Python exceptions, DB unreachable, serialization failures → JSON-RPC `-32603`.

**Decision:** Create `src/purveyor/core/errors.py` with a `ToolError` class and the error code enum. Add a SkyFi API error mapping function that translates HTTP status codes and response bodies to the appropriate `ToolError`.

**Implications for SPEC:** Add §3.6 Error Handling with the error taxonomy and code definitions.

**Implications for IMPLEMENTATION_PLAN:** Add `errors.py` to Phase 1 deliverables. All tool implementations use `ToolError` for return values, not ad-hoc dicts.

---

## 8. `check_feasibility` Polling Behavior

**Gap:** The SPEC says `check_feasibility` creates a SkyFi task and polls until completion with a 60-second timeout, but doesn't specify behavior at timeout. A 60-second blocking tool call is also poor UX.

**Question asked:** What should the tool return if the 60 seconds elapse before SkyFi marks the task complete?

**Answer:** Option 3 — dual-mode tool, with no hard blocking timeout. `check_feasibility` operates in two modes based on input: (1) If called with `location` + parameters (no `feasibility_id`): create the SkyFi task, do a quick initial poll (2–3 seconds, a few attempts). If results are ready, return them immediately. If not ready, return `feasibility_id` + `status: "pending"` with a message like "Feasibility check is running." This is `isError=false` — a normal informational response. (2) If called with `feasibility_id` only: poll SkyFi for current status and return whatever is available — complete results, partial provider scores, or still-pending status. The agent handles the conversational loop naturally.

**Decision:** `check_feasibility` input schema adds `feasibility_id: string?` as an optional parameter. When only `feasibility_id` is provided, skip task creation and go directly to status polling. Remove the 60-second blocking poll. Replace with: 2–3 quick attempts on create-mode, single poll on check-mode.

**Implications for SPEC:** Update `check_feasibility` tool spec in §3.2.3 to add `feasibility_id` input parameter and describe dual-mode behavior. Update output to include `status` field that can be `"pending"` | `"complete"` | `"failed"`.

**Implications for IMPLEMENTATION_PLAN:** Task 2.5 (Feasibility Tools): rewrite the polling logic per the dual-mode pattern. Remove the `background_tasks` dependency for feasibility (it was listed as using background tasks in Task 3.5).

---

## 9. Delivery Credentials Handling

**Gap:** `create_tasking_order` and `create_archive_order` accept `delivery_driver` and `delivery_params` (cloud storage credentials). The spec treats `delivery_params` as an opaque object, with no defined schema, no security guidance for logging, and no guidance on making the field optional.

**Question asked:** How should the tool handle delivery credentials in practice?

**Answer:** Option 3 as default (NONE driver), with Option 1's validation when a driver is specified. `delivery_driver` defaults to `NONE` (SkyFi holds the data; user downloads via `download_deliverable` or SkyFi UI). When a delivery driver IS specified, validate with typed Pydantic schemas per driver. Never log `delivery_params` content — add an explicit structlog filter/processor that scrubs fields matching `delivery_params`, `aws_secret_key`, `gs_credentials`, `azure_connection_string`, and similar. Credentials pass through in-memory only: encrypted token → decrypted at confirmation → SkyFi API call.

**Decision:**
- `delivery_driver: str = "NONE"` and `delivery_params: dict | None = None` in order creation tools.
- Add typed Pydantic models: `S3DeliveryParams`, `GCSDeliveryParams`, `AzureDeliveryParams`.
- Add structlog processor `scrub_sensitive_fields()` applied before any log output. Fields scrubbed: `delivery_params`, `api_key`, `aws_secret`, `gs_credentials`, `azure_sas`, etc.
- Tool description should list supported drivers and explain that omitting them keeps imagery in SkyFi's custody for manual download.

**Implications for SPEC:** Update §3.2.4 order tool inputs to show `delivery_driver` defaulting to `NONE`. Add §11 (Security Considerations) note about log scrubbing of delivery credentials.

**Implications for IMPLEMENTATION_PLAN:** Add `S3DeliveryParams` etc. to `skyfi_types.py` (Task 1.1). Add log scrubbing processor to `logging.py` (Task 0.2).

---

## 10. CORS Policy

**Gap:** The SPEC says "CORS middleware for browser-based MCP clients" but doesn't define the allowed origins policy.

**Question asked:** What should the CORS policy be for the `/mcp` endpoint?

**Answer:** Option 1 — Default to `*` for CORS origins. The authentication boundary is the API key in the `X-Skyfi-Api-Key` header, not the browser origin. CORS protects against a threat model (cookies/session credentials) that doesn't apply here. Operators who want to restrict origins can set `ALLOWED_ORIGINS` as a comma-separated env var. Same policy applies to `/confirm/{token}` page — it's opened directly by users, not embedded.

**Decision:** FastAPI CORS middleware configured with `allow_origins=["*"]` by default. `ALLOWED_ORIGINS` env var (optional, comma-separated) overrides to a specific list.

**Implications for SPEC:** Add `ALLOWED_ORIGINS` to environment variables table.

**Implications for IMPLEMENTATION_PLAN:** Task 2.1 (MCP Server Setup): configure CORS middleware as above.

---

## 11. Demo Agent Architecture

**Gap:** Task 5.1 describes the demo agent as "connecting to Purveyor as an MCP client" but doesn't specify whether this requires a separately running server or if the demo is self-contained.

**Question asked:** Does the demo agent connect to Purveyor as an external client (requires the server to already be running), or does it spin up the server in-process?

**Answer:** Option 3 — stdio transport in-process. The demo agent spawns the Purveyor MCP server as a subprocess and communicates over pipes. Single command, no ports, no network configuration, no "is the server running" issues. The MCP Python SDK supports stdio natively alongside Streamable HTTP. The demo works with an in-memory store for the demo session — nothing needs to persist. For users testing against the HTTP server, the docs show how to point any MCP client at a running `purveyor serve` instance.

**Decision:** `purveyor demo` spawns `purveyor serve --transport stdio` as a subprocess (or uses the MCP SDK's in-process stdio mechanism). The server code handles both `stdio` and `streamable-http` transports. Demo sessions use SQLite in-memory (`sqlite:///:memory:`) to avoid any filesystem setup.

**Implications for SPEC:** Add `--transport` flag to server options. Add `stdio` as a supported transport alongside Streamable HTTP in §3.1.

**Implications for IMPLEMENTATION_PLAN:** Task 2.1 (MCP Server Setup): add stdio transport support. Task 5.1 (Demo Agent): update to use stdio subprocess pattern.

---

## 12. OSM Nominatim Rate Limiting

**Gap:** Nominatim's usage policy requires a maximum of 1 request/second. In cloud mode with concurrent users, Purveyor could easily violate this, risking IP bans.

**Question asked:** How should Nominatim's 1 req/sec limit be handled?

**Answer:** Primarily rely on caching (1-hour geocode TTL absorbs most repeat queries), but implement a global `asyncio.Semaphore` as a safety net. This is a few lines of code and guarantees compliance regardless of usage patterns. A 1–2 second wait behind the semaphore is invisible in conversational flows. For operators at scale, add a `GEOCODING_BASE_URL` env var pointing at a self-hosted Nominatim, Photon instance, or commercial API. Don't build the abstraction now — just make the base URL configurable.

**Decision:**
- `GEOCODING_BASE_URL` optional env var (default: `https://nominatim.openstreetmap.org`).
- Global `asyncio.Semaphore(1)` guard on all Nominatim HTTP calls in `geocode_location`.
- Nominatim `User-Agent` header set to `Purveyor-MCP/1.0` (required by Nominatim policy).

**Implications for SPEC:** Add `GEOCODING_BASE_URL` to environment variables table. Update §3.2.6 geocoding behavior to note the semaphore.

**Implications for IMPLEMENTATION_PLAN:** Task 2.2 (Geospatial Tools): add semaphore + configurable base URL.

---

## 13. Background Task Recovery in Multi-Instance Deployments

**Gap:** Task 3.5 describes a startup recovery sweep that re-queues orphaned `BackgroundTask` records. In multi-instance cloud deployments (Fargate, Cloud Run), every instance would try to re-queue and re-run the same tasks simultaneously.

**Question asked:** How should Purveyor handle the startup recovery sweep in multi-instance deployments?

**Answer:** Both `SELECT FOR UPDATE SKIP LOCKED` (mechanism) and idempotent task design (defense-in-depth). `SKIP LOCKED` is a one-line change to the Postgres recovery query that atomically claims tasks no other instance has locked. SQLite deployments are local/single-instance by definition and don't need SKIP LOCKED. Add a runtime check: SQLite → plain `SELECT WHERE status = 'pending'`; Postgres → `SELECT FOR UPDATE SKIP LOCKED`. All tasks are designed to be idempotent: the order placement task checks the confirmation record's status before calling SkyFi (if already `placed`, no-op). Feasibility polling is naturally idempotent.

**Decision:** Two-layer protection: row locking prevents duplicate execution, idempotency prevents damage if locking somehow fails.

**Implications for SPEC:** Add §5.4 (Background Task Concurrency) noting the SKIP LOCKED pattern and idempotency requirement.

**Implications for IMPLEMENTATION_PLAN:** Task 3.5 (Background Task Infrastructure): add SKIP LOCKED logic and idempotency checks per task type.

---

## 14. Tool Response Summary Format

**Gap:** Every tool returns a `summary: string` field, but the spec doesn't define who that string is written for — the agent (machine context) or the user (directly presentable).

**Question asked:** Should summaries be written for the agent to relay, or as if speaking to the end user?

**Answer:** Option 1 with structured data alongside — the summary is a dense, factual briefing note for the agent, not a user-facing script. Format: key stats, notable items highlighted, no first-person voice, no suggestions like "want me to order it," no conversational filler. Example: "Found 23 archives matching query. 8 are VERY HIGH resolution (0.5m). Price range: $120–$850/scene. 3 are open data (free). Lowest cloud cover: 2% on archive abc-123 from PLANET, captured 2024-03-15. AOI overlap ranges from 45% to 100%." The full structured data is also returned alongside it. Summaries don't need to be localized or tone-matched.

**Decision:** All tool implementations follow this summary style. Summaries answer: what did we find, what's notable, what are the ranges/extremes. No agent-voice suggestions.

**Implications for IMPLEMENTATION_PLAN:** All tool implementation tasks (2.2–2.7, 3.2, 3.4) include this summary style guidance.

---

## 15. V1 Scope

**Gap:** The PRD assigns P0/P1/P2 priorities but doesn't define which priority tiers constitute the V1 release. The implementation plan appears to implement everything.

**Question asked:** Is V1 everything (P0+P1+P2), or should P2 items be deferred?

**Answer:** Everything — P2 items (legacy SSE endpoint, custom metadata on orders, cloud OAuth stub) are small enough to include in V1 for completeness.

**Decision:** All P0, P1, and P2 requirements are in scope for V1. The implementation plan as written covers the full scope.

**Implications:** No scope changes to the implementation plan.

---

## 16. In-Memory Rate Limiter Memory Growth

**Gap:** The in-memory sliding window rate limiter maintains counters per API key. In a cloud deployment with many distinct API keys making occasional requests, the dict could grow unbounded.

**Question asked:** How should the in-memory rate limiter handle unbounded memory growth?

**Answer:** Option 1 — inline cleanup on access. The sliding window counters already have a natural TTL (the window itself). When checking a key's rate, prune timestamps older than the window. When no timestamps remain for a key, delete the key from the dict. Add a lazy sweep that runs on a timer (every 5 minutes) and drops any key whose newest timestamp is older than the longest window (1 hour for order confirmations). This is done inline in `check_rate_limit`, no background task infrastructure needed.

**Decision:** `MemoryRateLimiter.check_rate_limit()` prunes stale timestamps inline. A periodic `asyncio.create_task` sweep every 5 minutes drops fully-idle keys.

**Implications for IMPLEMENTATION_PLAN:** Task 4.1 (Rate Limiting): implement inline pruning and periodic sweep.

---

## 17. Open Data Order Limits

**Gap:** The PRD specifies daily open data order limits (1/day free, 5/day pro) and implies Purveyor should be aware of them, but doesn't specify whether Purveyor tracks/enforces them or relies on SkyFi.

**Question asked:** Should Purveyor track and enforce these limits, or let SkyFi's API return the error?

**Answer:** Option 1 — SkyFi owns the limits, SkyFi enforces the limits. When the API returns an error for exceeding the daily cap, map it to: `isError=true`, code `open_data_limit_reached`, message "You've reached your daily open data order limit. Free accounts can place 1 open data order per day; Pro accounts can place up to 5. You can upgrade at app.skyfi.com or try again tomorrow." Enhancement: include account type context in the `whoami` tool response (derivable from `isDemoAccount` and budget fields) so the agent can proactively inform the user of their tier without them hitting the wall first.

**Decision:** No limit tracking in Purveyor. Map SkyFi's limit error to `open_data_limit_reached`. Enrich `whoami` response with inferred account tier.

**Implications for IMPLEMENTATION_PLAN:** Task 1.1 (SkyFi API Client): add `open_data_limit_reached` to error mapping. Task 2.7 (Account Tool): add account tier inference to `whoami` output.

---

## 18. SkyFi API Drift Detection

**Gap:** The PRD lists "SkyFi API schema changes" as a risk. The mitigation ("Pydantic validation surfaces issues clearly; version-pin OpenAPI spec") is vague and unactionable.

**Question asked:** What's the concrete strategy for detecting and handling SkyFi API drift?

**Answer:** Option 3 (detection) + Option 2 (runtime resilience). Runtime: all SkyFi response models use `model_config = ConfigDict(extra='ignore')`. Use `Optional` liberally for fields that SkyFi might null. Log a structured warning when responses have unexpected nulls or missing expected fields, but return results to the agent with whatever data was received. Detection: commit the OpenAPI spec to `docs/openapi.json`. Weekly GitHub Actions workflow fetches the live spec from SkyFi, diffs against the committed version, and if there's a meaningful change, automatically opens a GitHub issue tagged `api-drift` with the diff summary. Weekly live test suite (read-only) is the second detection layer.

**Decision:** Two-layer approach: lenient runtime parsing + weekly automated schema diff CI job.

**Implications for SPEC:** Add §10.5 (API Drift Detection) describing this strategy.

**Implications for IMPLEMENTATION_PLAN:** Task 1.1 (SkyFi API Client): use `extra='ignore'` on all response models. Task 5.3 (CI/CD): add the weekly schema diff workflow and weekly live test workflow.

---

## 19. Order Confirmation Page UX

**Gap:** The SPEC says "lightweight FastAPI-served HTML page" but doesn't define the design bar, template system, or required UI elements.

**Question asked:** What's the intended design bar for the `/confirm/{token}` page?

**Answer:** Option 2 (styled), but self-contained — inline the CSS, no CDN dependencies. Single HTML file served by FastAPI with embedded styles using Jinja2 (natively supported by FastAPI). No JavaScript frameworks, no external requests. Show: SkyFi logo (embedded as base64 SVG or served from a static route), clear visual hierarchy, order type (archive/tasking), location description, product type and resolution, estimated cost prominently, cost calculation breakdown ("X sq km × $Y/sq km"), two buttons (primary "Confirm Order" / secondary "Cancel"), a brief reassurance line ("You will be charged approximately $X.XX to your SkyFi account"), and token expiry countdown ("This link expires in 28 minutes"). After confirmation: success state with SkyFi order ID and "your agent has been notified." After cancellation: clean "Order cancelled" state. Both actions are simple HTML form POSTs — no JavaScript required.

**Decision:** Single Jinja2 template file at `src/purveyor/templates/confirm.html` with embedded CSS. Not operator-customizable in V1. Static assets (logo) served from `/static/`.

**Implications for IMPLEMENTATION_PLAN:** Task 3.1 (Confirmation Flow): implement Jinja2 template, add `jinja2` and `python-multipart` to dependencies, configure `StaticFiles` in FastAPI app.

---

## 20. Monitoring Webhook URL Handling

**Gap:** `setup_monitoring` must register a webhook URL with SkyFi pointing to Purveyor's `/webhooks/archive-notification`. In local mode, `localhost` is unreachable from SkyFi. The spec's `webhook_url` parameter is present but the behavior around omission/localhost detection isn't defined.

**Question asked:** When `setup_monitoring` is called without an explicit `webhook_url`, and the resolved URL would be localhost, what should happen?

**Answer:** Option 3 (user-provided URL) as mechanism + Option 1 (warn if localhost) as safety net. Three behaviors: (1) If the user provides an explicit `webhook_url` — use it directly. Covers users with their own endpoint, ngrok tunnels, Zapier webhooks, etc. (2) If no `webhook_url` is provided — default to Purveyor's own `/webhooks/archive-notification` using the same `resolve_base_url()` logic built for the confirmation URL. (3) If the resolved URL is localhost/127.0.0.1 — create the monitor anyway (it's valid in SkyFi; user may add a tunnel later) but include a warning in the tool response: "Monitor created, but the webhook URL points to localhost which SkyFi cannot reach. Notifications won't arrive until you set WEBHOOK_BASE_URL or provide a public webhook_url."

**Decision:** `setup_monitoring` tool accepts an optional `webhook_url` parameter. Default resolution uses `resolve_base_url()`. Localhost detection adds a `warning` field to the tool response.

**Implications for SPEC:** Update `setup_monitoring` tool spec in §3.2.5 to clarify the three-behavior logic and add the `warning` output field.

**Implications for IMPLEMENTATION_PLAN:** Task 3.4 (Notification Tools): implement the three-behavior logic and localhost detection.

---

## 21. Priority Tasking Orders

**Gap:** `create_tasking_order` includes a `priority: boolean?` parameter that is never explained in any doc. Cost implications and semantics are undefined.

**Question asked:** What does `priority` mean and how should Purveyor surface it?

**Answer:** Option 1 — pass through with a clear description. Include `priority` in the tool input schema as `priority: bool = False` with description: "Request priority scheduling for faster satellite tasking. May result in higher cost. Default: false." Pass the value to SkyFi. The estimated cost on the confirmation page comes from SkyFi's order response and will reflect the priority premium if there is one. The human-in-the-loop confirmation flow handles price surprises — if the user dislikes the premium, they click Cancel.

**Decision:** No special handling for `priority`. Include in schema with description. The confirmation page already shows the actual cost, handling this case.

**Implications:** No spec changes needed. Implement as described in `create_tasking_order` schema.

---

## 22. Estimated vs. Actual Cost Accuracy

**Gap:** The confirmation page shows an "estimated cost" before order placement, but the actual charge is determined by SkyFi when the order is placed. The accuracy and labeling of this estimate were not addressed.

**Question asked:** How accurate is the estimate, and how should discrepancies be communicated?

**Answer:** Option 2 — derive from existing data, label clearly by order type. For archive orders: use `priceForOneSquareKm × aoi_area_sq_km` from the archive search results metadata (high confidence — archive pricing is tied to the specific image and doesn't fluctuate). Label: "Estimated cost." For tasking orders: derive from the pricing matrix for the product type, resolution, and provider, multiplied by AOI area (rougher estimate). Label: "Estimated cost based on current pricing" with a note: "Final cost is determined when the order is processed and may vary slightly." Show how the cost was calculated ("X sq km × $Y/sq km"). After the order is placed and SkyFi returns `orderCost`, store the actual cost. `get_order_status` shows the real charged amount.

**Decision:** Confirmation page shows calculation breakdown and type-appropriate label. `order_confirmations` table can store `estimated_cost_cents` for display; the actual SkyFi `orderCost` is fetched live via `get_order_status`.

**Implications for IMPLEMENTATION_PLAN:** Task 3.2 (Order Creation Tools): implement cost estimation logic per order type. Task 3.1 (Confirmation Flow): render cost calculation breakdown on the confirmation page.

---

## 23. Order Cancellation from Agent

**Gap:** Once `create_tasking_order` or `create_archive_order` returns a confirmation URL, the order is in `pending` state. If the user changes their mind and tells the agent to cancel, there was no mechanism for the agent to cancel without the user visiting the URL.

**Question asked:** Can the agent cancel a pending confirmation without the user visiting the URL?

**Answer:** Option 1 — add `cancel_pending_order` tool. Takes the confirmation token or identifier from the create response. Marks the confirmation as `cancelled` (new status). If someone clicks the URL after cancellation, they see "This order has been cancelled." Returns "Order cancelled. No charge will occur." Gated by checking current status is `pending`: if already `placed`, return error "This order has already been placed. Contact SkyFi to cancel." If already `expired` or `cancelled`, return a no-op success. Tool annotation: `destructiveHint=false` — it prevents spending, it doesn't cause it.

**Decision:** Add `cancel_pending_order` tool to the order tools. Add `cancelled` as a valid status in `order_confirmations`. This is a new tool not in the current spec or implementation plan.

**Implications for SPEC:** Add `cancel_pending_order` to §3.2.4 Order Tools.

**Implications for IMPLEMENTATION_PLAN:** Add `cancel_pending_order` to Task 3.2 (Order Creation Tools).

---

## 24. Confirmation Token Encryption Algorithm

**Gap:** The encrypted confirmation token approach requires a specific cryptographic implementation. No algorithm was specified.

**Question asked:** What encryption approach should be used for the confirmation token?

**Answer:** Option 1 — Python's Fernet symmetric encryption (`cryptography` library). AES-128-CBC + HMAC-SHA256, built-in TTL enforcement, URL-safe base64 output. Dead simple, well-audited. Implementation: serialize payload (API key + order params + expiry) as JSON, encrypt with Fernet, use ciphertext as the URL token. At the confirmation page, `Fernet.decrypt(token, ttl=1800)` handles expiry automatically. If `CONFIRMATION_SECRET_KEY` changes (server redeployment, key rotation), pending tokens become invalid — acceptable for a 30-minute window. Document key rotation implications for operators.

**Decision:** Use `Fernet` from the `cryptography` package. Token is `Fernet(key).encrypt(json_payload_bytes)`. Decryption uses `Fernet(key).decrypt(token, ttl=1800)`.

**Implications for SPEC:** Add `cryptography` to dependencies. Add note to §11 (Security) about key rotation implications.

**Implications for IMPLEMENTATION_PLAN:** Task 0.1: add `cryptography` to `pyproject.toml`. Task 3.1: implement Fernet-based token generation.

---

## 25. CONFIRMATION_SECRET_KEY Provisioning

**Gap:** The Fernet key must be consistent across all instances in multi-instance cloud deployments, and must survive restarts in any persistent deployment. Auto-generation behavior and error handling were unspecified.

**Question asked:** How should `CONFIRMATION_SECRET_KEY` be provisioned, with different requirements for local vs. cloud mode?

**Answer:** Option 3 — different behavior by mode. Local mode: auto-generate an ephemeral Fernet key in-memory at startup. Log an info message: "Using ephemeral confirmation key. Pending order confirmations will not survive server restart. Set CONFIRMATION_SECRET_KEY in config.json for persistent tokens." Cloud mode (`local_mode=False`): require `CONFIRMATION_SECRET_KEY` as an env var. Refuse to start without it. Log an error with the fix: "CONFIRMATION_SECRET_KEY is required in cloud mode. Generate one with: `purveyor generate-key`." Add `purveyor generate-key` CLI command (prints `Fernet.generate_key().decode()`). Local users who want persistent tokens can optionally set the key in `config.json`.

**Decision:** Mode-differentiated provisioning. Add `purveyor generate-key` CLI subcommand.

**Implications for SPEC:** Add `CONFIRMATION_SECRET_KEY` to environment variables table as "Required in cloud mode."

**Implications for IMPLEMENTATION_PLAN:** Task 0.3 (Configuration): add `confirmation_secret_key` to Settings with conditional validation. Task 0.1 / Task 5.5: add `generate-key` CLI subcommand.

---

## 26. Testing Strategy — Real SkyFi API

**Gap:** The SPEC describes respx mocks for all integration tests, but doesn't address whether real API contract validation is part of the testing strategy.

**Question asked:** Do you have access to a real SkyFi test account, and should any part of the test suite hit the real API?

**Answer:** Option 2 — mocked tests always, optional live tests behind a flag. Mocked tests with respx run on every push in CI — no credentials, fast, deterministic. A separate live test suite behind a `--live` pytest marker runs against SkyFi's real API, gated on `SKYFI_TEST_API_KEY` env var. Live suite is scoped to read-only operations only (search archives, get pricing, check feasibility, whoami) — never creates orders or notifications in automated tests. If `SKYFI_TEST_API_KEY` is not set, live tests are skipped with a clear message. A separate scheduled GitHub Actions workflow runs the live suite weekly using a test API key stored as a GitHub Actions secret. This catches SkyFi API drift before it hits users without slowing CI. Open source contributors without a SkyFi key can contribute confidently against mocked tests only.

**Decision:** Two test suites: `tests/` (always runs, respx mocked) and `tests/live/` (requires `--live` + `SKYFI_TEST_API_KEY`, read-only, skipped gracefully). Separate weekly CI workflow for live tests.

**Implications for IMPLEMENTATION_PLAN:** Task 4.3 (Comprehensive Test Suite): add live test infrastructure. Task 5.3 (CI/CD): add weekly live test workflow.

---

## Summary of New/Changed Artifacts

### New tools added (not in original spec):
- `cancel_pending_order` — Cancel a pending order confirmation from within the agent conversation.

### New config env vars:
- `CONFIRMATION_BASE_URL` — Optional. Base URL for confirmation/webhook URLs (§5, §20).
- `CONFIRMATION_SECRET_KEY` — Required in cloud mode. Fernet encryption key.
- `GEOCODING_BASE_URL` — Optional. Custom Nominatim/Photon/commercial geocoding endpoint.
- `ALLOWED_ORIGINS` — Optional. Comma-separated CORS allowed origins (default: `*`).

### New CLI commands:
- `purveyor generate-key` — Prints a new Fernet key for use as `CONFIRMATION_SECRET_KEY`.

### New database tables:
- `notification_registry` — Maps `notification_id` to `api_key_hash` for webhook routing.
- `order_confirmations` — Schema revised (see §2).

### Schema changes from original SPEC:
- `order_confirmations.request_payload` removed (payload is in the encrypted token).
- `order_confirmations.api_key_hash` added.
- `order_confirmations.mcp_session_id` added.
- `order_confirmations.status` adds `cancelled` as a valid value.
- `webhook_events.api_key_hash` added.
- `webhook_events.delivered` added (replaces/renames `processed`).

### Key behavioral changes from original SPEC:
- `check_feasibility` is now a dual-mode tool: create mode and check mode (no blocking 60s poll).
- Confirmation token is Fernet-encrypted payload, not a random opaque string.
- Webhook security is layered: shared secret query param + verify-against-SkyFi-API before updating state.
- Tool summaries are agent briefing notes (dense, factual), not user-facing prose.
- Delivery credentials default to `NONE` driver (SkyFi custody + download via tool).

---

## Open Items (Post-V1)

| Item | Notes |
|------|-------|
| Fernet key rotation without token invalidation | Try decryption with old and new keys during rotation window |
| SkyFi hosted checkout migration | Drop API key from token when SkyFi offers hosted checkout (Option 3 from §1) |
| Multi-language summary support | If non-English agent users become significant |
| Webhook IP allowlist | Complement the shared-secret approach once SkyFi publishes IP ranges |
| Full webhook signature validation | Activate when SkyFi implements HMAC signatures |
