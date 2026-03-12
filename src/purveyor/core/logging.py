"""Structured logging configuration for Purveyor using structlog."""

from __future__ import annotations

import logging
import os
from typing import Any

import structlog

# Fields that must never appear in log output
_SENSITIVE_FIELDS = frozenset(
    {
        "api_key",
        "secret_key",
        "gs_credentials",
        "azure_connection_string",
        "azure_client_secret",
        "aws_secret_key",
        "aws_access_key",
        "delivery_params",
        "confirmation_token",
        "x_skyfi_api_key",
    }
)


def _scrub_sensitive_fields(
    logger: Any,
    method: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Remove sensitive fields from log entries before output."""
    for field in _SENSITIVE_FIELDS:
        if field in event_dict:
            event_dict[field] = "[REDACTED]"
    return event_dict


def setup_logging(log_level: str = "info", log_format: str = "json") -> None:
    """Configure structlog for Purveyor.

    Args:
        log_level: Minimum log level (debug, info, warning, error, critical).
        log_format: Output format — "json" for production, "console" for dev.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _scrub_sensitive_fields,
    ]

    if log_format == "console":
        processors: list[structlog.types.Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging at the same level so third-party libs behave
    logging.basicConfig(
        format="%(message)s",
        level=level,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name (typically the module name).
    """
    logger: structlog.BoundLogger = structlog.get_logger(name)
    return logger


def setup_logging_from_env() -> None:
    """Configure logging from environment variables LOG_LEVEL and LOG_FORMAT."""
    log_level = os.environ.get("LOG_LEVEL", "info")
    log_format = os.environ.get("LOG_FORMAT", "json")
    setup_logging(log_level=log_level, log_format=log_format)
