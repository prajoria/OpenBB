"""Security helpers for the fmp_cached provider.

Shared utilities for keeping the FMP API key out of any surface that
gets logged or shown to a caller:

* :func:`redact_apikey_qs` — rewrites the querystring of a URL so the
  ``apikey=<key>`` fragment reads ``apikey=__redacted__``. Apply this
  to ``resp.url`` (and ``resp.request.url``) BEFORE calling
  ``requests.Response.raise_for_status()`` — ``requests`` merges
  ``params=`` into ``PreparedRequest.url`` before sending, so the
  response URL contains the plaintext key and the resulting
  ``HTTPError`` message would otherwise leak it into every stderr /
  Sentry / CI-log surface (bd-6641 / bd-q4b4 / bd-ygtq).

* :func:`raise_for_status_redacted` — convenience wrapper: mutates the
  response URL in place then calls ``raise_for_status()``, so callers
  can replace a bare ``resp.raise_for_status()`` with a one-line
  ``raise_for_status_redacted(resp)``.
"""

from __future__ import annotations

import re
from typing import Any

# Regex + helper for redacting FMP apikey from response URLs.
# Case-insensitive; anchors on ? or & so ``?myapikey=`` won't match.
# Terminates on & so subsequent querystring params are preserved.
_APIKEY_QS_RE = re.compile(r"([?&])apikey=[^&]*", re.IGNORECASE)


def redact_apikey_qs(url: str) -> str:
    """Return ``url`` with any ``apikey=<...>`` querystring value redacted.

    Preserves everything else in the URL (base, other params, fragment)
    so operators can still see 'which endpoint returned 429', just not
    the key that authenticated the call.

    Examples
    --------
    >>> redact_apikey_qs("https://api.example.com/x?symbol=A&apikey=SECRET")
    'https://api.example.com/x?symbol=A&apikey=__redacted__'
    >>> redact_apikey_qs("https://api.example.com/x?apikey=SECRET&other=y")
    'https://api.example.com/x?apikey=__redacted__&other=y'
    >>> redact_apikey_qs("")
    ''
    """
    if not url:
        return url
    return _APIKEY_QS_RE.sub(r"\1apikey=__redacted__", url)


def raise_for_status_redacted(resp: Any) -> None:
    """Call ``resp.raise_for_status()`` after redacting apikey from ``resp.url``.

    Handles the ``requests``-merges-``params=``-into-URL leak
    (bd-6641 / bd-q4b4 / bd-ygtq): on any 4xx/5xx response,
    ``resp.raise_for_status()`` reads ``resp.url`` at exception-
    construction time and interpolates it into the ``HTTPError``
    message. This wrapper mutates ``resp.url`` (and
    ``resp.request.url`` for the Sentry-style ``.response.url``
    breadcrumb field) to the redacted form BEFORE calling
    ``raise_for_status()``, so the resulting exception carries
    ``apikey=__redacted__`` instead of the plaintext key.

    No-op on 2xx/3xx responses.
    """
    if getattr(resp, "status_code", 200) >= 400:
        redacted_url = redact_apikey_qs(getattr(resp, "url", ""))
        try:
            resp.url = redacted_url
        except (AttributeError, TypeError):
            # Older/stubbed Response objects may not allow attribute
            # writes — nothing we can do; raise_for_status() falls
            # through unchanged.
            pass
        req = getattr(resp, "request", None)
        if req is not None:
            try:
                req.url = redacted_url
            except (AttributeError, TypeError):
                pass
    resp.raise_for_status()
