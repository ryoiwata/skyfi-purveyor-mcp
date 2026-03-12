"""Configuration management for Purveyor using Pydantic Settings."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    """All runtime configuration for Purveyor.

    Loaded from environment variables, with optional config.json overlay in local mode.
    Environment variables take precedence over config.json values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # SkyFi API
    skyfi_api_key: str | None = Field(default=None, description="SkyFi Platform API key")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///purveyor.db",
        description="SQLAlchemy async database URL",
    )

    # Redis
    redis_url: str | None = Field(default=None, description="Redis connection URL")

    # Server
    server_host: str = Field(default="0.0.0.0", description="Bind address")
    server_port: int = Field(default=8000, description="Bind port")

    # Logging
    log_level: str = Field(default="info", description="Log level (debug/info/warning/error)")
    log_format: Literal["json", "console"] = Field(
        default="json", description="Log format (json=prod, console=dev)"
    )

    # Error tracking
    sentry_dsn: str | None = Field(default=None, description="Sentry DSN for error tracking")

    # Caching
    cache_backend: Literal["memory", "redis"] = Field(
        default="memory", description="Cache backend (memory or redis)"
    )

    # Deployment mode
    local_mode: bool = Field(
        default=False, description="Local single-user mode (SQLite, no external deps)"
    )

    # Config file path (for local mode overlay)
    config_file: Path | None = Field(
        default=None, description="Path to config.json for local mode settings"
    )

    # Confirmation / security
    confirmation_secret_key: str | None = Field(
        default=None,
        description=(
            "Fernet key for confirmation token encryption. "
            "Required in cloud mode. Auto-generated ephemerally in local mode."
        ),
    )
    confirmation_base_url: str | None = Field(
        default=None,
        description="Base URL for confirmation pages (auto-detected from request if not set)",
    )
    webhook_base_url: str | None = Field(
        default=None,
        description="Base URL for webhook registration (defaults to confirmation_base_url)",
    )

    # CORS
    allowed_origins: str = Field(
        default="*",
        description="Comma-separated CORS allowed origins (default: all)",
    )

    # Geocoding
    geocoding_base_url: str = Field(
        default="https://nominatim.openstreetmap.org",
        description="Nominatim or compatible geocoding base URL",
    )

    @model_validator(mode="after")
    def _validate_cloud_mode_requirements(self) -> Settings:
        """Enforce cloud mode requirements and handle local mode key generation."""
        if not self.local_mode:
            # Cloud mode: confirmation key is required
            if not self.confirmation_secret_key:
                raise ValueError(
                    "CONFIRMATION_SECRET_KEY is required in cloud mode. "
                    "Generate one with: purveyor generate-key"
                )
        else:
            # Local mode: auto-generate an ephemeral key if not set
            if not self.confirmation_secret_key:
                self.confirmation_secret_key = Fernet.generate_key().decode()
                log.info(
                    "Using ephemeral confirmation key. "
                    "Pending order confirmations will not survive server restart. "
                    "Set CONFIRMATION_SECRET_KEY in config.json for persistent tokens."
                )
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse allowed_origins into a list."""
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def fernet_key(self) -> bytes:
        """Return the Fernet key as bytes."""
        assert self.confirmation_secret_key is not None  # guaranteed by validator
        return self.confirmation_secret_key.encode()


def _load_config_file(path: Path) -> dict[str, object]:
    """Load a JSON config file and return its contents."""
    try:
        with path.open() as f:
            return json.load(f)  # type: ignore[no-any-return]
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc


def load_settings(config_file: Path | None = None) -> Settings:
    """Load settings, optionally merging a config.json overlay.

    Priority (highest to lowest): env vars > config.json > built-in defaults.

    Args:
        config_file: Optional path to a JSON config file. When provided, its
                     values are used as defaults before env var override.
    """
    if config_file is not None and config_file.exists():
        file_values = _load_config_file(config_file)
        # Apply file values only for fields not already set via environment.
        # Pydantic Settings env vars take precedence; we set defaults for the rest.
        import os

        merged: dict[str, object] = {}
        for field_name, value in file_values.items():
            env_name = field_name.upper()
            if env_name not in os.environ:
                merged[field_name] = value
        return Settings(config_file=config_file, **merged)  # type: ignore[arg-type]
    return Settings(config_file=config_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached global Settings singleton."""
    return Settings()
