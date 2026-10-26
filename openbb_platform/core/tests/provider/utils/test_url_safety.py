"""SSRF guard tests for caller-controlled document URLs (#2242)."""

import asyncio
import socket

import pytest
import requests
from openbb_core.provider.utils import url_safety
from openbb_core.provider.utils.url_safety import (
    UnsafeUrlError,
    amake_safe_request,
    make_safe_request,
    validate_public_url,
)

HOSTS = ("www.sec.gov",)
PUBLIC_V4 = "23.33.233.188"


def _resolver(*addresses: str):
    """Return a getaddrinfo stand-in that answers with ``addresses``."""

    def resolve(host, port, *args, **kwargs):  # noqa: ARG001
        family = socket.AF_INET6 if ":" in addresses[0] else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    return resolve


PUBLIC = _resolver(PUBLIC_V4)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sec.gov/Archives/edgar/data/1/0001-index.htm",
        "https://WWW.SEC.GOV/Archives/x.htm",
        "https://www.sec.gov./Archives/x.htm",
        "https://www.sec.gov:443/Archives/x.htm",
    ],
)
def test_accepts_https_allowlisted_public_host(url):
    """Allowlisted HTTPS hosts on the default port pass, case/dot-normalized."""
    assert validate_public_url(url, HOSTS, resolver=PUBLIC) == url


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://www.sec.gov/x.htm", "https"),
        ("ftp://www.sec.gov/x.htm", "https"),
        ("https://evil.example/?www.sec.gov", "not an allowed host"),
        ("https://www.sec.gov.evil.example/x.htm", "not an allowed host"),
        ("https://sec.gov/x.htm", "not an allowed host"),
        ("https://evilwww.sec.gov/x.htm", "not an allowed host"),
        ("https://attacker.www.sec.gov/x.htm", "not an allowed host"),
        ("https://user:pw@www.sec.gov/x.htm", "credentials"),
        ("https://www.sec.gov@evil.example/x.htm", "credentials"),
        ("https://www.sec.gov:8443/x.htm", "port"),
        ("https://www.sec.gov:0/x.htm", "port"),
        ("https:///x.htm", "host"),
        ("www.sec.gov/x.htm", "https"),
        ("", "https"),
    ],
)
def test_rejects_unsafe_url_shapes(url, reason):
    """Scheme, host, userinfo and port rules reject each bypass shape."""
    with pytest.raises(UnsafeUrlError, match=reason):
        validate_public_url(url, HOSTS, resolver=PUBLIC)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_rejects_hosts_resolving_to_non_public_addresses(address):
    """An allowlisted name that resolves anywhere non-public is refused."""
    with pytest.raises(UnsafeUrlError, match="non-public address"):
        validate_public_url(
            "https://www.sec.gov/x.htm", HOSTS, resolver=_resolver(address)
        )


def test_rejects_when_any_resolved_address_is_private():
    """One private answer among public ones is enough to refuse."""
    with pytest.raises(UnsafeUrlError, match="non-public address"):
        validate_public_url(
            "https://www.sec.gov/x.htm",
            HOSTS,
            resolver=_resolver(PUBLIC_V4, "10.1.2.3"),
        )


def test_rejects_unresolvable_host():
    """A DNS failure is a refusal, not a pass."""

    def fail(*_args, **_kwargs):
        raise socket.gaierror("no such host")

    with pytest.raises(UnsafeUrlError, match="could not be resolved"):
        validate_public_url("https://www.sec.gov/x.htm", HOSTS, resolver=fail)


def test_real_resolver_refuses_localhost():
    """The default resolver path really runs: localhost is loopback."""
    with pytest.raises(UnsafeUrlError, match="non-public address"):
        validate_public_url("https://localhost/x", ("localhost",))


class _Response:
    def __init__(self, status=200, location=None, body="ok"):
        self.status_code = self.status = status
        self.headers = {"Location": location} if location else {}
        self.is_redirect = location is not None
        self.text = body


class _Session(requests.Session):
    """requests.Session that records each GET instead of sending it."""

    def __init__(self, *responses):
        super().__init__()
        self.responses = list(responses)
        self.calls: list[tuple[str, bool]] = []

    def get(self, url, **kwargs):  # type: ignore[override]
        self.calls.append((url, kwargs.get("allow_redirects", True)))
        return self.responses.pop(0)


def test_sync_request_disables_automatic_redirects(monkeypatch):
    """Every hop is fetched with redirects off so it can be validated."""
    monkeypatch.setattr(url_safety, "_default_resolver", PUBLIC)
    session = _Session(_Response(body="doc"))
    response = make_safe_request("https://www.sec.gov/a.htm", HOSTS, session=session)
    assert response.text == "doc"
    assert session.calls == [("https://www.sec.gov/a.htm", False)]


def test_sync_request_follows_allowlisted_redirect(monkeypatch):
    """A relative redirect to the same allowlisted host is followed."""
    monkeypatch.setattr(url_safety, "_default_resolver", PUBLIC)
    session = _Session(_Response(302, "/b.htm"), _Response(body="moved"))
    response = make_safe_request("https://www.sec.gov/a.htm", HOSTS, session=session)
    assert response.text == "moved"
    assert [c[0] for c in session.calls] == [
        "https://www.sec.gov/a.htm",
        "https://www.sec.gov/b.htm",
    ]


def test_sync_request_refuses_redirect_off_allowlist(monkeypatch):
    """A redirect to another host is refused before it is fetched."""
    monkeypatch.setattr(url_safety, "_default_resolver", PUBLIC)
    session = _Session(_Response(302, "http://169.254.169.254/latest/meta-data"))
    with pytest.raises(UnsafeUrlError):
        make_safe_request("https://www.sec.gov/a.htm", HOSTS, session=session)
    assert len(session.calls) == 1


def test_sync_request_caps_redirect_chain(monkeypatch):
    """A redirect loop stops at max_redirects."""
    monkeypatch.setattr(url_safety, "_default_resolver", PUBLIC)
    session = _Session(*[_Response(302, "/loop.htm") for _ in range(10)])
    with pytest.raises(UnsafeUrlError, match="too many redirects"):
        make_safe_request(
            "https://www.sec.gov/a.htm", HOSTS, max_redirects=3, session=session
        )
    assert len(session.calls) == 4


class _AsyncResponse(_Response):
    async def text_body(self):
        return self.text


class _AsyncSession:
    """aiohttp.ClientSession stand-in recording each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, bool]] = []
        self.closed = False

    async def request(self, method, url, **kwargs):
        self.calls.append((url, kwargs.get("allow_redirects", True)))
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


async def _text(response, _session):
    return {"body": await response.text_body()}


def test_async_request_validates_each_hop(monkeypatch):
    """Async fetches follow allowlisted redirects with redirects disabled."""
    monkeypatch.setattr(url_safety, "_default_resolver", PUBLIC)
    session = _AsyncSession(
        _AsyncResponse(301, "https://www.sec.gov/final.htm"),
        _AsyncResponse(body="final"),
    )
    result = asyncio.run(
        amake_safe_request(
            "https://www.sec.gov/a.htm",
            HOSTS,
            session=session,
            response_callback=_text,
        )
    )
    assert result == {"body": "final"}
    assert session.calls == [
        ("https://www.sec.gov/a.htm", False),
        ("https://www.sec.gov/final.htm", False),
    ]


def test_async_request_refuses_redirect_off_allowlist(monkeypatch):
    """An async redirect to a non-allowlisted host is refused."""
    monkeypatch.setattr(url_safety, "_default_resolver", PUBLIC)
    session = _AsyncSession(_AsyncResponse(302, "https://evil.example/x"))
    with pytest.raises(UnsafeUrlError, match="not an allowed host"):
        asyncio.run(
            amake_safe_request(
                "https://www.sec.gov/a.htm",
                HOSTS,
                session=session,
                response_callback=_text,
            )
        )
    assert len(session.calls) == 1


def test_unsafe_url_error_is_an_openbb_client_error():
    """The API maps OpenBBError to HTTP 400, so refusals are client errors."""
    from openbb_core.app.model.abstract.error import OpenBBError

    assert issubclass(UnsafeUrlError, OpenBBError)


def test_error_text_never_echoes_query_or_credentials():
    """Refusals must not leak an API key or password carried in the URL."""
    with pytest.raises(UnsafeUrlError) as caught:
        validate_public_url(
            "http://user:s3cret@www.sec.gov/x.htm?api_key=TOPSECRET", HOSTS
        )
    message = str(caught.value)
    assert "TOPSECRET" not in message and "s3cret" not in message
    assert "www.sec.gov/x.htm" in message
