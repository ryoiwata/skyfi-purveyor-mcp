"""Property-based tests for cache correctness using Hypothesis."""

from __future__ import annotations

import asyncio

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# MemoryCacheBackend — property tests
# ---------------------------------------------------------------------------


_TEXT = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
)


@given(key=_TEXT, value=st.binary(min_size=1, max_size=1024))
@hyp_settings(max_examples=50)
def test_cache_roundtrip(key: str, value: bytes) -> None:
    """Any key/value pair survives a set/get round-trip in MemoryCacheBackend."""
    from purveyor.core.cache import MemoryCacheBackend

    async def _run() -> None:
        cache = MemoryCacheBackend(max_size=500)
        await cache.set(key, value, ttl_seconds=300)
        retrieved = await cache.get(key)
        assert retrieved == value, f"Round-trip failed for key={key!r}"

    asyncio.run(_run())


@given(key=_TEXT, value=st.binary(min_size=1, max_size=256))
@hyp_settings(max_examples=30)
def test_cache_delete_removes_entry(key: str, value: bytes) -> None:
    """Deleted entries are no longer returned by get."""
    from purveyor.core.cache import MemoryCacheBackend

    async def _run() -> None:
        cache = MemoryCacheBackend(max_size=500)
        await cache.set(key, value, ttl_seconds=300)
        await cache.delete(key)
        result = await cache.get(key)
        assert result is None, f"Deleted key {key!r} still returned a value"

    asyncio.run(_run())


@given(
    keys=st.lists(_TEXT, min_size=2, max_size=20, unique=True),
    value=st.binary(min_size=1, max_size=64),
)
@hyp_settings(max_examples=30)
def test_cache_distinct_keys_independent(keys: list[str], value: bytes) -> None:
    """Distinct keys do not interfere with each other."""
    from purveyor.core.cache import MemoryCacheBackend

    async def _run() -> None:
        cache = MemoryCacheBackend(max_size=500)
        for k in keys:
            await cache.set(k, value + k.encode(), ttl_seconds=300)

        for k in keys:
            retrieved = await cache.get(k)
            assert retrieved == value + k.encode(), f"Key {k!r} returned wrong value"

    asyncio.run(_run())


def test_cache_miss_returns_none() -> None:
    """Getting a key that was never set returns None."""
    from purveyor.core.cache import MemoryCacheBackend

    async def _run() -> None:
        cache = MemoryCacheBackend(max_size=100)
        result = await cache.get("nonexistent_key_xyz")
        assert result is None

    asyncio.run(_run())


def test_cache_overwrite_returns_new_value() -> None:
    """Setting a key twice returns the second value."""
    from purveyor.core.cache import MemoryCacheBackend

    async def _run() -> None:
        cache = MemoryCacheBackend(max_size=100)
        await cache.set("k", b"first", ttl_seconds=300)
        await cache.set("k", b"second", ttl_seconds=300)
        result = await cache.get("k")
        assert result == b"second"

    asyncio.run(_run())
