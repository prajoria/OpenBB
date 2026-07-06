"""Structural security tests: apikey must not appear in URL f-strings.

Regression tests for OpenBBTechnical-ygtq — two sites in
``index_constituents.py`` (lines 397 and 579) used to build URLs like
``f"...?apikey={api_key}"``, leaking the FMP API key into any log line,
proxy access log, or traceback that ever surfaced the request URL.

The fix routes the key through ``params={'apikey': api_key}`` on the
underlying HTTP call — ``requests`` / ``aiohttp`` both handle URL-encoding
and keep the key out of the URL string.

Written as a **source-level** assertion for two reasons:
  1. It's strictly stronger — any future refactor that reintroduces the
     ``apikey=`` f-string in a new call site fails this test even if we
     didn't think to add a unit test for that specific site.
  2. Live-async unit tests for this provider's async fetch functions
     were hitting an ``OSError: could not get source code`` on pytest-
     asyncio's event_loop fixture setup in this test env; a source
     scan sidesteps the runtime infrastructure entirely.
"""

from __future__ import annotations

import inspect
import re

_ANTIPATTERN = re.compile(r"apikey=\{[^}]+\}")


def _scan_source_for_apikey_fstring(module) -> list[tuple[int, str]]:
    """Return line-number + text pairs where ``apikey={...}`` appears in code."""
    src = inspect.getsource(module)
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # comments may legitimately reference the anti-pattern
        if _ANTIPATTERN.search(line):
            hits.append((lineno, line.rstrip()))
    return hits


def test_no_apikey_in_url_fstring_in_index_constituents():
    """Regression for OpenBBTechnical-ygtq (line 397 + 579).

    Both the sync ``_fetch_from_api_sync`` and the async fetcher used
    ``f"...?apikey={api_key}"``. Fixed by moving to ``params=``; this
    test locks it in.
    """
    from openbb_fmp_cached.models import index_constituents as mod

    hits = _scan_source_for_apikey_fstring(mod)
    assert not hits, (
        "Found f-string apikey= interpolation in index_constituents.py — "
        "these leak the API key via HTTPError.url and proxy logs. Move to "
        "params={'apikey': api_key}. Sites:\n"
        + "\n".join(f"  L{ln}: {ln_text}" for ln, ln_text in hits)
    )


def test_fetch_from_api_sync_http_error_does_not_leak_apikey(monkeypatch):
    """Round-1 review finding: sync path's raise_for_status() must redact.

    Even after moving apikey to ``params=``, ``requests`` merges params
    into PreparedRequest.url pre-send, so ``resp.url`` carries the
    plaintext key. A 4xx/5xx response then produces an
    ``HTTPError`` whose message reads ``for url: <URL with apikey=...>``
    that propagates up to the CLI caller and lands in logs.

    Verified fix: ``raise_for_status_redacted`` wrapper mutates
    ``resp.url`` before ``raise_for_status()`` fires. This test
    reproduces a 429 and asserts the resulting exception message +
    ``response.url`` both have the sentinel key redacted.
    """
    import requests
    from openbb_fmp_cached.models import index_constituents as mod

    sentinel = "SENTINEL_KEY_INDEX_CONSTITUENTS"

    def fake_get(url, timeout=None, params=None, **kwargs):
        merged_url = f"{url}?apikey={params['apikey']}"

        class FakeRequest:
            def __init__(self, u):
                self.url = u

        class R:
            status_code = 429
            content = b"rate limited"
            reason = "Too Many Requests"

            def __init__(self):
                self.url = merged_url
                self.request = FakeRequest(merged_url)

            def raise_for_status(self):
                # Match requests.Response behaviour: read self.url at
                # raise-time so the fix's mutation actually redacts.
                raise requests.HTTPError(
                    f"{self.status_code} Client Error: {self.reason} "
                    f"for url: {self.url}",
                    response=self,
                )

            def json(self):
                return {}

        return R()

    # Monkeypatch top-level requests.get (the module imports it at file top)
    monkeypatch.setattr(mod.requests, "get", fake_get)

    # Also stub the api_key resolver so we control the sentinel.
    monkeypatch.setattr(mod, "_get_api_key", lambda: sentinel)

    try:
        mod._fetch_from_api_sync()
    except requests.HTTPError as exc:
        assert sentinel not in str(exc), f"HTTPError leaked apikey in message: {exc!s}"
        resp = getattr(exc, "response", None)
        if resp is not None:
            assert sentinel not in str(
                getattr(resp, "url", "")
            ), f"HTTPError.response.url leaked apikey: {resp.url!r}"
    else:
        raise AssertionError("_fetch_from_api_sync should have raised on HTTP 429")
