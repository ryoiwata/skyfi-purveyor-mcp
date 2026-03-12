# API Contracts & Schemas

## General Principles

- The MCP server communicates via Streamable HTTP transport (JSON-RPC over POST, optional SSE upgrade).
- All SkyFi API responses are parsed with Pydantic `extra='ignore'` for forward compatibility.
- All timestamps are ISO 8601 UTC: `2026-03-08T14:30:00+00:00`.
- All IDs are UUIDs.
- All monetary amounts are integers in cents. `$1,000.00` = `100000`.
- AOIs are WKT POLYGON strings in WGS84 (EPSG:4326).
- Authentication: `X-Skyfi-Api-Key` header (cloud) or `config.json` (local).

## MCP Tool Response Envelope

Every tool returns structured data + agent-facing summary:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Found 23 archives. Date range: 2024-01-01 to 2024-12-31. Price range: $120–$850/scene. 3 are open data (free). Highest resolution: VERY HIGH (0.5m) from PLANET."
    }
  ],
  "structuredData": {
    "archives": [...],
    "total": 23,
    "next_page": "abc123"
  },
  "isError": false
}
```

For errors:

```json
{
  "content": [
    {
      "type": "text",
      "text": "AOI exceeds maximum area of 500,000 sq km for archive searches. The provided area is 17,098,242 sq km. Provide a more specific location or use create_aoi_from_point."
    }
  ],
  "structuredData": {
    "code": "aoi_too_large",
    "message": "AOI exceeds maximum area for searches",
    "detail": {
      "max_area_sq_km": 500000,
      "actual_area_sq_km": 17098242
    }
  },
  "isError": true
}
```

## Error Codes

| Code | Category | Description |
|------|----------|-------------|
| `invalid_input` | Business | Missing or malformed tool input |
| `aoi_too_large` | Business | AOI exceeds 500k sq km search limit |
| `aoi_too_many_vertices` | Business | AOI exceeds 500 vertex limit |
| `no_results` | Business | Search returned zero matches |
| `rate_limited` | Business | Inbound rate limit exceeded |
| `skyfi_api_error` | Business | SkyFi returned 4xx (auth, budget, validation) |
| `skyfi_unavailable` | Business | SkyFi returned 5xx or timed out (retries exhausted) |
| `order_expired` | Business | Confirmation token past 30-minute TTL |
| `order_already_confirmed` | Business | Token already used |
| `order_already_cancelled` | Business | Token already cancelled |
| `order_already_placed` | Business | Cannot cancel — order placed with SkyFi |
| `feasibility_timeout` | Business | Feasibility task still pending after initial poll |
| `open_data_limit_reached` | Business | Daily open data order limit exceeded |
| `nominatim_unavailable` | Business | Geocoding service unreachable |

Infrastructure errors use JSON-RPC error codes:
- `-32603` — Internal error (unhandled exception, DB down)
- `-32601` — Method not found
- `-32602` — Invalid params

## Confirmation Page Endpoints

### Render Confirmation Page

```
GET /confirm/{token}

Response 200: HTML page showing:
  - Order type (Archive / Tasking)
  - Location description
  - Product type and resolution
  - Estimated cost (prominent)
  - How cost was calculated
  - Token expiry countdown
  - Confirm button (POST form)
  - Cancel button (POST form)

Response 400: Token invalid or malformed
Response 410: Token expired (show "This order link has expired")
Response 409: Token already used (show "This order has already been [confirmed/cancelled]")
```

### Confirm Order

```
POST /confirm/{token}
Content-Type: application/x-www-form-urlencoded
Body: action=confirm

Response 200: HTML success page with:
  - SkyFi order ID
  - Order status
  - "Your AI assistant has been notified"

Response 410: Token expired
Response 409: Already confirmed/cancelled
Response 502: SkyFi API error during order placement
```

### Cancel Order

```
POST /confirm/{token}
Content-Type: application/x-www-form-urlencoded
Body: action=cancel

Response 200: HTML page "Order cancelled. No charge will occur."
Response 410: Token expired
Response 409: Already confirmed/placed
```

## Webhook Endpoints

### Order Event

```
POST /webhooks/order-event?token={shared_secret}

Body (from SkyFi):
{
  "orderInfo": { ... },  // TaskingOrderResponse or ArchiveOrderResponse
  "event": {
    "status": "DELIVERY_COMPLETED",
    "timestamp": "2026-03-08T14:30:00Z",
    "message": null
  }
}

Processing:
1. Validate ?token matches expected shared secret → 401 if not
2. Store raw event in webhook_events table
3. Call SkyFi GET /orders/{order_id} to verify actual state
4. If verified, update local records and mark event as processed
5. If SSE stream is open for the owning API key, push notification
6. If not, event stays unprocessed for reconnect delivery

Response 200: {"status": "received"}
Response 401: Missing or invalid token
Response 429: Rate limited
```

### Archive Notification

```
POST /webhooks/archive-notification?token={shared_secret}

Body (from SkyFi):
{
  "archiveId": "uuid",
  "provider": "PLANET",
  "captureTimestamp": "2026-03-08T14:30:00Z",
  ...
  "overlapRatio": 0.85,
  "overlapSqkm": 12.5
}

Processing:
1. Validate ?token → 401 if not
2. Store in webhook_events
3. Verify archive exists via SkyFi GET /archives/{archive_id}
4. Look up owning API key via notification_registry table
5. Push to agent or queue for reconnect delivery

Response 200: {"status": "received"}
Response 401: Missing or invalid token
Response 429: Rate limited
```

## Health Endpoint

```
GET /health

Response 200:
{
  "status": "healthy",
  "database": "ok",
  "skyfi_api": "ok",
  "redis": "ok" | "skipped",
  "timestamp": "2026-03-08T14:30:00Z"
}

Response 503:
{
  "status": "degraded",
  "database": "error: connection refused",
  "skyfi_api": "ok",
  "redis": "skipped",
  "timestamp": "2026-03-08T14:30:00Z"
}
```

## SkyFi API Reference

Full spec: `docs/openapi.json`

Key endpoints used by Purveyor:

| Endpoint | Method | MCP Tool |
|----------|--------|----------|
| `/auth/whoami` | GET | `whoami` |
| `/archives` | POST | `search_archives` |
| `/archives` | GET | `search_archives` (pagination) |
| `/archives/{id}` | GET | `get_archive_details` |
| `/pricing` | POST | `get_pricing` |
| `/feasibility` | POST | `check_feasibility` |
| `/feasibility/{id}` | GET | `check_feasibility` (poll) |
| `/feasibility/pass-prediction` | POST | `get_pass_predictions` |
| `/order-tasking` | POST | confirmation flow |
| `/order-archive` | POST | confirmation flow |
| `/orders` | GET | `list_orders` |
| `/orders/{id}` | GET | `get_order_status` |
| `/orders/{id}/{type}` | GET | `download_deliverable` |
| `/orders/{id}/redelivery` | POST | `request_redelivery` |
| `/notifications` | POST | `setup_monitoring` |
| `/notifications` | GET | `list_notifications` |
| `/notifications/{id}` | GET | `get_notification_history` |
| `/notifications/{id}` | DELETE | `delete_notification` |
