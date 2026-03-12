"""Tests for authentication providers."""

from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from purveyor.core.auth import (
    CloudHeaderAuthProvider,
    LocalFileAuthProvider,
    UserContext,
    get_auth_provider,
)


def _mock_whoami(email: str = "test@example.com") -> MagicMock:
    """Return a mock WhoamiUser-like object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    return user


# ---------------------------------------------------------------------------
# UserContext
# ---------------------------------------------------------------------------


def test_user_context_from_api_key_computes_hash() -> None:
    """UserContext.from_api_key computes the correct SHA-256 hash."""
    api_key = "sk-test-1234567890"
    ctx = UserContext.from_api_key(api_key)
    expected_hash = hashlib.sha256(api_key.encode()).hexdigest()
    assert ctx.api_key == api_key
    assert ctx.api_key_hash == expected_hash


def test_user_context_hash_is_sha256() -> None:
    """api_key_hash is a 64-character hex string (SHA-256)."""
    ctx = UserContext.from_api_key("any-key")
    assert len(ctx.api_key_hash) == 64
    int(ctx.api_key_hash, 16)  # must parse as hex


# ---------------------------------------------------------------------------
# LocalFileAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_auth_returns_configured_key() -> None:
    """LocalFileAuthProvider.get_api_key returns the configured key."""
    mock_client = AsyncMock()
    provider = LocalFileAuthProvider(api_key="local-key-abc", cached_client=mock_client)
    key = await provider.get_api_key({})
    assert key == "local-key-abc"


@pytest.mark.asyncio
async def test_local_auth_ignores_request_context() -> None:
    """LocalFileAuthProvider ignores headers in request_context."""
    mock_client = AsyncMock()
    provider = LocalFileAuthProvider(api_key="my-key", cached_client=mock_client)
    # Even if headers contain a different key, local auth uses its own
    key = await provider.get_api_key({"headers": {"x-skyfi-api-key": "other-key"}})
    assert key == "my-key"


@pytest.mark.asyncio
async def test_local_auth_validate_request_populates_user_info() -> None:
    """validate_request populates user_id and email via whoami."""
    mock_client = AsyncMock()
    whoami_result = _mock_whoami("alice@example.com")
    mock_client.whoami = AsyncMock(return_value=whoami_result)

    provider = LocalFileAuthProvider(api_key="sk-local", cached_client=mock_client)
    ctx = await provider.validate_request({})

    assert ctx.api_key == "sk-local"
    assert ctx.email == "alice@example.com"
    assert ctx.user_id == str(whoami_result.id)
    mock_client.whoami.assert_called_once()


@pytest.mark.asyncio
async def test_local_auth_validate_request_survives_whoami_failure() -> None:
    """validate_request returns partial context if whoami fails."""
    mock_client = AsyncMock()
    mock_client.whoami = AsyncMock(side_effect=Exception("network error"))

    provider = LocalFileAuthProvider(api_key="sk-local", cached_client=mock_client)
    ctx = await provider.validate_request({})

    # Key and hash should be set even if whoami fails
    assert ctx.api_key == "sk-local"
    assert ctx.email is None
    assert ctx.user_id is None


# ---------------------------------------------------------------------------
# CloudHeaderAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_auth_extracts_header() -> None:
    """CloudHeaderAuthProvider extracts X-Skyfi-Api-Key from headers."""
    factory = MagicMock()
    provider = CloudHeaderAuthProvider(cached_client_factory=factory)

    request_context = {"headers": {"x-skyfi-api-key": "cloud-key-xyz"}}
    key = await provider.get_api_key(request_context)
    assert key == "cloud-key-xyz"


@pytest.mark.asyncio
async def test_cloud_auth_extracts_mixed_case_header() -> None:
    """CloudHeaderAuthProvider handles mixed-case header names."""
    factory = MagicMock()
    provider = CloudHeaderAuthProvider(cached_client_factory=factory)

    request_context = {"headers": {"X-Skyfi-Api-Key": "cloud-key-mixed"}}
    key = await provider.get_api_key(request_context)
    assert key == "cloud-key-mixed"


@pytest.mark.asyncio
async def test_cloud_auth_raises_on_missing_header() -> None:
    """CloudHeaderAuthProvider raises ValueError when header is absent."""
    factory = MagicMock()
    provider = CloudHeaderAuthProvider(cached_client_factory=factory)

    with pytest.raises(ValueError, match="X-Skyfi-Api-Key"):
        await provider.get_api_key({"headers": {}})


@pytest.mark.asyncio
async def test_cloud_auth_raises_on_missing_headers_key() -> None:
    """CloudHeaderAuthProvider raises when request_context has no headers."""
    factory = MagicMock()
    provider = CloudHeaderAuthProvider(cached_client_factory=factory)

    with pytest.raises(ValueError, match="X-Skyfi-Api-Key"):
        await provider.get_api_key({})


@pytest.mark.asyncio
async def test_cloud_auth_validate_request_calls_whoami() -> None:
    """validate_request calls whoami on the per-key client."""
    whoami_user = _mock_whoami("bob@example.com")
    mock_client = AsyncMock()
    mock_client.whoami = AsyncMock(return_value=whoami_user)

    factory = MagicMock(return_value=mock_client)
    provider = CloudHeaderAuthProvider(cached_client_factory=factory)

    ctx = await provider.validate_request({"headers": {"x-skyfi-api-key": "cloud-key-abc"}})

    assert ctx.api_key == "cloud-key-abc"
    assert ctx.email == "bob@example.com"
    assert ctx.user_id == str(whoami_user.id)
    # Verify factory was called with the extracted key
    factory.assert_called_once_with("cloud-key-abc")


@pytest.mark.asyncio
async def test_cloud_auth_validate_request_handles_whoami_failure() -> None:
    """validate_request returns partial context if whoami fails."""
    mock_client = AsyncMock()
    mock_client.whoami = AsyncMock(side_effect=Exception("timeout"))

    factory = MagicMock(return_value=mock_client)
    provider = CloudHeaderAuthProvider(cached_client_factory=factory)

    ctx = await provider.validate_request({"headers": {"x-skyfi-api-key": "cloud-key"}})

    assert ctx.api_key == "cloud-key"
    assert ctx.email is None


# ---------------------------------------------------------------------------
# get_auth_provider factory
# ---------------------------------------------------------------------------


def test_get_auth_provider_returns_local_in_local_mode() -> None:
    """get_auth_provider returns LocalFileAuthProvider in local mode."""
    settings = MagicMock()
    settings.local_mode = True
    settings.skyfi_api_key = "local-key"

    provider = get_auth_provider(settings, cached_client=AsyncMock())
    assert isinstance(provider, LocalFileAuthProvider)


def test_get_auth_provider_returns_cloud_in_cloud_mode() -> None:
    """get_auth_provider returns CloudHeaderAuthProvider in cloud mode."""
    settings = MagicMock()
    settings.local_mode = False

    provider = get_auth_provider(settings, cached_client=AsyncMock())
    assert isinstance(provider, CloudHeaderAuthProvider)
