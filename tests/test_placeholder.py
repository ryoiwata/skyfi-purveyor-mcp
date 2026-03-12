"""Placeholder test to verify the test suite runs."""

from __future__ import annotations

from purveyor import __version__


def test_version() -> None:
    """Verify the package version is set."""
    assert __version__ == "0.1.0"
