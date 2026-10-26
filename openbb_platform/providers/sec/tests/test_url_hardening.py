"""SSRF regressions for caller-supplied SEC document URLs (#2242)."""

import asyncio
import socket

import pytest
from openbb_core.provider.utils import helpers as core_helpers
from openbb_core.provider.utils import url_safety
from openbb_core.provider.utils.url_safety import UnsafeUrlError
from openbb_sec.models.htm_file import SecHtmFileFetcher
from openbb_sec.models.sec_filing import SecBaseFiling

UNSAFE = [
    "https://evil.example/sec.gov/x.htm",
    "https://www.sec.gov.evil.example/Archives/x.htm",
    "https://user@www.sec.gov/Archives/x.htm",
    "http://www.sec.gov/Archives/x.htm",
    "https://www.sec.gov:8443/Archives/x.htm",
]


@pytest.fixture
def network(monkeypatch):
    """Record outbound requests; resolve every host publicly."""
    calls: list[str] = []

    def public(host, port, *args, **kwargs):  # noqa: ARG001
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("23.1.2.3", port))]

    async def fake_amake_request(url, *args, **kwargs):
        calls.append(url)
        return "<html></html>"

    monkeypatch.setattr(url_safety, "_default_resolver", public)
    monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
    return calls


@pytest.mark.parametrize("url", UNSAFE)
def test_htm_file_query_refuses_unsafe_urls(network, url):
    """The htm_file query rejects every bypass shape up front."""
    with pytest.raises(UnsafeUrlError):
        SecHtmFileFetcher.transform_query({"url": url})


@pytest.mark.parametrize("url", UNSAFE)
def test_filing_downloads_refuse_unsafe_urls_without_fetching(network, url):
    """The shared SEC download path (htm_file, filing_headers) never fetches off-host."""
    with pytest.raises(UnsafeUrlError):
        asyncio.run(SecBaseFiling._adownload_file(url, use_cache=False))
    assert network == []


def test_filing_download_fetches_allowlisted_sec_url(network):
    """A real sec.gov archive URL is still fetched."""
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/x.htm"
    asyncio.run(SecBaseFiling._adownload_file(url, use_cache=False))
    assert network == [url]
