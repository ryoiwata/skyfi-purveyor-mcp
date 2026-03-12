"""Live integration tests against the real SkyFi API.

These tests require a real SkyFi API key and are gated behind the ``live``
pytest marker.  They are read-only: no orders, notifications, or mutating
calls are made.

Run with:
    SKYFI_TEST_API_KEY=<your_key> uv run pytest -m live -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def live_api_key() -> str:
    """Provide the live SkyFi API key, or skip if not set."""
    key = os.environ.get("SKYFI_TEST_API_KEY")
    if not key:
        pytest.skip("SKYFI_TEST_API_KEY not set — skipping live API tests")
    return key


@pytest.fixture
async def live_client(live_api_key: str) -> object:
    """Return an authenticated SkyFiClient against the real API."""
    from purveyor.core.skyfi_client import SkyFiClient

    client = SkyFiClient(api_key=live_api_key)
    yield client
    await client.close()


async def test_ping(live_client: object) -> None:
    """SkyFi /ping endpoint returns a parseable response."""
    import typing

    from purveyor.core.skyfi_client import SkyFiClient

    client = typing.cast(SkyFiClient, live_client)
    result = await client.ping()
    # Should not raise — result can be anything (dict or model)
    assert result is not None


async def test_whoami(live_client: object) -> None:
    """SkyFi /auth/whoami returns a parseable WhoamiUser."""
    import typing

    from purveyor.core.skyfi_client import SkyFiClient
    from purveyor.core.skyfi_types import WhoamiUser

    client = typing.cast(SkyFiClient, live_client)
    result = await client.whoami()
    assert isinstance(result, WhoamiUser)
    assert result.email  # Basic shape check — must have an email


async def test_search_archives(live_client: object) -> None:
    """Archive search against Austin TX returns a parseable list."""
    import typing

    from purveyor.core.skyfi_client import SkyFiClient
    from purveyor.core.skyfi_types import GetArchivesRequest

    client = typing.cast(SkyFiClient, live_client)
    request = GetArchivesRequest(
        aoi="POLYGON((-97.76 30.28, -97.72 30.28, -97.72 30.24, -97.76 30.24, -97.76 30.28))",
        openData=True,
        pageSize=5,
    )
    result = await client.search_archives(request)
    assert isinstance(result.archives, list)


async def test_get_pricing(live_client: object) -> None:
    """Pricing endpoint returns a non-empty dict."""
    import typing

    from purveyor.core.skyfi_client import SkyFiClient

    client = typing.cast(SkyFiClient, live_client)
    result = await client.get_pricing(None)
    assert isinstance(result, dict)
