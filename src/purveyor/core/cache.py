"""Tiered caching layer: in-memory TTL cache and optional Redis backend."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# CacheBackend protocol
# ---------------------------------------------------------------------------


class CacheBackend:
    """Abstract cache backend interface.

    Subclasses must implement all four async methods.
    """

    async def get(self, key: str) -> bytes | None:
        """Return cached bytes for key, or None on miss."""
        raise NotImplementedError

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        """Store value for key with the given TTL in seconds."""
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """Remove a specific key from the cache."""
        raise NotImplementedError

    async def delete_pattern(self, pattern: str) -> None:
        """Remove all keys matching a glob pattern (e.g. 'archives:*')."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class MemoryCacheBackend(CacheBackend):
    """In-memory cache backed by a dict with manual TTL tracking.

    Thread-safe for writes via asyncio.Lock.  TTL is enforced lazily on reads.
    """

    def __init__(self, max_size: int = 1000) -> None:
        """Create a new MemoryCacheBackend.

        Args:
            max_size: Maximum number of entries to keep before evicting the
                      oldest entry on insert.
        """
        self._max_size = max_size
        # Stores (value_bytes, expiry_monotonic_time)
        self._store: dict[str, tuple[bytes, float]] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, key: str) -> bool:
        """Return True if the key exists and its TTL has elapsed."""
        entry = self._store.get(key)
        if entry is None:
            return False
        _, expiry = entry
        return asyncio.get_event_loop().time() > expiry

    async def get(self, key: str) -> bytes | None:
        """Return cached bytes or None if missing / expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if asyncio.get_event_loop().time() > expiry:
            async with self._lock:
                self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        """Store value with a TTL.  Evicts oldest entry when full."""
        expiry = asyncio.get_event_loop().time() + ttl_seconds
        async with self._lock:
            # Evict oldest if at capacity
            if key not in self._store and len(self._store) >= self._max_size:
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]
            self._store[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        async with self._lock:
            self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        """Remove all keys matching a glob pattern."""
        async with self._lock:
            matching = [k for k in list(self._store.keys()) if fnmatch.fnmatch(k, pattern)]
            for k in matching:
                del self._store[k]

    def _current_keys(self) -> list[str]:
        """Return current keys (for testing)."""
        return list(self._store.keys())


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class RedisCacheBackend(CacheBackend):
    """Redis-backed cache using redis.asyncio.

    Falls back logging a warning if the connection is unavailable.
    Pattern deletion uses SCAN + DELETE to avoid blocking KEYS.
    """

    def __init__(self, redis_url: str) -> None:
        """Create a new RedisCacheBackend.

        Args:
            redis_url: Redis connection URL (e.g. redis://localhost:6379/0).
        """
        import redis.asyncio as aioredis

        self._client: aioredis.Redis = aioredis.from_url(
            redis_url, decode_responses=False
        )

    async def get(self, key: str) -> bytes | None:
        """Return cached bytes or None if missing / expired."""
        value: bytes | None = await self._client.get(key)
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        """Store value with TTL."""
        await self._client.setex(key, ttl_seconds, value)

    async def delete(self, key: str) -> None:
        """Remove a specific key."""
        await self._client.delete(key)

    async def delete_pattern(self, pattern: str) -> None:
        """Remove all keys matching a glob pattern via SCAN."""
        cursor: int = 0
        while True:
            cursor, keys = await self._client.scan(cursor, match=pattern, count=100)
            if keys:
                await self._client.delete(*keys)
            if cursor == 0:
                break

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------


def _make_cache_key(prefix: str, *args: Any, **kwargs: Any) -> str:
    """Create a deterministic cache key from a prefix and arguments.

    Args:
        prefix: Human-readable prefix (e.g. 'archives', 'pricing').
        *args, **kwargs: Serialisable values that uniquely identify the request.

    Returns:
        A string of the form ``prefix:{sha256_hex[:16]}``.
    """
    payload = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


# ---------------------------------------------------------------------------
# Cached SkyFi client
# ---------------------------------------------------------------------------


class CachedSkyFiClient:
    """Wraps SkyFiClient with TTL caching for read operations.

    Cache TTLs (from SPEC §5.3):
      - search_archives: 60 s
      - get_pricing:     300 s (5 min)
      - whoami:          300 s (5 min)
      - feasibility:     120 s (2 min)
      - geocode:         3600 s (1 hour) — used by geospatial tools

    Cache invalidation:
      - create_tasking_order / create_archive_order clear 'archives:*' and 'pricing:*'.
    """

    ARCHIVES_TTL = 60
    PRICING_TTL = 300
    WHOAMI_TTL = 300
    FEASIBILITY_TTL = 120
    GEOCODE_TTL = 3600

    def __init__(self, client: Any, cache: CacheBackend) -> None:
        """Create a CachedSkyFiClient.

        Args:
            client: A SkyFiClient instance.
            cache: A CacheBackend instance.
        """
        self._client = client
        self._cache = cache

    def _raw_client(self) -> Any:
        """Return the underlying SkyFiClient (for non-cached pass-through)."""
        return self._client

    async def _get_cached(self, key: str) -> Any | None:
        """Return the deserialized cached value, or None on miss."""
        raw = await self._cache.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def _set_cached(self, key: str, value: Any, ttl: int) -> None:
        """Serialize and cache a value."""
        await self._cache.set(key, json.dumps(value, default=str).encode(), ttl)

    # ------------------------------------------------------------------
    # Cached methods
    # ------------------------------------------------------------------

    async def search_archives(self, request: Any) -> Any:
        """search_archives with 60-second TTL cache."""
        key = _make_cache_key("archives", request.model_dump(mode="json"))
        cached = await self._get_cached(key)
        if cached is not None:
            log.debug("cache_hit", key=key)
            from purveyor.core.skyfi_types import GetArchivesResponse

            return GetArchivesResponse.model_validate(cached)
        result = await self._client.search_archives(request)
        await self._set_cached(key, result.model_dump(mode="json"), self.ARCHIVES_TTL)
        return result

    async def get_pricing(self, request: Any) -> Any:
        """get_pricing with 5-minute TTL cache."""
        aoi = request.aoi if request else None
        key = _make_cache_key("pricing", aoi)
        cached = await self._get_cached(key)
        if cached is not None:
            log.debug("cache_hit", key=key)
            return cached
        result = await self._client.get_pricing(request)
        await self._set_cached(key, result, self.PRICING_TTL)
        return result

    async def whoami(self) -> Any:
        """whoami with 5-minute TTL cache."""
        key = "whoami:current"
        cached = await self._get_cached(key)
        if cached is not None:
            log.debug("cache_hit", key=key)
            from purveyor.core.skyfi_types import WhoamiUser

            return WhoamiUser.model_validate(cached)
        result = await self._client.whoami()
        await self._set_cached(key, result.model_dump(mode="json"), self.WHOAMI_TTL)
        return result

    async def get_feasibility_status(self, feasibility_id: str) -> Any:
        """get_feasibility_status with 2-minute TTL cache."""
        key = _make_cache_key("feasibility", feasibility_id)
        cached = await self._get_cached(key)
        if cached is not None:
            log.debug("cache_hit", key=key)
            from purveyor.core.skyfi_types import FeasibilityResponse

            return FeasibilityResponse.model_validate(cached)
        result = await self._client.get_feasibility_status(feasibility_id)
        await self._set_cached(key, result.model_dump(mode="json"), self.FEASIBILITY_TTL)
        return result

    # ------------------------------------------------------------------
    # Order creation with cache invalidation
    # ------------------------------------------------------------------

    async def create_tasking_order(self, request: Any) -> Any:
        """create_tasking_order — clears archive and pricing caches after."""
        result = await self._client.create_tasking_order(request)
        await self._cache.delete_pattern("archives:*")
        await self._cache.delete_pattern("pricing:*")
        log.info("cache_invalidated", reason="tasking_order_created")
        return result

    async def create_archive_order(self, request: Any) -> Any:
        """create_archive_order — clears archive and pricing caches after."""
        result = await self._client.create_archive_order(request)
        await self._cache.delete_pattern("archives:*")
        await self._cache.delete_pattern("pricing:*")
        log.info("cache_invalidated", reason="archive_order_created")
        return result

    # ------------------------------------------------------------------
    # Pass-through methods (not cached)
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Delegate any uncached method to the underlying client."""
        return getattr(self._client, name)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_cache_backend(settings: Any) -> CacheBackend:
    """Return the configured cache backend.

    Uses Redis if settings.cache_backend == 'redis' and settings.redis_url
    is set; otherwise falls back to MemoryCacheBackend.
    """
    if getattr(settings, "cache_backend", "memory") == "redis":
        redis_url = getattr(settings, "redis_url", None)
        if redis_url:
            log.info("cache_backend", backend="redis", url=redis_url)
            return RedisCacheBackend(redis_url)
        logging.getLogger(__name__).warning(
            "cache_backend=redis but REDIS_URL is not set — using in-memory cache"
        )
    log.info("cache_backend", backend="memory")
    return MemoryCacheBackend()
