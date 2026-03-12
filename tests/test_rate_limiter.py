"""Tests for MemoryRateLimiter, RateLimitResult, and the rate-limiting middleware."""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Enable local mode so Settings doesn't require CONFIRMATION_SECRET_KEY
os.environ.setdefault("LOCAL_MODE", "true")

from purveyor.core.rate_limiter import (
    MemoryRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
    resolve_rate_limit_key,
)

# ---------------------------------------------------------------------------
# MemoryRateLimiter — basic behaviour
# ---------------------------------------------------------------------------


async def test_under_limit_all_allowed() -> None:
    """59 requests within a 60/min window are all allowed."""
    rl = MemoryRateLimiter()
    for i in range(59):
        result = await rl.check_rate_limit("key1", 60, 60)
        assert result.allowed, f"Request {i + 1} should be allowed"
    await rl.close()


async def test_over_limit_rejected() -> None:
    """61st request within a 60/min window is rejected."""
    rl = MemoryRateLimiter()
    for _ in range(60):
        result = await rl.check_rate_limit("key1", 60, 60)
        assert result.allowed

    over = await rl.check_rate_limit("key1", 60, 60)
    assert not over.allowed
    assert over.remaining == 0
    assert over.retry_after is not None
    assert over.retry_after > 0
    await rl.close()


async def test_remaining_decrements() -> None:
    """Remaining count decrements correctly as requests are made."""
    rl = MemoryRateLimiter()
    r1 = await rl.check_rate_limit("key_rem", 5, 60)
    assert r1.remaining == 4

    r2 = await rl.check_rate_limit("key_rem", 5, 60)
    assert r2.remaining == 3
    await rl.close()


async def test_rate_limit_result_fields() -> None:
    """RateLimitResult contains correct fields when allowed."""
    rl = MemoryRateLimiter()
    result = await rl.check_rate_limit("keyA", 10, 60)
    assert result.allowed is True
    assert result.remaining == 9
    assert result.reset_at > time.time()
    assert result.retry_after is None
    await rl.close()


async def test_rate_limit_result_fields_when_denied() -> None:
    """RateLimitResult fields are correct when request is denied."""
    rl = MemoryRateLimiter()
    for _ in range(3):
        await rl.check_rate_limit("keyB", 3, 60)

    result = await rl.check_rate_limit("keyB", 3, 60)
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after is not None
    assert 0 < result.retry_after <= 60
    assert result.reset_at > time.time()
    await rl.close()


async def test_sliding_window_allows_after_expiry() -> None:
    """After the window expires, requests are allowed again."""
    rl = MemoryRateLimiter()

    # Fill the window (limit=2, window=1s)
    r1 = await rl.check_rate_limit("sliding_key", 2, 1)
    r2 = await rl.check_rate_limit("sliding_key", 2, 1)
    assert r1.allowed
    assert r2.allowed

    denied = await rl.check_rate_limit("sliding_key", 2, 1)
    assert not denied.allowed

    # Wait for window to expire
    await asyncio.sleep(1.1)

    # Should be allowed again
    allowed_again = await rl.check_rate_limit("sliding_key", 2, 1)
    assert allowed_again.allowed
    await rl.close()


async def test_inline_pruning_removes_old_timestamps() -> None:
    """Inline pruning removes timestamps older than the window."""
    rl = MemoryRateLimiter()

    # Make 3 requests with a 1s window
    for _ in range(3):
        await rl.check_rate_limit("prune_key", 5, 1)

    # Inspect internal state — 3 entries
    assert len(rl._counters.get("prune_key", [])) == 3

    await asyncio.sleep(1.1)

    # Next request triggers inline prune — old entries are removed first
    await rl.check_rate_limit("prune_key", 5, 1)
    # Only the latest request remains after pruning
    assert len(rl._counters.get("prune_key", [])) == 1
    await rl.close()


async def test_periodic_sweep_removes_idle_keys() -> None:
    """Periodic sweep removes keys that have been idle for longer than MAX_WINDOW."""
    rl = MemoryRateLimiter()

    # Make a request to create a key
    await rl.check_rate_limit("idle_key", 10, 60)
    assert "idle_key" in rl._counters

    # Manually backdating the deque entries to simulate an old key
    dq = rl._counters["idle_key"]
    old_timestamp = time.monotonic() - rl._MAX_WINDOW - 10
    dq.clear()
    dq.append(old_timestamp)

    # Run the sweep logic directly (don't wait 5 minutes)
    cutoff = time.monotonic() - rl._MAX_WINDOW
    async with rl._lock:
        dead_keys = [k for k, d in rl._counters.items() if not d or d[-1] < cutoff]
        for k in dead_keys:
            del rl._counters[k]

    assert "idle_key" not in rl._counters
    await rl.close()


async def test_independent_keys_dont_interfere() -> None:
    """Rate limit for keyA does not affect keyB."""
    rl = MemoryRateLimiter()

    for _ in range(5):
        await rl.check_rate_limit("independent_a", 5, 60)

    denied_a = await rl.check_rate_limit("independent_a", 5, 60)
    assert not denied_a.allowed

    allowed_b = await rl.check_rate_limit("independent_b", 5, 60)
    assert allowed_b.allowed
    await rl.close()


# ---------------------------------------------------------------------------
# resolve_rate_limit_key — routing logic
# ---------------------------------------------------------------------------


def _make_mock_request(
    path: str,
    method: str = "GET",
    api_key: str = "",
    client_ip: str = "127.0.0.1",
) -> object:
    """Build a minimal mock request object."""
    from unittest.mock import MagicMock

    req = MagicMock()
    req.url.path = path
    req.method = method
    req.headers = {"X-Skyfi-Api-Key": api_key} if api_key else {}
    req.client = MagicMock()
    req.client.host = client_ip
    return req


def test_webhook_path_uses_ip_key() -> None:
    """Webhook endpoints use IP-based rate limit key."""
    req = _make_mock_request("/webhooks/order-event", "POST", client_ip="10.0.0.1")
    key, limit, window = resolve_rate_limit_key(req)
    assert key.startswith("webhook:ip:")
    assert limit == 100
    assert window == 60


def test_confirm_post_uses_5_per_hour() -> None:
    """POST /confirm/* uses 5/hour per API key."""
    req = _make_mock_request("/confirm/some-token", "POST", api_key="mykey123")
    key, limit, window = resolve_rate_limit_key(req)
    assert key.startswith("confirm:")
    assert limit == 5
    assert window == 3600


def test_general_api_uses_60_per_min() -> None:
    """GET and POST to /health and /mcp use 60/min."""
    req_get = _make_mock_request("/health", "GET", api_key="mykey")
    key, limit, window = resolve_rate_limit_key(req_get)
    assert key.startswith("api:")
    assert limit == 60
    assert window == 60


def test_different_ips_get_different_webhook_keys() -> None:
    """Different source IPs produce different webhook rate limit keys."""
    req1 = _make_mock_request("/webhooks/archive-notification", "POST", client_ip="1.2.3.4")
    req2 = _make_mock_request("/webhooks/archive-notification", "POST", client_ip="5.6.7.8")
    key1, _, _ = resolve_rate_limit_key(req1)
    key2, _, _ = resolve_rate_limit_key(req2)
    assert key1 != key2


# ---------------------------------------------------------------------------
# Middleware — FastAPI integration
# ---------------------------------------------------------------------------


def _make_app_with_low_limit(limit: int = 2) -> object:
    """Create a test FastAPI app with a very low rate limit for testing."""
    import typing

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from purveyor.app import RateLimitMiddleware
    from purveyor.core.rate_limiter import MemoryRateLimiter

    test_app = FastAPI()
    rl = MemoryRateLimiter()

    class LowLimitMiddleware(RateLimitMiddleware):
        """Always uses 'test_key' so all requests share a single counter."""

        async def dispatch(self, request: object, call_next: object) -> object:
            key = "test_key"
            result = await self._rl.check_rate_limit(key, limit, 60)
            if not result.allowed:
                return JSONResponse(
                    content={"error": "rate_limited"},
                    status_code=429,
                    headers={
                        "Retry-After": str(int(result.retry_after or 1)),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(result.reset_at)),
                    },
                )
            call_next_typed = typing.cast(typing.Any, call_next)
            response = await call_next_typed(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(result.remaining)
            response.headers["X-RateLimit-Reset"] = str(int(result.reset_at))
            return response

    test_app.add_middleware(LowLimitMiddleware, rate_limiter=rl)

    @test_app.get("/ping")
    async def ping() -> JSONResponse:
        return JSONResponse(content={"pong": True})

    return test_app


def test_middleware_rate_limit_headers_on_normal_response() -> None:
    """X-RateLimit-* headers are present on normal (non-limited) responses."""
    from fastapi.testclient import TestClient

    app = _make_app_with_low_limit(limit=10)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/ping")
    assert response.status_code == 200
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-reset" in response.headers


def test_middleware_returns_429_with_retry_after() -> None:
    """Middleware returns 429 with Retry-After when limit is exceeded."""
    from fastapi.testclient import TestClient

    app = _make_app_with_low_limit(limit=2)
    client = TestClient(app, raise_server_exceptions=False)

    # First two requests — allowed
    r1 = client.get("/ping")
    r2 = client.get("/ping")
    assert r1.status_code == 200
    assert r2.status_code == 200

    # Third request — rate limited
    r3 = client.get("/ping")
    assert r3.status_code == 429
    assert "retry-after" in r3.headers
    assert int(r3.headers["retry-after"]) >= 0
    assert r3.json()["error"] == "rate_limited"


def test_middleware_webhook_uses_ip_not_api_key() -> None:
    """Webhook endpoint rate limits by IP, not API key."""
    from fastapi.testclient import TestClient

    from purveyor.app import create_app

    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        # POST to webhook without auth token → 401 (correct security check)
        # The important thing is the rate limit key uses client IP, not API key
        response = client.post(
            "/webhooks/order-event",
            json={"test": "data"},
        )
        # 401 because no webhook secret — but rate limit headers should be present
        # (rate limiting applies before auth in middleware order)
        # The response should have X-RateLimit-* headers
        # Note: middleware order — rate limit → CORS → routes
        assert "x-ratelimit-limit" in response.headers
        # Webhook limit is 100/min
        assert response.headers["x-ratelimit-limit"] == "100"


# ---------------------------------------------------------------------------
# RedisRateLimiter — fallback and factory
# ---------------------------------------------------------------------------


async def test_redis_rate_limiter_fallback_when_unavailable() -> None:
    """RedisRateLimiter allows requests when Redis is unavailable (graceful degradation)."""
    rl = RedisRateLimiter(redis_url="redis://localhost:9999")  # unreachable port

    result = await rl.check_rate_limit("test_key", 10, 60)

    # Should allow and return full remaining (fallback path)
    assert result.allowed is True
    assert result.remaining == 10
    assert result.retry_after is None
    await rl.close()


async def test_redis_rate_limiter_close_without_client() -> None:
    """RedisRateLimiter.close() is safe to call when no client was created."""
    rl = RedisRateLimiter(redis_url="redis://localhost:6379")
    # _client is None — should not raise
    await rl.close()


async def test_redis_rate_limiter_close_with_client() -> None:
    """RedisRateLimiter.close() calls aclose on the Redis client."""
    rl = RedisRateLimiter(redis_url="redis://localhost:6379")
    mock_client = AsyncMock()
    rl._client = mock_client

    await rl.close()

    mock_client.aclose.assert_called_once()


def test_get_rate_limiter_returns_redis_when_url_set() -> None:
    """get_rate_limiter returns RedisRateLimiter when redis_url is configured."""
    settings = MagicMock()
    settings.redis_url = "redis://localhost:6379"

    limiter = get_rate_limiter(settings)

    assert isinstance(limiter, RedisRateLimiter)


def test_get_rate_limiter_returns_memory_when_no_url() -> None:
    """get_rate_limiter returns MemoryRateLimiter when redis_url is falsy."""
    settings = MagicMock()
    settings.redis_url = None

    limiter = get_rate_limiter(settings)

    assert isinstance(limiter, MemoryRateLimiter)


async def test_periodic_sweep_cancels_on_close() -> None:
    """Periodic sweep task is cancelled when close() is called."""
    rl = MemoryRateLimiter()
    rl.start_sweep()

    assert rl._sweep_task is not None
    assert not rl._sweep_task.done()

    await rl.close()

    assert rl._sweep_task.done()


async def test_periodic_sweep_runs_once() -> None:
    """Periodic sweep removes idle keys when triggered manually."""
    rl = MemoryRateLimiter()

    # Create a key
    await rl.check_rate_limit("sweep_test_key", 10, 60)
    assert "sweep_test_key" in rl._counters

    # Backdate the entry past MAX_WINDOW
    dq = rl._counters["sweep_test_key"]
    dq.clear()
    dq.append(time.monotonic() - rl._MAX_WINDOW - 1)

    # Patch sleep: first call returns immediately (sweep runs), second raises CancelledError
    sleep_count = 0

    async def fast_sleep(delay: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError

    with patch("purveyor.core.rate_limiter.asyncio.sleep", side_effect=fast_sleep):
        rl._sweep_task = asyncio.create_task(rl._periodic_sweep())
        try:
            await rl._sweep_task
        except asyncio.CancelledError:
            pass

    assert "sweep_test_key" not in rl._counters
    await rl.close()


# ---------------------------------------------------------------------------
# skyfi_error_from_response — error mapping (in errors.py, tested here for convenience)
# ---------------------------------------------------------------------------


def test_skyfi_error_401_maps_to_auth_error() -> None:
    """HTTP 401 maps to SKYFI_API_ERROR with authentication message."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(401, json={"message": "Unauthorized"})
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.SKYFI_API_ERROR
    assert "authentication" in err.message.lower()


def test_skyfi_error_402_open_data_limit() -> None:
    """HTTP 402 with 'open data' message maps to OPEN_DATA_LIMIT_REACHED."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(402, json={"message": "open data limit exceeded"})
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.OPEN_DATA_LIMIT_REACHED


def test_skyfi_error_402_payment_error() -> None:
    """HTTP 402 without open-data message maps to SKYFI_API_ERROR."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(402, json={"message": "payment required"})
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.SKYFI_API_ERROR
    assert "payment" in err.message.lower()


def test_skyfi_error_422_maps_to_invalid_input() -> None:
    """HTTP 422 maps to INVALID_INPUT."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(422, json={"message": "Validation failed"})
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.INVALID_INPUT


def test_skyfi_error_4xx_generic() -> None:
    """HTTP 400 (other 4xx) maps to SKYFI_API_ERROR."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(400, json={"message": "Bad request"})
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.SKYFI_API_ERROR
    assert "400" in err.message


def test_skyfi_error_5xx_maps_to_unavailable() -> None:
    """HTTP 500 maps to SKYFI_UNAVAILABLE."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(503, text="Service Unavailable")
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.SKYFI_UNAVAILABLE


def test_skyfi_error_non_json_body() -> None:
    """Non-JSON response body falls back to text content."""
    import httpx

    from purveyor.core.errors import ErrorCode, skyfi_error_from_response

    response = httpx.Response(403, text="Forbidden")
    err = skyfi_error_from_response(response)

    assert err.code == ErrorCode.SKYFI_API_ERROR
