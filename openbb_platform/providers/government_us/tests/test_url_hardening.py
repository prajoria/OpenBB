"""SSRF regressions for caller-supplied USDA bulletin URLs (#2242)."""

import asyncio
import socket

import pytest
from openbb_core.provider.utils import url_safety
from openbb_core.provider.utils.url_safety import UnsafeUrlError
from openbb_government_us.models import weather_bulletin_download as module
from openbb_government_us.models.weather_bulletin_download import (
    GovernmentUsWeatherBulletinDownloadFetcher as Fetcher,
)


@pytest.fixture
def network(monkeypatch):
    """Fail if any session is opened; resolve every host publicly."""
    opened: list[str] = []

    def public(host, port, *args, **kwargs):  # noqa: ARG001
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("23.1.2.3", port))]

    async def no_session(*args, **kwargs):
        opened.append("session")
        raise AssertionError("no download may start for an unsafe URL")

    monkeypatch.setattr(url_safety, "_default_resolver", public)
    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_async_requests_session", no_session
    )
    return opened


@pytest.mark.parametrize(
    "url",
    [
        "https://esmis.nal.usda.gov.evil.example/files/x.pdf",
        "https://esmis.nal.usda.gov@evil.example/files/x.pdf",
        "https://esmis.nal.usda.gov:8443/files/x.pdf",
        "http://esmis.nal.usda.gov/files/x.pdf",
    ],
)
def test_bulletin_download_refuses_unsafe_urls_before_any_session(network, url):
    """Every URL is validated before a session is opened."""
    query = Fetcher.transform_query({"urls": [url]})
    with pytest.raises(UnsafeUrlError):
        asyncio.run(Fetcher.aextract_data(query, None))
    assert network == []


def test_bulletin_hosts_are_exact():
    """Only the ESMIS host is allowlisted."""
    assert module.USDA_ESMIS_HOSTS == ("esmis.nal.usda.gov",)
