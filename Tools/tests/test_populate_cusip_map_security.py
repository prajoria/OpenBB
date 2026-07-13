"""Structural security test: populate_cusip_map must not embed API key in URL.

Regression test for OpenBBTechnical-1xgu — line 173 built
``f"{FMP_STABLE}/profile?symbol={symbol}&apikey={api_key}"`` and:
  1. Leaked the FMP API key into proxy/CDN access logs and any error path
     that echoes the request URL
  2. Interpolated ``symbol`` raw (no URL-encoding) — a value containing
     ``&``, ``#``, ``?``, or whitespace would break URL parsing or
     smuggle extra query parameters (the ``--symbols`` CLI accepts
     arbitrary user input)

Fix: route both ``symbol`` and ``apikey`` through
``requests.get(url, params={'symbol': symbol, 'apikey': api_key}, ...)`` —
requests handles URL-encoding and keeps the key out of the URL.

Structural test rationale: same as the fmp_cached security tests —
strictly stronger than a live unit test (catches any future refactor)
and independent of any runtime infrastructure gotchas.
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
            continue
        if _ANTIPATTERN.search(line):
            hits.append((lineno, line.rstrip()))
    return hits


def test_no_apikey_in_url_fstring_in_populate_cusip_map():
    """Regression for OpenBBTechnical-1xgu — apikey must move to params dict."""
    # Import inside the test so pytest collection doesn't require the Tools/
    # module to be importable on failure (Tools/ has script-oriented modules
    # that may pull in optional deps at import time).
    import sys
    from pathlib import Path

    tools_root = str(Path(__file__).resolve().parents[1] / "Tools")
    if tools_root not in sys.path:
        sys.path.insert(0, tools_root)

    from Tools import populate_cusip_map as mod  # type: ignore[import-not-found]

    hits = _scan_source_for_apikey_fstring(mod)
    assert not hits, (
        "Found f-string apikey= interpolation in Tools/populate_cusip_map.py — "
        "these leak the API key via HTTPError.url and proxy logs. Move to "
        "params={'symbol': symbol, 'apikey': api_key}. Sites:\n"
        + "\n".join(f"  L{ln}: {ln_text}" for ln, ln_text in hits)
    )
