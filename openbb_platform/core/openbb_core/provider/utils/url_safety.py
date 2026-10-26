"""SSRF guards for caller-controlled document URLs (#2242).

Some provider endpoints download a document from a URL the caller supplies.
Before any such fetch, :func:`validate_public_url` requires:

- the ``https`` scheme on the default port, with no embedded credentials;
- a hostname exactly equal (after lower-casing and dropping a trailing dot)
  to one in the endpoint's allowlist, never a substring or suffix match;
- every address the hostname resolves to being a public unicast address.

:func:`make_safe_request` and :func:`amake_safe_request` fetch with automatic
redirects disabled and re-validate every ``Location`` before following it.

Residual risk: the address check and the connection resolve DNS separately,
so a hostile resolver could still race a rebind between them. The exact
hostname allowlist (public government hosts only) is the primary control.
"""

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from urllib.parse import urljoin, urlsplit

from openbb_core.app.model.abstract.error import OpenBBError

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
DEFAULT_MAX_REDIRECTS = 5

_default_resolver: Callable[..., list] = socket.getaddrinfo


class UnsafeUrlError(OpenBBError):
    """A caller-supplied URL failed the SSRF policy."""


def _display(url: str) -> str:
    """Return ``url`` without credentials, query or fragment, for error text."""
    try:
        parts = urlsplit(url or "")
        host = parts.hostname or ""
    except ValueError:
        return "<malformed URL>"
    return f"{parts.scheme}://{host}{parts.path}" if parts.scheme else "<relative URL>"


def _normalize_host(host: str) -> str:
    return host.rstrip(".").lower()


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def validate_public_url(
    url: str,
    allowed_hosts: Iterable[str],
    *,
    resolver: Callable[..., list] | None = None,
) -> str:
    """Return ``url`` unchanged if it is safe to fetch, else raise UnsafeUrlError."""
    allowed = {_normalize_host(h) for h in allowed_hosts}
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError as error:
        raise UnsafeUrlError(f"URL {_display(url)!r} is malformed: {error}") from error
    if parts.scheme.lower() != "https":
        raise UnsafeUrlError(f"URL {_display(url)!r} must use https.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeUrlError(f"URL {_display(url)!r} must not contain credentials.")
    if port not in (None, 443):
        raise UnsafeUrlError(f"URL {_display(url)!r} must use the default https port.")
    host = _normalize_host(parts.hostname or "")
    if not host:
        raise UnsafeUrlError(f"URL {_display(url)!r} has no host.")
    if host not in allowed:
        raise UnsafeUrlError(
            f"URL host {host!r} is not an allowed host for this endpoint"
            f" (allowed: {', '.join(sorted(allowed))})."
        )
    resolve = resolver or _default_resolver
    try:
        answers = resolve(host, 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as error:
        raise UnsafeUrlError(f"URL host {host!r} could not be resolved.") from error
    addresses = {info[4][0] for info in answers}
    if not addresses:
        raise UnsafeUrlError(f"URL host {host!r} could not be resolved.")
    blocked = sorted(a for a in addresses if not _is_public(a))
    if blocked:
        raise UnsafeUrlError(
            f"URL host {host!r} resolves to a non-public address ({', '.join(blocked)})."
        )
    return url


def _next_hop(current: str, location: str | None) -> str:
    if not location:
        raise UnsafeUrlError(
            f"Redirect from {_display(current)!r} has no Location header."
        )
    return urljoin(current, location)


def make_safe_request(
    url: str,
    allowed_hosts: Iterable[str],
    *,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    **kwargs: Any,
):
    """GET ``url`` with :func:`make_request`, validating every redirect hop."""
    # pylint: disable=import-outside-toplevel
    from openbb_core.provider.utils.helpers import make_request

    hosts = tuple(allowed_hosts)
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current, hosts)
        response = make_request(current, allow_redirects=False, **kwargs)
        if not response.is_redirect:
            return response
        current = _next_hop(current, response.headers.get("Location"))
    raise UnsafeUrlError(f"URL {_display(url)!r} produced too many redirects.")


class _Redirect:
    def __init__(self, location: str | None):
        self.location = location


async def amake_safe_request(
    url: str,
    allowed_hosts: Iterable[str],
    *,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    response_callback: Callable[[Any, Any], Awaitable[Any]] | None = None,
    **kwargs: Any,
) -> Any:
    """Fetch ``url`` with :func:`amake_request`, validating every redirect hop."""
    # pylint: disable=import-outside-toplevel
    from openbb_core.provider.utils.helpers import amake_request

    async def default_callback(response, _session):
        return await response.json()

    callback = response_callback or default_callback

    async def guarded(response, session):
        if response.status in REDIRECT_STATUSES:
            return _Redirect(response.headers.get("Location"))
        return await callback(response, session)

    hosts = tuple(allowed_hosts)
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current, hosts)
        result = await amake_request(
            current, allow_redirects=False, response_callback=guarded, **kwargs
        )
        if not isinstance(result, _Redirect):
            return result
        current = _next_hop(current, result.location)
    raise UnsafeUrlError(f"URL {_display(url)!r} produced too many redirects.")
