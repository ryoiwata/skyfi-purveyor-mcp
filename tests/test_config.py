"""Tests for configuration management."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from purveyor.core.config import Settings, _load_config_file, load_settings


class TestDefaultValues:
    """Tests for default configuration values."""

    def test_default_database_url(self) -> None:
        """Default database URL is SQLite."""
        settings = Settings(local_mode=True)
        assert "sqlite" in settings.database_url

    def test_default_server_port(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.server_port == 8000

    def test_default_server_host(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.server_host == "0.0.0.0"

    def test_default_log_level(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.log_level == "info"

    def test_default_log_format(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.log_format == "json"

    def test_default_cache_backend(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.cache_backend == "memory"

    def test_default_allowed_origins(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.allowed_origins == "*"

    def test_allowed_origins_list_star(self) -> None:
        settings = Settings(local_mode=True)
        assert settings.allowed_origins_list == ["*"]

    def test_allowed_origins_list_parsed(self) -> None:
        settings = Settings(local_mode=True, allowed_origins="https://a.com,https://b.com")
        assert settings.allowed_origins_list == ["https://a.com", "https://b.com"]


class TestLocalMode:
    """Tests for local mode behavior."""

    def test_local_mode_generates_ephemeral_key(self) -> None:
        """Local mode auto-generates a Fernet key when none is provided."""
        settings = Settings(local_mode=True, confirmation_secret_key=None)
        assert settings.confirmation_secret_key is not None
        assert len(settings.confirmation_secret_key) > 0

    def test_local_mode_each_instance_gets_unique_key(self) -> None:
        """Each Settings instance in local mode gets its own ephemeral key."""
        s1 = Settings(local_mode=True, confirmation_secret_key=None)
        s2 = Settings(local_mode=True, confirmation_secret_key=None)
        assert s1.confirmation_secret_key != s2.confirmation_secret_key

    def test_local_mode_explicit_key_preserved(self) -> None:
        """Explicit key is not overwritten in local mode."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        settings = Settings(local_mode=True, confirmation_secret_key=key)
        assert settings.confirmation_secret_key == key


class TestCloudMode:
    """Tests for cloud mode requirements."""

    def test_cloud_mode_requires_confirmation_key(self) -> None:
        """Cloud mode refuses to start without CONFIRMATION_SECRET_KEY."""
        with pytest.raises(Exception, match="CONFIRMATION_SECRET_KEY"):
            Settings(local_mode=False, confirmation_secret_key=None)

    def test_cloud_mode_starts_with_key(self) -> None:
        """Cloud mode starts successfully when key is provided."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        settings = Settings(local_mode=False, confirmation_secret_key=key)
        assert settings.confirmation_secret_key == key

    def test_fernet_key_property_returns_bytes(self) -> None:
        """fernet_key property returns bytes."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        settings = Settings(local_mode=True, confirmation_secret_key=key)
        assert isinstance(settings.fernet_key, bytes)


class TestEnvVarOverride:
    """Tests for environment variable override."""

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables override default values."""
        monkeypatch.setenv("SERVER_PORT", "9090")
        monkeypatch.setenv("LOG_LEVEL", "debug")
        settings = Settings(local_mode=True)
        assert settings.server_port == 9090
        assert settings.log_level == "debug"

    def test_skyfi_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SKYFI_API_KEY is loaded from environment."""
        monkeypatch.setenv("SKYFI_API_KEY", "test-key-abc")
        settings = Settings(local_mode=True)
        assert settings.skyfi_api_key == "test-key-abc"


class TestConfigFileLoading:
    """Tests for config.json file loading in local mode."""

    def test_load_config_file_parses_json(self, tmp_path: Path) -> None:
        """Config file values are loaded from JSON."""
        config = {"server_port": 7777, "log_level": "debug"}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        values = _load_config_file(config_path)
        assert values["server_port"] == 7777
        assert values["log_level"] == "debug"

    def test_load_config_file_missing_returns_empty(self, tmp_path: Path) -> None:
        """Missing config file returns empty dict."""
        values = _load_config_file(tmp_path / "nonexistent.json")
        assert values == {}

    def test_load_config_file_invalid_json_raises(self, tmp_path: Path) -> None:
        """Invalid JSON raises ValueError."""
        config_path = tmp_path / "bad.json"
        config_path.write_text("{ not valid json }")
        with pytest.raises(ValueError, match="Invalid JSON"):
            _load_config_file(config_path)

    def test_load_settings_with_config_file(self, tmp_path: Path) -> None:
        """load_settings reads values from config file."""
        config = {"server_port": 8888, "local_mode": True}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        settings = load_settings(config_file=config_path)
        assert settings.server_port == 8888

    def test_env_var_overrides_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables take precedence over config file values."""
        config = {"server_port": 8888, "local_mode": True}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        monkeypatch.setenv("SERVER_PORT", "9999")
        settings = load_settings(config_file=config_path)
        assert settings.server_port == 9999
