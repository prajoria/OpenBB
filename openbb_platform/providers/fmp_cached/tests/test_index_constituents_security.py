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
