"""Inbound rate limiting for Purveyor MCP server.

Implements sliding window counters per API key or IP address.
Two backends: in-memory (default) and Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_at: float  # Unix-epoch seconds when the window resets
    retry_after: float | None  # Seconds to wait before retrying (None if allowed)


class RateLimiter(Protocol):
    """Protocol for rate limiters."""

    async def check_rate_limit(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        """Check and record a request against a sliding window.

        Args:
            key: Rate limit key (api_key_hash or IP address).
            limit: Maximum number of requests in the window.
            window_seconds: Window size in seconds.

        Returns:
            RateLimitResult describing whether the request is allowed.
        """
        ...

    async def close(self) -> None:
        """Release resources (connections, background tasks)."""
        ...


class MemoryRateLimiter:
    """Sliding window rate limiter backed by in-memory deques of timestamps.

    Per Design Decision §16: inline pruning on every check, plus a periodic
    background sweep every 5 minutes to drop fully-idle keys.
    """

    #: Longest window in use — order confirmations are 1 hour.
    _MAX_WINDOW: int = 3600

    def __init__(self) -> None:
        self._counters: dict[str, deque[float]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._sweep_task: asyncio.Task[None] | None = None

    def start_sweep(self) -> None:
        """Start the periodic sweep task.

        Must be called after an event loop is running (e.g., from a FastAPI
        lifespan handler).
        """
        self._sweep_task = asyncio.create_task(self._periodic_sweep())

    async def _periodic_sweep(self) -> None:
        """Every 5 minutes, drop keys whose newest timestamp is older than MAX_WINDOW."""
        while True:
            await asyncio.sleep(300)  # 5 minutes
            cutoff = time.monotonic() - self._MAX_WINDOW
            async with self._lock:
                dead_keys = [
                    k for k, dq in self._counters.items() if not dq or dq[-1] < cutoff
                ]
                for k in dead_keys:
                    del self._counters[k]
            if dead_keys:
                log.debug("rate_limiter_sweep_completed", removed_keys=len(dead_keys))

    async def check_rate_limit(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        """Check and record a request against a sliding window.

        Inline-prunes expired timestamps before checking the count.  When no
        timestamps remain after pruning, the key is removed entirely.

        Args:
            key: Rate limit key.
            limit: Maximum allowed requests in the window.
            window_seconds: Window size in seconds.

        Returns:
            RateLimitResult with allowed/remaining/reset_at/retry_after.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        async with self._lock:
            dq = self._counters.get(key)
            if dq is None:
                dq = deque()
                self._counters[key] = dq

            # Inline prune — remove all entries older than the window
            while dq and dq[0] < cutoff:
                dq.popleft()

            count = len(dq)

            if count >= limit:
                # Rate limited — oldest entry determines when the window resets
                oldest = dq[0]
                reset_at_mono = oldest + window_seconds
                retry_after = max(0.0, reset_at_mono - now)
                # Convert monotonic → wall-clock for the reset_at value
                reset_at_wall = time.time() + retry_after
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=reset_at_wall,
                    retry_after=retry_after,
                )

            # Allowed — record this timestamp
            dq.append(now)
            remaining = limit - len(dq)

            # reset_at: when the oldest entry in the current window expires
            oldest_now = dq[0]
            reset_at_mono = oldest_now + window_seconds
            reset_at_wall = time.time() + max(0.0, reset_at_mono - now)

        return RateLimitResult(
            allowed=True,
            remaining=remaining,
            reset_at=reset_at_wall,
            retry_after=None,
        )

    async def close(self) -> None:
        """Cancel the background sweep task."""
        if self._sweep_task is not None and not self._sweep_task.done():
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass


class RedisRateLimiter:
    """Sliding window rate limiter backed by Redis sorted sets.

    Falls back to allowing the request (with a warning log) if Redis is
    unavailable, so a Redis outage never hard-blocks legitimate traffic.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def check_rate_limit(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        """Check rate limit using a Redis sorted-set sliding window.

        Algorithm:
        1. ZREMRANGEBYSCORE to prune old entries
        2. ZADD current_time as both score and (unique) member
        3. ZCARD to get current count
        4. EXPIRE to bound key lifetime
        If count > limit, remove the entry we just added and return denied.

        Args:
            key: Rate limit key.
            limit: Maximum allowed requests in the window.
            window_seconds: Window size in seconds.

        Returns:
            RateLimitResult.
        """
        try:
            r = await self._get_client()
            now = time.time()
            cutoff = now - window_seconds
            member = f"{now}:{uuid.uuid4().hex}"
            redis_key = f"ratelimit:{key}:{window_seconds}"

            async with r.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, "-inf", cutoff)
                pipe.zadd(redis_key, {member: now})
                pipe.zcard(redis_key)
                pipe.expire(redis_key, window_seconds + 1)
                results = await pipe.execute()

            count: int = int(results[2])

            if count > limit:
                # Over limit — remove the entry we just added
                await r.zrem(redis_key, member)
                oldest_entries = await r.zrange(redis_key, 0, 0, withscores=True)
                oldest_score = float(oldest_entries[0][1]) if oldest_entries else now
                reset_at = oldest_score + window_seconds
                retry_after = max(0.0, reset_at - time.time())
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after=retry_after,
                )

            remaining = limit - count
            oldest_entries = await r.zrange(redis_key, 0, 0, withscores=True)
            oldest_score = float(oldest_entries[0][1]) if oldest_entries else now
            reset_at = oldest_score + window_seconds

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=None,
            )

        except Exception as exc:
            log.warning(
                "redis_rate_limiter_error",
                error=str(exc),
                key=key,
            )
            # Fallback: allow the request when Redis is unavailable
            return RateLimitResult(
                allowed=True,
                remaining=limit,
                reset_at=time.time() + window_seconds,
                retry_after=None,
            )

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.aclose()


def get_rate_limiter(settings: Any) -> MemoryRateLimiter | RedisRateLimiter:
    """Return the appropriate rate limiter based on settings.

    Args:
        settings: Settings instance with redis_url attribute.

    Returns:
        RedisRateLimiter if redis_url is set, else MemoryRateLimiter.
    """
    if settings.redis_url:
        return RedisRateLimiter(redis_url=settings.redis_url)
    return MemoryRateLimiter()


def _hash_key(value: str) -> str:
    """Return a short SHA-256 hex prefix of value for use as a rate limit key component."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def resolve_rate_limit_key(request: Any) -> tuple[str, int, int]:
    """Determine the rate limit key, limit, and window for a request.

    Tiered limits per SPEC §6.1 and security.md:
    - Webhook endpoints: 100/min per source IP (unauthenticated inbound)
    - POST /confirm/*: 5/hour per API key (order confirmation guard)
    - GET *: 60/min per API key (read operations)
    - All other methods (POST /mcp, etc.): 60/min per API key
      (reads dominate MCP traffic; destructive ops are guarded by the
       confirmation flow which is independently rate-limited)

    Args:
        request: Starlette/FastAPI Request object.

    Returns:
        Tuple of (rate_limit_key, limit, window_seconds).
    """
    path: str = request.url.path
    method: str = request.method.upper()

    if path.startswith("/webhooks/"):
        # IP-based — 100 requests per minute
        client_ip: str = (
            request.client.host if request.client else "unknown"
        )
        key = f"webhook:ip:{_hash_key(client_ip)}"
        return key, 100, 60

    api_key: str = request.headers.get("X-Skyfi-Api-Key", "")
    ident = _hash_key(api_key) if api_key else _hash_key(
        request.client.host if request.client else "unknown"
    )

    if method == "POST" and path.startswith("/confirm/"):
        # Order confirmations — 5 per hour per API key
        key = f"confirm:{ident}"
        return key, 5, 3600

    # All other requests — 60 per minute (reads dominate; writes are guarded
    # by the confirmation flow)
    key = f"api:{ident}"
    return key, 60, 60
