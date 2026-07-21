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

import logging
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


# ---------------------------------------------------------------------------
# Log-record scrubbing (#963)
# ---------------------------------------------------------------------------
#
# Defense-in-depth for un-wrapped call sites: any log record whose fully-
# formatted message contains ``apikey=<value>`` gets scrubbed to
# ``apikey=__redacted__`` before it hits any handler.
#
# Motivation: `raise_for_status_redacted` covers the sync-`requests`
# leak surface, but upstream `openbb_fmp/utils/helpers.py` has two
# `make_request(url).raise_for_status()` sites (`get_available_transcript_symbols`,
# `get_transcript_dates_for_symbol`) where the URL is embedded with the
# raw apikey. On 402, the resulting `requests.HTTPError` message
# includes the key, and `base_cached.py:97`'s
# ``logger.error(f"Failed to fetch data ... {e}")`` re-emits it to
# stderr / Sentry / CI logs. Fixed live during PR #966 recording batch 3.
#
# This filter catches all such records defensively: even a future
# un-wrapped raise, an upstream regression, or a third-party library
# echoing a URL will be scrubbed at the logging boundary.


class ApikeyScrubFilter(logging.Filter):
    """Rewrite ``apikey=<value>`` inside a log record's message.

    Mutates the record so the scrubbed text is what handlers see. The
    original ``msg`` + ``args`` are replaced with the pre-formatted
    scrubbed string; downstream formatters get a message with no ``%s``
    placeholders to worry about.

    Falsy match → record passes through untouched (no allocation).
    Never raises; a scrubber that crashes on a corner case would
    silently drop log records, which is worse than leaking one.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            formatted = record.getMessage()
        except Exception:  # noqa: BLE001
            # LogRecord.getMessage() can raise on bad %-format specs.
            # If we can't read the message, don't drop the record.
            return True
        if "apikey=" not in formatted.lower():
            return True
        scrubbed = redact_apikey_qs(formatted)
        # Also handle plain "apikey=<value>" without ? or & prefix
        # (some log formatters concatenate this way).
        scrubbed = _APIKEY_BARE_RE.sub(r"apikey=__redacted__", scrubbed)
        if scrubbed != formatted:
            record.msg = scrubbed
            record.args = None
        return True


# Bare `apikey=<value>` without ? or & (rare — some log formatters
# join query params with space or comma). More permissive than
# _APIKEY_QS_RE — apply AFTER the QS redactor.
_APIKEY_BARE_RE = re.compile(r"apikey=[^\s&\"'>]+", re.IGNORECASE)


def install_apikey_scrub_filter(
    logger: logging.Logger | None = None,
) -> ApikeyScrubFilter:
    """Attach an :class:`ApikeyScrubFilter` to ``logger`` (default:
    ``openbb_fmp_cached``). Idempotent — a second call reuses the existing
    filter instance instead of stacking. Returns the (attached) filter so
    callers can remove it later if needed.

    IMPORTANT — Python logging filter semantics:
    Filters on a **logger** only apply to records EMITTED by that logger.
    Records that PROPAGATE up from a child logger reach parent handlers
    WITHOUT triggering the parent's filters — only the handlers' own
    filters. So installing on a package logger scrubs records emitted
    within the package but NOT records from ``urllib3.connectionpool``
    (which emits its own record and propagates up).

    To catch propagated records too, also call
    :func:`install_apikey_scrub_filter_on_root_handlers` (which iterates
    existing handlers on the root logger and attaches the filter to
    each). Do this at package-import time so any handler configured
    later still gets the filter via a fresh install.
    """
    if logger is None:
        logger = logging.getLogger("openbb_fmp_cached")
    for existing in logger.filters:
        if isinstance(existing, ApikeyScrubFilter):
            return existing
    f = ApikeyScrubFilter()
    logger.addFilter(f)
    return f


def install_apikey_scrub_filter_on_root_handlers() -> int:
    """Attach an :class:`ApikeyScrubFilter` to every handler on the ROOT logger.

    Catches records from ANY module (urllib3, requests, etc.) that
    propagate to the root's handlers. Idempotent per handler.

    Returns the number of handlers newly touched (excludes ones that
    already had the filter).

    Because handlers created AFTER this call won't have the filter,
    callers who need bulletproof coverage should also install a
    ``logging.setLoggerClass`` wrapper OR use
    :func:`patch_addHandler_to_install_filter` (below). For our fmp_cached
    use, the root-handler install at package-import covers the standard
    case (a test suite's caplog handler, a pytest --log-cli handler, a
    top-level logging.basicConfig). Any custom handler added post-import
    stays uncovered — accept that as a known gap.
    """
    root = logging.getLogger()
    touched = 0
    for h in root.handlers:
        if not any(isinstance(f, ApikeyScrubFilter) for f in h.filters):
            h.addFilter(ApikeyScrubFilter())
            touched += 1
    return touched


def _wrap_root_addHandler_with_scrub() -> None:
    """Monkey-patch ``root.addHandler`` so any handler added later also
    gets an :class:`ApikeyScrubFilter`. Idempotent.

    Belt-and-suspenders for the ``install_apikey_scrub_filter_on_root_handlers``
    gap on late-added handlers. Only patches once per process.
    """
    root = logging.getLogger()
    if getattr(root, "_apikey_scrub_wrapped", False):
        return
    orig = root.addHandler

    def wrapped(handler: logging.Handler) -> None:
        orig(handler)
        if not any(isinstance(f, ApikeyScrubFilter) for f in handler.filters):
            handler.addFilter(ApikeyScrubFilter())

    root.addHandler = wrapped  # type: ignore[method-assign,assignment]
    root._apikey_scrub_wrapped = True  # type: ignore[attr-defined]  # pylint: disable=protected-access
