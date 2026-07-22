"""Replay — regenerate a snapshot by re-running its recording.

Thin wrapper over ``record.run_recording`` for CLI symmetry with
``portfolio_export`` (which has separate ``pe record`` and ``pe
replay`` verbs). Semantically identical to ``record`` in this tool
because the recording is checked into the repo; "replay" just means
"re-run the same capture with today's data".
"""

from __future__ import annotations

from pathlib import Path

from scrape_record.config import Config
from scrape_record.record import run_recording


def run_replay(cfg: Config, name: str, symbol: str, **kwargs) -> Path:
    """Alias for ``run_recording`` — refresh an existing snapshot."""
    return run_recording(cfg, name, symbol, **kwargs)
