"""Recording — capture a raw scrape snapshot via Playwright.

A recording is a Python module in ``recordings/<name>.py`` that exports
a top-level ``async def capture(page, symbol) -> dict`` function. The
return value is the raw snapshot: whatever the page delivered (DOM
HTML, captured JSON responses, metadata).

The framework:
1. Opens a persistent Chromium via ``session.persistent_context``.
2. Imports the recording module.
3. Calls its ``capture(page, symbol)`` coroutine.
4. Wraps the returned raw dict in a snapshot envelope + writes to
   ``snapshots/<name>/<symbol>.json``.
5. Optionally runs the paired extractor to also emit an ``extracted``
   sibling artifact for downstream fetchers.

Contrast with ``portfolio_export.record``: that tool records + saves a
Playwright script *template* that the user then completes. Here the
recording is a fully-written capture function committed to the repo;
users invoke ``scrape-record record <name> --symbol X`` to *run* it,
not to author it. Authoring is a separate one-time step.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scrape_record.config import Config, recording_path, snapshot_path
from scrape_record.extract import apply_extractor


class RecordError(RuntimeError):
    """Raised when a recording can't be loaded or the capture fails."""


@dataclass
class SnapshotEnvelope:
    """Wrapper committed to disk around every raw snapshot."""

    name: str
    symbol: str
    captured_at: str  # ISO-8601 UTC
    source_url: str | None
    raw: dict[str, Any]
    extracted: dict[str, Any] | None = None
    extractor_version: str | None = None


def _load_recording(cfg: Config, name: str):
    """Import ``recordings/<name>.py`` as an ephemeral module."""
    path = recording_path(cfg, name)
    if not path.exists():
        raise RecordError(
            f"Recording '{name}' not found at {path}. Create it — a "
            "recording module exports `async def capture(page, symbol) -> dict`."
        )
    spec = importlib.util.spec_from_file_location(
        f"_scrape_record_recording_{name}", path
    )
    if spec is None or spec.loader is None:
        raise RecordError(f"Failed to build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "capture"):
        raise RecordError(
            f"Recording {path} does not define `async def capture(page, symbol)`."
        )
    return module


async def _run_capture(cfg: Config, name: str, symbol: str) -> dict[str, Any]:
    """Open persistent context, run the recording's capture(), return raw dict."""
    # pylint: disable=import-outside-toplevel
    from playwright.async_api import async_playwright

    module = _load_recording(cfg, name)
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.profile_dir),
            headless=cfg.headless,
            accept_downloads=False,
        )
        try:
            page = await ctx.new_page()
            raw = await module.capture(page, symbol)
            if not isinstance(raw, dict):
                raise RecordError(
                    f"Recording '{name}' returned {type(raw).__name__}, "
                    "expected a dict."
                )
            return raw
        finally:
            await ctx.close()


def run_recording(
    cfg: Config,
    name: str,
    symbol: str,
    *,
    also_extract: bool = True,
    source_url: str | None = None,
) -> Path:
    """End-to-end: record → save → optionally extract. Returns snapshot path."""
    raw = asyncio.run(_run_capture(cfg, name, symbol))
    envelope = SnapshotEnvelope(
        name=name,
        symbol=symbol,
        captured_at=datetime.now(timezone.utc).isoformat(),
        source_url=source_url or raw.get("source_url"),
        raw=raw,
    )
    if also_extract:
        envelope.extracted = apply_extractor(name, raw)
        envelope.extractor_version = raw.get("extractor_version", "1")
    out_path = snapshot_path(cfg, name, symbol)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(asdict(envelope), indent=2, sort_keys=False, default=str),
        encoding="utf-8",
    )
    return out_path


def load_snapshot(cfg: Config, name: str, symbol: str) -> SnapshotEnvelope:
    """Read a snapshot from disk. Raises FileNotFoundError if missing."""
    path = snapshot_path(cfg, name, symbol)
    if not path.exists():
        raise FileNotFoundError(
            f"No snapshot for ({name}, {symbol}) at {path}. Run "
            f"`scrape-record record {name} --symbol {symbol}` first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return SnapshotEnvelope(**data)
