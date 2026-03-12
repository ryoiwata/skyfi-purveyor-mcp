"""Authentication provider interface for Purveyor.

Two implementations:
- LocalFileAuthProvider: reads a single API key from Settings (local mode).
- CloudHeaderAuthProvider: extracts X-Skyfi-Api-Key from per-request headers (cloud mode).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# UserContext
# ---------------------------------------------------------------------------


@dataclass
class UserContext:
    """Resolved identity for an authenticated request.

    api_key_hash is stored for correlation in logs and database records —
    the raw api_key is never written to any persistent store.
    """

    api_key: str
    api_key_hash: str  # SHA-256 hex digest of api_key
    user_id: str | None = field(default=None)
    email: str | None = field(default=None)

    @classmethod
    def from_api_key(cls, api_key: str) -> UserContext:
        """Create a UserContext with the hash computed from api_key."""
        digest = hashlib.sha256(api_key.encode()).hexdigest()
        return cls(api_key=api_key, api_key_hash=digest)


# ---------------------------------------------------------------------------
# AuthProvider protocol
# ---------------------------------------------------------------------------


class AuthProvider(Protocol):
    """Interface all auth provider implementations must satisfy."""

    async def get_api_key(self, request_context: dict[str, Any]) -> str:
        """Extract or return the SkyFi API key for this request."""
        ...

    async def validate_request(self, request_context: dict[str, Any]) -> UserContext:
        """Validate the request and return a populated UserContext."""
        ...


# ---------------------------------------------------------------------------
# LocalFileAuthProvider
# ---------------------------------------------------------------------------


class LocalFileAuthProvider:
    """Auth provider for local single-user deployments.

    Reads the API key from Settings.skyfi_api_key (set via env var or config.json).
    Always returns the same key; no multi-tenancy.
    """

    def __init__(self, api_key: str, cached_client: Any) -> None:
        """Create a LocalFileAuthProvider.

        Args:
            api_key: The configured SkyFi API key.
            cached_client: A CachedSkyFiClient (or compatible) for whoami lookups.
        """
        self._api_key = api_key
        self._cached_client = cached_client

    async def get_api_key(self, request_context: dict[str, Any]) -> str:
        """Return the configured API key (ignores request context)."""
        return self._api_key

    async def validate_request(self, request_context: dict[str, Any]) -> UserContext:
        """Return UserContext, enriching it with whoami user info when available."""
        context = UserContext.from_api_key(self._api_key)
        try:
            user = await self._cached_client.whoami()
            context.user_id = str(user.id)
            context.email = user.email
        except Exception as exc:
            log.warning("whoami_failed", reason=str(exc))
        return context


# ---------------------------------------------------------------------------
# CloudHeaderAuthProvider
# ---------------------------------------------------------------------------


class CloudHeaderAuthProvider:
    """Auth provider for cloud multi-tenant deployments.

    Extracts the API key from the ``X-Skyfi-Api-Key`` request header.
    Each request may carry a different key.
    """

    HEADER_NAME = "x-skyfi-api-key"

    def __init__(self, cached_client_factory: Any) -> None:
        """Create a CloudHeaderAuthProvider.

        Args:
            cached_client_factory: A callable that accepts an API key and returns
                a CachedSkyFiClient (or compatible) for whoami lookups.
        """
        self._client_factory = cached_client_factory

    async def get_api_key(self, request_context: dict[str, Any]) -> str:
        """Extract X-Skyfi-Api-Key from request headers.

        Args:
            request_context: Dict with a ``headers`` key mapping header names
                             (lowercase) to values.

        Raises:
            ValueError: If the X-Skyfi-Api-Key header is missing.
        """
        headers: dict[str, str] = request_context.get("headers", {})
        # Headers may be provided with original or lowercase names
        key = headers.get(self.HEADER_NAME) or headers.get("X-Skyfi-Api-Key")
        if not key:
            raise ValueError(
                "Missing required header: X-Skyfi-Api-Key. "
                "Provide your SkyFi API key in the X-Skyfi-Api-Key request header."
            )
        return key

    async def validate_request(self, request_context: dict[str, Any]) -> UserContext:
        """Validate the request and return a UserContext with whoami data."""
        api_key = await self.get_api_key(request_context)
        context = UserContext.from_api_key(api_key)
        try:
            client = self._client_factory(api_key)
            user = await client.whoami()
            context.user_id = str(user.id)
            context.email = user.email
        except Exception as exc:
            log.warning("whoami_failed", reason=str(exc), api_key_hash=context.api_key_hash)
        return context


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_auth_provider(settings: Any, cached_client: Any) -> AuthProvider:
    """Return the appropriate AuthProvider based on settings.

    Args:
        settings: A Settings instance.
        cached_client: A CachedSkyFiClient or compatible object for whoami.

    Returns:
        LocalFileAuthProvider in local mode, CloudHeaderAuthProvider otherwise.
    """
    if settings.local_mode:
        api_key = settings.skyfi_api_key or ""
        if not api_key:
            log.warning("local_mode_missing_api_key")
        return LocalFileAuthProvider(api_key=api_key, cached_client=cached_client)

    return CloudHeaderAuthProvider(cached_client_factory=cached_client)
