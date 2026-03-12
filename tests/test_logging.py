"""Tests for structlog configuration."""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from purveyor.core.logging import _scrub_sensitive_fields, setup_logging


def _capture_log_output(
    log_format: str,
    log_level: str,
    message: str,
    **kwargs: object,
) -> str:
    """Set up logging and capture a single log entry as a string."""
    buf = io.StringIO()
    setup_logging(log_level=log_level, log_format=log_format)

    # Reconfigure to write to our buffer
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _scrub_sensitive_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )

    log = structlog.get_logger("test")
    log.info(message, **kwargs)
    return buf.getvalue()


class TestJsonLogging:
    """Tests for JSON log output."""

    def test_json_output_is_valid_json(self) -> None:
        """JSON log format produces parseable JSON."""
        output = _capture_log_output("json", "info", "test event", foo="bar")
        lines = [line for line in output.strip().split("\n") if line]
        assert lines, "Expected at least one log line"
        parsed = json.loads(lines[0])
        assert parsed["event"] == "test event"
        assert parsed["foo"] == "bar"

    def test_json_output_contains_level(self) -> None:
        """JSON log entries include the log level."""
        output = _capture_log_output("json", "info", "level test")
        parsed = json.loads(output.strip().split("\n")[0])
        assert parsed.get("log_level") == "info" or parsed.get("level") == "info"

    def test_json_output_contains_timestamp(self) -> None:
        """JSON log entries include an ISO timestamp."""
        output = _capture_log_output("json", "info", "ts test")
        parsed = json.loads(output.strip().split("\n")[0])
        assert "timestamp" in parsed


class TestLogLevelFiltering:
    """Tests for log level filtering."""

    def test_info_messages_appear_at_info_level(self) -> None:
        """Info messages are logged when level is info."""
        output = _capture_log_output("json", "info", "visible message")
        assert "visible message" in output

    def test_debug_messages_filtered_at_info_level(self) -> None:
        """Debug messages are suppressed when level is info."""
        buf = io.StringIO()
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=buf),
            cache_logger_on_first_use=False,
        )
        log = structlog.get_logger("test")
        log.debug("this should not appear")
        assert "this should not appear" not in buf.getvalue()


class TestSensitiveFieldRedaction:
    """Tests for sensitive field scrubbing."""

    @pytest.mark.parametrize(
        "field",
        [
            "api_key",
            "secret_key",
            "gs_credentials",
            "azure_connection_string",
            "aws_secret_key",
            "delivery_params",
        ],
    )
    def test_sensitive_field_redacted(self, field: str) -> None:
        """Sensitive fields are replaced with [REDACTED]."""
        event_dict = {"event": "test", field: "super_secret_value"}
        result = _scrub_sensitive_fields(None, "info", event_dict)
        assert result[field] == "[REDACTED]"
        assert "super_secret_value" not in str(result)

    def test_non_sensitive_fields_preserved(self) -> None:
        """Non-sensitive fields are not modified."""
        event_dict = {"event": "test", "order_id": "abc-123", "status": "pending"}
        result = _scrub_sensitive_fields(None, "info", event_dict)
        assert result["order_id"] == "abc-123"
        assert result["status"] == "pending"
