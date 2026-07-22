"""Tests for scrape_record.record — snapshot envelope load path.

Doesn't test the Playwright capture path (that requires a real browser
+ real Yahoo access). Focuses on the on-disk envelope contract: what
we save, what we load, how load_snapshot() handles missing files.
"""

from __future__ import annotations

import json

import pytest
from scrape_record.config import load_config, snapshot_path
from scrape_record.record import SnapshotEnvelope, load_snapshot


def test_load_committed_aapl_snapshot():
    """The checked-in AAPL fixture round-trips into a SnapshotEnvelope."""
    cfg = load_config()
    env = load_snapshot(cfg, "yahoo_options_chain", "AAPL")
    assert isinstance(env, SnapshotEnvelope)
    assert env.name == "yahoo_options_chain"
    assert env.symbol == "AAPL"
    assert env.source_url and env.source_url.startswith("https://finance.yahoo.com")
    assert isinstance(env.raw, dict)
    assert isinstance(env.extracted, dict)
    assert env.extractor_version == "1"


def test_load_snapshot_raises_for_missing_symbol(tmp_path):
    """Missing (name, symbol) raises FileNotFoundError with a helpful hint."""
    cfg = load_config()
    with pytest.raises(FileNotFoundError, match="record"):
        load_snapshot(cfg, "yahoo_options_chain", "NONEXISTENT_XYZ_SYMBOL_")


def test_snapshot_envelope_shape_stable_on_disk():
    """The AAPL fixture's on-disk keys match the envelope dataclass fields."""
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_options_chain", "AAPL")
    raw = json.loads(p.read_text(encoding="utf-8"))
    expected_keys = {
        "name",
        "symbol",
        "captured_at",
        "source_url",
        "raw",
        "extracted",
        "extractor_version",
    }
    assert set(raw.keys()) == expected_keys
