"""Tests for the tiered cache layer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from purveyor.core.cache import CachedSkyFiClient, MemoryCacheBackend, _make_cache_key


# ---------------------------------------------------------------------------
# MemoryCacheBackend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_cache_set_and_get() -> None:
    """Basic set then get returns stored value."""
    cache = MemoryCacheBackend()
    await cache.set("key1", b"hello", ttl_seconds=60)
    result = await cache.get("key1")
    assert result == b"hello"


@pytest.mark.asyncio
async def test_memory_cache_miss_returns_none() -> None:
    """get on missing key returns None."""
    cache = MemoryCacheBackend()
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_memory_cache_delete() -> None:
    """delete removes the key."""
    cache = MemoryCacheBackend()
    await cache.set("key1", b"data", ttl_seconds=60)
    await cache.delete("key1")
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_memory_cache_delete_pattern() -> None:
    """delete_pattern removes all matching keys."""
    cache = MemoryCacheBackend()
    await cache.set("archives:abc", b"1", ttl_seconds=60)
    await cache.set("archives:def", b"2", ttl_seconds=60)
    await cache.set("pricing:xyz", b"3", ttl_seconds=60)

    await cache.delete_pattern("archives:*")

    assert await cache.get("archives:abc") is None
    assert await cache.get("archives:def") is None
    assert await cache.get("pricing:xyz") == b"3"  # unaffected


@pytest.mark.asyncio
async def test_memory_cache_ttl_expiry() -> None:
    """Entries expire after their TTL elapses."""
    cache = MemoryCacheBackend()
    # Manually set an entry with a past expiry time
    loop = asyncio.get_event_loop()
    cache._store["expired_key"] = (b"old_data", loop.time() - 1)  # already expired
    result = await cache.get("expired_key")
    assert result is None


@pytest.mark.asyncio
async def test_memory_cache_max_size_eviction() -> None:
    """When max_size is reached, the oldest entry is evicted."""
    cache = MemoryCacheBackend(max_size=3)
    await cache.set("a", b"1", ttl_seconds=60)
    await cache.set("b", b"2", ttl_seconds=60)
    await cache.set("c", b"3", ttl_seconds=60)
    await cache.set("d", b"4", ttl_seconds=60)  # triggers eviction of "a"

    # "a" should be evicted, "b", "c", "d" should remain
    assert await cache.get("a") is None
    assert await cache.get("b") == b"2"
    assert await cache.get("c") == b"3"
    assert await cache.get("d") == b"4"


@pytest.mark.asyncio
async def test_memory_cache_overwrite_does_not_evict() -> None:
    """Overwriting an existing key doesn't evict another entry."""
    cache = MemoryCacheBackend(max_size=2)
    await cache.set("a", b"1", ttl_seconds=60)
    await cache.set("b", b"2", ttl_seconds=60)
    await cache.set("a", b"updated", ttl_seconds=60)  # overwrite, not new

    assert await cache.get("a") == b"updated"
    assert await cache.get("b") == b"2"


# ---------------------------------------------------------------------------
# Cache key generation
# ---------------------------------------------------------------------------


def test_make_cache_key_deterministic() -> None:
    """Same inputs always produce the same cache key."""
    key1 = _make_cache_key("test", "arg1", foo="bar")
    key2 = _make_cache_key("test", "arg1", foo="bar")
    assert key1 == key2


def test_make_cache_key_distinct_for_different_inputs() -> None:
    """Different inputs produce different cache keys."""
    key1 = _make_cache_key("archives", "POLYGON((0 0, 1 0))")
    key2 = _make_cache_key("archives", "POLYGON((1 1, 2 0))")
    assert key1 != key2


def test_make_cache_key_includes_prefix() -> None:
    """Cache key includes the prefix."""
    key = _make_cache_key("archives", "some_value")
    assert key.startswith("archives:")


# ---------------------------------------------------------------------------
# CachedSkyFiClient — cache hit/miss
# ---------------------------------------------------------------------------


def _make_cached_client(
    cache: MemoryCacheBackend | None = None,
) -> tuple[CachedSkyFiClient, AsyncMock, MemoryCacheBackend]:
    """Create a CachedSkyFiClient with a mocked underlying client."""
    mock_client = AsyncMock()
    if cache is None:
        cache = MemoryCacheBackend()
    cached = CachedSkyFiClient(mock_client, cache)
    return cached, mock_client, cache


@pytest.mark.asyncio
async def test_whoami_cached_on_second_call() -> None:
    """whoami caches the result and skips the underlying call on second hit."""
    from purveyor.core.skyfi_types import WhoamiUser
    import uuid

    whoami_data = WhoamiUser(
        id=uuid.uuid4(),
        email="test@example.com",
        firstName="Test",
        lastName="User",
        isDemoAccount=False,
        currentBudgetUsage=0,
        budgetAmount=100000,
        hasValidSharedCard=True,
    )

    cached, mock_client, _ = _make_cached_client()
    mock_client.whoami = AsyncMock(return_value=whoami_data)

    # First call — hits the real client
    result1 = await cached.whoami()
    assert mock_client.whoami.call_count == 1

    # Second call — should come from cache
    result2 = await cached.whoami()
    assert mock_client.whoami.call_count == 1  # still 1!
    assert result2.email == result1.email


@pytest.mark.asyncio
async def test_search_archives_cached() -> None:
    """search_archives caches results by request params."""
    from purveyor.core.skyfi_types import GetArchivesRequest, GetArchivesResponse

    req = GetArchivesRequest(aoi="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")
    mock_response = MagicMock(spec=GetArchivesResponse)
    mock_response.model_dump = MagicMock(return_value={"archives": [], "nextPage": None})

    # model_validate must return the same type
    with patch.object(GetArchivesResponse, "model_validate", return_value=mock_response):
        cached, mock_client, _ = _make_cached_client()
        mock_client.search_archives = AsyncMock(return_value=mock_response)

        await cached.search_archives(req)
        await cached.search_archives(req)

        assert mock_client.search_archives.call_count == 1


@pytest.mark.asyncio
async def test_cache_miss_calls_underlying_client() -> None:
    """On cache miss, the underlying client is called."""
    from purveyor.core.skyfi_types import WhoamiUser
    import uuid

    whoami_data = WhoamiUser(
        id=uuid.uuid4(),
        email="user@example.com",
        firstName="User",
        lastName="One",
        isDemoAccount=False,
        currentBudgetUsage=0,
        budgetAmount=100000,
        hasValidSharedCard=True,
    )

    cached, mock_client, _ = _make_cached_client()
    mock_client.whoami = AsyncMock(return_value=whoami_data)

    result = await cached.whoami()
    assert mock_client.whoami.call_count == 1
    assert result.email == "user@example.com"


# ---------------------------------------------------------------------------
# Cache invalidation on order placement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tasking_order_invalidates_archive_cache() -> None:
    """Creating a tasking order clears the archives cache."""
    from purveyor.core.skyfi_types import (
        GetArchivesRequest,
        GetArchivesResponse,
        TaskingOrderRequest,
        TaskingOrderResponse,
        ProductType,
        DeliveryStatus,
        OrderType,
    )
    from datetime import datetime, timezone
    import uuid

    cache = MemoryCacheBackend()
    # Pre-seed the archives cache
    await cache.set("archives:abc123", b'{"archives":[]}', ttl_seconds=60)
    await cache.set("pricing:xyz", b'{"data": {}}', ttl_seconds=60)

    cached, mock_client, _ = _make_cached_client(cache=cache)

    order_response = MagicMock()
    mock_client.create_tasking_order = AsyncMock(return_value=order_response)

    req = MagicMock()
    await cached.create_tasking_order(req)

    # Archive and pricing caches should be cleared
    assert await cache.get("archives:abc123") is None
    assert await cache.get("pricing:xyz") is None


@pytest.mark.asyncio
async def test_create_archive_order_invalidates_caches() -> None:
    """Creating an archive order clears archive and pricing caches."""
    cache = MemoryCacheBackend()
    await cache.set("archives:abc", b"data", ttl_seconds=60)
    await cache.set("pricing:def", b"prices", ttl_seconds=60)

    cached, mock_client, _ = _make_cached_client(cache=cache)
    mock_client.create_archive_order = AsyncMock(return_value=MagicMock())

    await cached.create_archive_order(MagicMock())

    assert await cache.get("archives:abc") is None
    assert await cache.get("pricing:def") is None


# ---------------------------------------------------------------------------
# Pass-through for uncached methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uncached_method_delegates_to_client() -> None:
    """Methods not overridden in CachedSkyFiClient delegate to underlying client."""
    cached, mock_client, _ = _make_cached_client()
    mock_client.get_archive = AsyncMock(return_value="archive_data")

    result = await cached.get_archive("archive-123")
    assert result == "archive_data"
    mock_client.get_archive.assert_called_once_with("archive-123")


# ---------------------------------------------------------------------------
# get_cache_backend factory
# ---------------------------------------------------------------------------


def test_get_cache_backend_returns_memory_by_default() -> None:
    """get_cache_backend returns MemoryCacheBackend when cache_backend=memory."""
    from purveyor.core.cache import get_cache_backend

    settings = MagicMock()
    settings.cache_backend = "memory"
    settings.redis_url = None

    backend = get_cache_backend(settings)
    assert isinstance(backend, MemoryCacheBackend)


def test_get_cache_backend_falls_back_when_redis_url_missing() -> None:
    """get_cache_backend falls back to memory when Redis URL is absent."""
    from purveyor.core.cache import get_cache_backend

    settings = MagicMock()
    settings.cache_backend = "redis"
    settings.redis_url = None

    backend = get_cache_backend(settings)
    assert isinstance(backend, MemoryCacheBackend)
