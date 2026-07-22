"""Extractor contract — how a raw scraped snapshot becomes structured JSON.

An extractor is a plain Python module in ``scrape_record.extractors``
that exports a top-level ``extract(raw: dict) -> dict`` function.

- **raw** is what the recording produced: DOM HTML + captured network
  JSON responses + metadata (url, symbol, timestamp).
- **return value** is the structured JSON that gets saved to disk and
  read back by downstream fetchers. Extractors should return a JSON-
  serializable dict.

Design note: extractors are DELIBERATELY pure functions of the raw
snapshot. Same raw input → same structured output, no network. This
lets us evolve extractors + re-run ``extract`` on old raw snapshots
without re-scraping (e.g. when Yahoo adds a field we now want to
surface).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any


class ExtractorError(RuntimeError):
    """Raised when an extractor can't be loaded or fails to run."""


def load_extractor(name: str) -> Callable[[dict], dict]:
    """Import ``scrape_record.extractors.<name>`` and return its ``extract`` fn.

    Raises ExtractorError if the module is missing or doesn't export a
    callable named ``extract``.
    """
    module_name = f"scrape_record.extractors.{name}"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ExtractorError(
            f"No extractor module '{module_name}'. Create "
            f"scrape_record/extractors/{name}.py with a top-level "
            "`def extract(raw): ...` function."
        ) from exc
    fn = getattr(module, "extract", None)
    if not callable(fn):
        raise ExtractorError(
            f"Module '{module_name}' does not export a callable named "
            "'extract'. Expected signature: extract(raw: dict) -> dict."
        )
    return fn


def apply_extractor(name: str, raw: dict) -> dict:
    """Load the extractor for ``name`` and apply it to ``raw``.

    Wraps runtime exceptions with ExtractorError so callers can
    distinguish extractor bugs from scraping failures.
    """
    fn = load_extractor(name)
    try:
        return fn(raw)
    except Exception as exc:
        raise ExtractorError(
            f"Extractor '{name}' raised {type(exc).__name__} while "
            f"processing snapshot: {exc}"
        ) from exc


def verify_snapshot(name: str, raw: dict) -> dict[str, Any]:
    """Dry-run an extractor against a raw snapshot; return a summary dict.

    Used by ``scrape-record verify`` to sanity-check extractor drift
    without opening a browser. Returns:

    - ``ok``: True if extract() ran without error
    - ``rows``: number of top-level rows produced (best-effort)
    - ``keys``: sorted list of top-level keys in the output
    - ``error``: exception message if ok=False
    """
    try:
        result = apply_extractor(name, raw)
    except ExtractorError as exc:
        return {"ok": False, "error": str(exc), "rows": 0, "keys": []}
    keys = sorted(result.keys()) if isinstance(result, dict) else []
    rows = 0
    if isinstance(result, dict):
        for v in result.values():
            if isinstance(v, list):
                rows += len(v)
    return {"ok": True, "rows": rows, "keys": keys}
