"""SSRF and API-key-leak regressions for caller-supplied Congress URLs (#2242)."""

import asyncio
import socket

import pytest
from openbb_congress_gov.models.amendment_info import CongressAmendmentInfoFetcher
from openbb_congress_gov.models.amendment_text import CongressAmendmentTextFetcher
from openbb_congress_gov.models.bill_info import CongressBillInfoFetcher
from openbb_congress_gov.models.bill_text import CongressBillTextFetcher
from openbb_core.provider.utils import helpers as core_helpers
from openbb_core.provider.utils import url_safety
from openbb_core.provider.utils.url_safety import UnsafeUrlError

KEY = "CONGRESS-KEY-SENTINEL"
CREDENTIALS = {"congress_gov_api_key": KEY}


def _public(host, port, *args, **kwargs):  # noqa: ARG001
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("23.1.2.3", port))]


@pytest.fixture
def network(monkeypatch):
    """Record every outbound request; resolve every host to a public IP."""
    calls: list[str] = []
    monkeypatch.setattr(url_safety, "_default_resolver", _public)

    async def fake_amake_request(url, *args, **kwargs):
        calls.append(url)
        return {"bill": {}, "amendment": {}}

    def fake_make_request(url, *args, **kwargs):
        calls.append(url)
        raise AssertionError("document fetch should not happen in this test")

    monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
    monkeypatch.setattr(core_helpers, "make_request", fake_make_request)
    return calls


@pytest.mark.parametrize(
    "fetcher_cls,field",
    [
        (CongressBillInfoFetcher, "bill_url"),
        (CongressAmendmentInfoFetcher, "amendment_url"),
    ],
)
@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v3/bill/119/s/1947?format=json",
        "https://api.congress.gov.evil.example/v3/bill/119/s/1947?",
        "http://api.congress.gov/v3/bill/119/s/1947?",
        "https://api.congress.gov:8443/v3/bill/119/s/1947?",
    ],
)
def test_info_fetchers_never_send_the_key_off_host(network, fetcher_cls, field, url):
    """A caller-chosen host is refused before the keyed request is made."""
    query = fetcher_cls.transform_query({field: url})
    with pytest.raises(UnsafeUrlError) as caught:
        asyncio.run(fetcher_cls.aextract_data(query, CREDENTIALS))
    assert network == [], "no request may leave for an unsafe host"
    assert KEY not in str(caught.value)


def test_bill_info_shorthand_reaches_the_api_host_with_key(network):
    """The documented shorthand still resolves to api.congress.gov."""
    query = CongressBillInfoFetcher.transform_query({"bill_url": "119/s/1947"})
    asyncio.run(CongressBillInfoFetcher.aextract_data(query, CREDENTIALS))
    assert network == [
        f"https://api.congress.gov/v3/bill/119/s/1947?format=json&api_key={KEY}"
    ]


@pytest.mark.parametrize(
    "fetcher_cls", [CongressBillTextFetcher, CongressAmendmentTextFetcher]
)
@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/?congress.gov",
        "https://www.congress.gov.evil.example/BILLS-119hr1eh.pdf",
        "https://user@www.congress.gov/BILLS-119hr1eh.pdf",
        "http://www.govinfo.gov/x.pdf",
    ],
)
def test_text_fetchers_report_unsafe_urls_without_fetching(network, fetcher_cls, url):
    """Unsafe document URLs become invalid_url results; nothing is fetched."""
    query = fetcher_cls.transform_query({"urls": [url]})
    results = asyncio.run(fetcher_cls.aextract_data(query, CREDENTIALS))
    assert network == []
    assert [r["error_type"] for r in results] == ["invalid_url"]
