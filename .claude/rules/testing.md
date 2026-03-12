# Testing Rules

## Philosophy

Test what matters for a production-grade open source MCP server. The test suite is a key signal of project quality for evaluators and contributors.

**Test rigorously:** MCP tool handlers, SkyFi API client (mocked), confirmation token flow, webhook verification, cache behavior, rate limiting, geospatial validation, auth providers.
**Test lightly:** CLI entry points, Docker Compose orchestration, demo agent wiring.
**Don't test:** SkyFi API internals, MCP SDK internals, Fernet encryption correctness (trust the `cryptography` library).

Target: >80% line coverage. All critical paths have explicit tests.

## Framework

- **Python:** pytest + pytest-asyncio
- **HTTP mocking:** respx (for httpx async client)
- **Database:** testcontainers (Postgres+PostGIS)
- **Property testing:** hypothesis (geospatial edge cases)
- **Run:** `uv run pytest -v`
- **Coverage:** `uv run pytest --cov=src/purveyor --cov-report=term-missing`

## Directory Structure

```
tests/
├── conftest.py                    # Shared fixtures: settings, DB session, SkyFi client, auth
├── test_skyfi_client.py           # SkyFi API client — all endpoints mocked with respx
├── test_skyfi_types.py            # Pydantic model parsing (response fixtures from openapi.json)
├── test_cache.py                  # TTL cache get/set/delete/invalidation
├── test_auth.py                   # Local and cloud auth providers
├── test_rate_limiter.py           # Sliding window counters, 429 behavior
├── test_confirmation.py           # Fernet encrypt/decrypt, single-use enforcement, expiry
├── test_config.py                 # Settings loading, env var override, local config file
├── test_logging.py                # JSON output, redaction of sensitive fields
├── test_geospatial.py             # Geocoding, AOI creation, area calculation, validation
├── test_geospatial_properties.py  # hypothesis: arbitrary polygons, coordinate round-trips
├── test_archives_tool.py          # search + get_archive_details tool handlers
├── test_pricing_tool.py           # get_pricing with/without AOI
├── test_feasibility_tool.py       # check_feasibility polling, pass predictions
├── test_orders_tool.py            # list, status, download, cancel, create (with confirm flow)
├── test_notifications_tool.py     # setup/list/get/delete monitoring
├── test_account_tool.py           # whoami
├── test_resources.py              # MCP resources
├── test_webhooks.py               # Webhook receiver, verification, idempotency
├── test_tasks.py                  # Background task tracking, startup recovery
├── test_health.py                 # Health endpoint, component checks
├── test_server.py                 # MCP initialize, tools/list, basic tool call
└── test_live/                     # Live SkyFi API tests (gated)
    └── test_live_api.py           # Read-only operations against real API
```

## Required Test Cases

### Core Infrastructure

#### 1. SkyFi API Client — Happy Path
- Mock all major endpoints: search_archives, get_pricing, create_tasking_order, get_order, whoami
- Assert: correct headers sent (X-Skyfi-Api-Key), response parsed into Pydantic models, structlog entries for method/path/status/duration

#### 2. SkyFi API Client — Retry Behavior
- Mock 429 response, then 200 on retry
- Mock 500, 502, 503, 504 with eventual success
- Assert: tenacity retries with backoff, final success returned

#### 3. SkyFi API Client — Timeout and Permanent Failure
- Mock timeout, then 3 retries all fail
- Assert: appropriate exception raised, logged with context

#### 4. Cache — TTL Behavior
- Set cache entry, read immediately (hit), wait past TTL, read again (miss)
- Assert: cache returns data before TTL, returns None after

#### 5. Cache — Invalidation on Order Placement
- Cache archive search results, then place an order
- Assert: archive and pricing caches cleared for affected AOI

### Confirmation Flow (Critical)

#### 6. Token Encrypt / Decrypt Round-Trip
- Encrypt payload with API key + order params, decrypt, verify contents match
- Assert: round-trip preserves all fields

#### 7. Token Expiry
- Create token, wait past 30-minute TTL (mock time), attempt decrypt
- Assert: Fernet raises InvalidToken on expired token

#### 8. Single-Use Enforcement
- Create confirmation, confirm it (status → placed), attempt second confirmation
- Assert: second attempt returns error, no duplicate order

#### 9. Confirmation Page Renders
- GET `/confirm/{valid_token}`
- Assert: 200 response, HTML contains order details, cost, confirm/cancel buttons

#### 10. Cancel Pending Order
- Create confirmation, call `cancel_pending_order` tool
- Assert: status → cancelled, confirmation URL returns "cancelled" page

### Webhook Security

#### 11. Webhook — Valid Event with Verification
- POST to webhook endpoint with valid token, mock SkyFi API confirms the state
- Assert: event stored, local state updated

#### 12. Webhook — Fake Event Detected
- POST to webhook endpoint, mock SkyFi API returns different state than webhook claims
- Assert: fake event discarded, discrepancy logged

#### 13. Webhook — Missing Secret Token
- POST to webhook endpoint without `?token=` query param
- Assert: 401 rejected

#### 14. Webhook — Duplicate Event
- POST same event twice
- Assert: first processed, second deduplicated

### MCP Tools

#### 15. search_archives — Place Name Resolution
- Input: `location="Port of Los Angeles"`
- Assert: geocoding called, WKT polygon generated, SkyFi search called with polygon, results returned with summary

#### 16. search_archives — Oversized AOI Clipping
- Input: `location="Russia"` (returns >500k sq km bounding box)
- Assert: AOI clipped to 500k sq km centered on centroid, warning included in summary, results still returned

#### 17. check_feasibility — Async Pattern
- Mock SkyFi returns PENDING on first 2 polls, COMPLETE on third
- Assert: quick initial poll succeeds, results returned

#### 18. check_feasibility — Timeout
- Mock SkyFi always returns PENDING
- Assert: returns feasibility_id with pending status (not an error), agent can follow up

#### 19. create_tasking_order — Returns Confirmation URL
- Assert: returns confirmation_url + estimated_cost + summary, does NOT call SkyFi order endpoint

#### 20. get_order_status — Reconnect Delivery
- Store unprocessed webhook events, then simulate new session init
- Assert: pending events delivered, marked as processed

### Geospatial

#### 21. AOI Area Calculation
- Known polygons with known areas
- Assert: calculated area within 1% of expected

#### 22. WKT Validation — Exceeds Limits
- Polygon with 501 vertices, polygon with >500k sq km
- Assert: validation returns specific error messages

### Auth

#### 23. Local Auth — Reads Config File
- Assert: API key loaded from config.json, whoami called and cached

#### 24. Cloud Auth — Extracts from Headers
- Assert: API key extracted from X-Skyfi-Api-Key header, missing header returns 401

### Rate Limiting

#### 25. Inbound Rate Limit — Under Limit
- Send 59 requests in 60 seconds
- Assert: all allowed

#### 26. Inbound Rate Limit — Over Limit
- Send 61 requests in 60 seconds
- Assert: 61st returns 429 with Retry-After header

## Property-Based Tests (Hypothesis)

```python
# test_geospatial_properties.py

from hypothesis import given, strategies as st

@given(lat=st.floats(min_value=-90, max_value=90),
       lon=st.floats(min_value=-180, max_value=180),
       area=st.floats(min_value=0.01, max_value=1000))
def test_create_aoi_produces_valid_polygon(lat, lon, area):
    """Any valid lat/lon/area produces a valid WKT polygon with area close to requested."""
    result = create_aoi_from_point(lat, lon, area)
    assert result.is_valid
    assert abs(result.actual_area_sq_km - area) / area < 0.05  # within 5%

@given(wkt=st.from_regex(r'POLYGON\(\(.*\)\)', fullmatch=True))
def test_calculate_area_never_negative(wkt):
    """Area calculation never returns negative."""
    try:
        result = calculate_aoi_area(wkt)
        assert result.area_sq_km >= 0
    except ValueError:
        pass  # Invalid WKT is fine — we're testing the calculation doesn't go negative
```

## Live API Tests (Optional, Gated)

```python
# test_live/test_live_api.py

import pytest

pytestmark = pytest.mark.live

@pytest.fixture
def live_client():
    """Only runs if SKYFI_TEST_API_KEY is set."""
    key = os.environ.get("SKYFI_TEST_API_KEY")
    if not key:
        pytest.skip("SKYFI_TEST_API_KEY not set")
    return SkyFiClient(api_key=key)

async def test_whoami(live_client):
    """Verify our Pydantic model parses the real whoami response."""
    result = await live_client.whoami()
    assert result.email  # Basic shape check

async def test_search_archives(live_client):
    """Verify archive search returns parseable results."""
    result = await live_client.search_archives(GetArchivesRequest(
        aoi="POLYGON((-97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28, -97.72 30.28))",
        open_data=True,
        page_size=5,
    ))
    assert isinstance(result.archives, list)

async def test_get_pricing(live_client):
    """Verify pricing endpoint returns parseable response."""
    result = await live_client.get_pricing(None)
    assert isinstance(result, dict)
```

**Rules for live tests:**
- Read-only operations ONLY — never create orders, notifications, or any mutating calls
- Gated on `SKYFI_TEST_API_KEY` env var — skip (not fail) if missing
- Run in CI weekly via scheduled GitHub Actions workflow, not on every push
- Use Austin, TX area AOI for archive searches (SkyFi's HQ area, likely has coverage)

## Mocking Strategy

Mock at the HTTP level with `respx`, not at the service level:

```python
@pytest.fixture
def mock_skyfi(respx_mock):
    """Pre-configure common SkyFi API mocks."""
    respx_mock.get("https://app.skyfi.com/platform-api/auth/whoami").mock(
        return_value=httpx.Response(200, json={"id": "...", "email": "test@example.com", ...})
    )
    respx_mock.post("https://app.skyfi.com/platform-api/archives").mock(
        return_value=httpx.Response(200, json={"archives": [...], "total": 5})
    )
    return respx_mock
```

This tests the full client → HTTP → parse pipeline. Service-level mocks only for testing tool handlers in isolation.

## What Not to Test

- Don't test the `cryptography` library's Fernet implementation — it's well-audited.
- Don't test MCP SDK internals (transport layer, JSON-RPC parsing).
- Don't test SQLAlchemy or Alembic internals.
- Don't test the demo agent's Claude API calls (mock the MCP client side).
- Don't test Docker Compose orchestration.
- Don't test Caddy configuration.
- Don't aim for 100% coverage — aim for "every critical path works and every design decision is verified."
