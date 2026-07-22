"""Tests for Tools/pine/reshape_tv_trades.py — D2.1 (structural validation)
and D2.2 (metadata capture) extensions per the hybrid-fixture-suite
brainstorm response (issue #951).

The existing reshape (shipped in PR #946) already validates:
  - Every Trade number has exactly 2 legs
  - Directions match within a pair
  - No missing entry-or-exit row

D2.1 adds:
  - exit_time > entry_time (chronological order per round-trip)
  - qty is non-negative

D2.2 adds:
  - --symbol / --timeframe / --start / --end / --tv-strategy-settings-json
    CLI flags
  - Companion <fixture>.trades.meta.json emission alongside the CSV

Test strategy: hand-authored TV-shaped CSV fixtures inline (no external
CSV files needed — the shapes are small and reading them from disk would
add fixture-management overhead for zero gain here). R7.1 compliance: the
shapes match REAL TV output verified against
Tools/pine/reshape_tv_trades.py's docstring examples.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make Tools/pine importable — Tools is not a package on the pythonpath
# by default. Same pattern used by Tools/tests/test_parse_fidelity_positions.py.
_TOOLS_PINE_DIR = Path(__file__).resolve().parent.parent / "pine"
sys.path.insert(0, str(_TOOLS_PINE_DIR))

import reshape_tv_trades  # noqa: E402 -- deliberate late import after sys.path insert

# ---------------------------------------------------------------------------
# Test data — minimal TV-shaped CSVs (2 rows per round-trip, exit-then-entry)
# ---------------------------------------------------------------------------

_TV_HEADER = (
    "Trade number,Type,Date and time,Signal,Price USD,Size (qty),Size (value),"
    "Net PnL USD,Return %,Commission USD,Favorable excursion USD,"
    "Favorable excursion %,Adverse excursion USD,Adverse excursion %,"
    "Cumulative PnL USD,Cumulative PnL %,Duration (bars)"
)


def _valid_two_trade_csv() -> str:
    """Two closed round-trips, exit-then-entry per TV convention.

    Trade 1: long AAPL 100 → 110 (win)
    Trade 2: short AAPL 105 → 100 (win)
    """
    return "\n".join(
        [
            _TV_HEADER,
            "1,Exit long,2025-01-05,Close entry(s) order Long,110,10,1100,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            "1,Entry long,2025-01-02,Long,100,10,1000,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            "2,Exit short,2025-01-12,Close entry(s) order Short,100,5,500,25,5.00,0,5,5.00,0,0.00,125,12.50,2",
            "2,Entry short,2025-01-10,Short,105,5,525,25,5.00,0,5,5.00,0,0.00,125,12.50,2",
            "",  # TV often emits a trailing blank line
        ]
    )


# ---------------------------------------------------------------------------
# D2.1 — Structural validation extensions
# ---------------------------------------------------------------------------


def test_valid_csv_still_reshapes_cleanly(tmp_path: Path) -> None:
    """Regression: the pre-existing reshape behavior is unchanged for a
    valid input. All new validation must be additive, not restrictive of
    the passing case.
    """
    inp = tmp_path / "input.csv"
    out = tmp_path / "output.csv"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")

    n = reshape_tv_trades.reshape(inp, out)
    assert n == 2
    assert out.exists()


def test_exit_before_entry_raises(tmp_path: Path) -> None:
    """A round-trip whose exit_time <= entry_time is structurally invalid.
    TV won't emit this shape but a mangled hand-edited CSV might; catch
    it loudly before it poisons the fixture.
    """
    # Trade 1: entry 2025-01-10, exit 2025-01-05 (BAD — exit before entry)
    bad_csv = "\n".join(
        [
            _TV_HEADER,
            "1,Exit long,2025-01-05,Close entry(s) order Long,110,10,1100,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            "1,Entry long,2025-01-10,Long,100,10,1000,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
        ]
    )
    inp = tmp_path / "input.csv"
    out = tmp_path / "output.csv"
    inp.write_text(bad_csv, encoding="utf-8")

    with pytest.raises(ValueError, match=r"(?i)exit.*before.*entry|chronolog"):
        reshape_tv_trades.reshape(inp, out)


def test_exit_equals_entry_raises(tmp_path: Path) -> None:
    """Same-timestamp entry+exit is structurally suspect — either two
    fills on the same bar (rare but real) or a data bug. Reject it and
    let a human confirm rather than silently pass.
    """
    same_time_csv = "\n".join(
        [
            _TV_HEADER,
            "1,Exit long,2025-01-05,Close entry(s) order Long,110,10,1100,100,10.00,0,10,10.00,0,0.00,100,10.00,0",
            "1,Entry long,2025-01-05,Long,100,10,1000,100,10.00,0,10,10.00,0,0.00,100,10.00,0",
        ]
    )
    inp = tmp_path / "input.csv"
    out = tmp_path / "output.csv"
    inp.write_text(same_time_csv, encoding="utf-8")

    with pytest.raises(
        ValueError, match=r"(?i)exit.*before.*entry|chronolog|same.*time"
    ):
        reshape_tv_trades.reshape(inp, out)


def test_negative_qty_raises(tmp_path: Path) -> None:
    """Qty must be non-negative — direction lives in the Type field, not
    in a signed qty. A negative qty is a TV-export corruption or a hand-
    edit bug that would produce nonsense downstream.
    """
    neg_qty_csv = "\n".join(
        [
            _TV_HEADER,
            # Note: -10 in Size (qty) column
            "1,Exit long,2025-01-05,Close entry(s) order Long,110,-10,1100,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            "1,Entry long,2025-01-02,Long,100,-10,1000,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
        ]
    )
    inp = tmp_path / "input.csv"
    out = tmp_path / "output.csv"
    inp.write_text(neg_qty_csv, encoding="utf-8")

    with pytest.raises(ValueError, match=r"(?i)qty|quantity|non.negative"):
        reshape_tv_trades.reshape(inp, out)


def test_error_names_the_offending_trade_number(tmp_path: Path) -> None:
    """When validation fails, the error must name the trade_num so a
    reader can find the row in a large CSV. CLAUDE.md R7.3: loud
    diagnostics.
    """
    bad_csv = "\n".join(
        [
            _TV_HEADER,
            # Trade 1 is fine
            "1,Exit long,2025-01-05,Close entry(s) order Long,110,10,1100,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            "1,Entry long,2025-01-02,Long,100,10,1000,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            # Trade 42 has exit-before-entry
            "42,Exit long,2025-01-05,Close entry(s) order Long,110,10,1100,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
            "42,Entry long,2025-01-10,Long,100,10,1000,100,10.00,0,10,10.00,0,0.00,100,10.00,3",
        ]
    )
    inp = tmp_path / "input.csv"
    out = tmp_path / "output.csv"
    inp.write_text(bad_csv, encoding="utf-8")

    with pytest.raises(ValueError, match=r"42"):
        reshape_tv_trades.reshape(inp, out)


# ---------------------------------------------------------------------------
# D2.2 — Metadata capture
# ---------------------------------------------------------------------------


def test_metadata_json_emitted_when_all_flags_present(tmp_path: Path) -> None:
    """When --symbol / --timeframe / --start / --end are all provided,
    emit a companion <output-stem>.meta.json file capturing them plus
    the tool version + capture timestamp. This becomes the trades_source
    block of provenance.json per the hybrid-fixture-suite brainstorm's
    D1.4.
    """
    inp = tmp_path / "input.csv"
    out = tmp_path / "rsi_reversal.trades.csv"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")

    reshape_tv_trades.reshape(
        inp,
        out,
        metadata={
            "symbol": "NASDAQ:AAPL",
            "timeframe": "1D",
            "start": "2025-01-01",
            "end": "2025-06-30",
        },
    )

    meta_path = tmp_path / "rsi_reversal.trades.meta.json"
    assert meta_path.exists(), "metadata JSON should be emitted next to the CSV"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["symbol"] == "NASDAQ:AAPL"
    assert meta["timeframe"] == "1D"
    assert meta["start"] == "2025-01-01"
    assert meta["end"] == "2025-06-30"
    assert "captured_at" in meta  # ISO date string
    assert "reshape_tool_version" in meta  # semver-ish string
    assert "row_count" in meta and meta["row_count"] == 2


def test_no_metadata_json_when_flags_omitted(tmp_path: Path) -> None:
    """metadata=None → no .meta.json emitted. Back-compat with the
    pre-D2.2 CLI (positional args only).
    """
    inp = tmp_path / "input.csv"
    out = tmp_path / "rsi_reversal.trades.csv"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")

    reshape_tv_trades.reshape(inp, out)

    meta_path = tmp_path / "rsi_reversal.trades.meta.json"
    assert not meta_path.exists()


def test_metadata_json_includes_strategy_settings_when_provided(tmp_path: Path) -> None:
    """When --tv-strategy-settings-json points at a JSON file (the TV
    Strategy Tester's Properties tab exported), embed its contents
    verbatim under `strategy_settings`. This closes reviewer feedback
    A4 (execution model must be pinned).
    """
    inp = tmp_path / "input.csv"
    out = tmp_path / "rsi_reversal.trades.csv"
    settings = tmp_path / "settings.json"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")
    settings.write_text(
        json.dumps(
            {
                "initial_capital": 1_000_000,
                "commission_type": "Percent",
                "commission_value": 0.0,
                "slippage_ticks": 0,
                "pyramiding_max_orders": 1,
                "process_orders_on_close": False,
                "calc_on_every_tick": False,
                "default_qty_type": "fixed",
                "default_qty_value": 1,
            }
        ),
        encoding="utf-8",
    )

    reshape_tv_trades.reshape(
        inp,
        out,
        metadata={
            "symbol": "NASDAQ:AAPL",
            "timeframe": "1D",
            "start": "2025-01-01",
            "end": "2025-06-30",
            "strategy_settings_path": settings,
        },
    )

    meta = json.loads((tmp_path / "rsi_reversal.trades.meta.json").read_text())
    assert "strategy_settings" in meta
    assert meta["strategy_settings"]["initial_capital"] == 1_000_000
    assert meta["strategy_settings"]["commission_type"] == "Percent"
    assert meta["strategy_settings"]["pyramiding_max_orders"] == 1


def test_metadata_json_missing_strategy_settings_path_raises(tmp_path: Path) -> None:
    """If --tv-strategy-settings-json points at a non-existent file, fail
    loudly — don't silently emit metadata without the settings block.
    """
    inp = tmp_path / "input.csv"
    out = tmp_path / "rsi_reversal.trades.csv"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        reshape_tv_trades.reshape(
            inp,
            out,
            metadata={
                "symbol": "AAPL",
                "timeframe": "1D",
                "start": "2025-01-01",
                "end": "2025-06-30",
                "strategy_settings_path": tmp_path / "does_not_exist.json",
            },
        )


# ---------------------------------------------------------------------------
# CLI smoke test — argparse wiring
# ---------------------------------------------------------------------------


def test_cli_positional_args_still_work(tmp_path: Path, monkeypatch) -> None:
    """The original 2-positional-arg CLI still works. Backwards compat."""
    inp = tmp_path / "input.csv"
    out = tmp_path / "output.csv"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["reshape_tv_trades.py", str(inp), str(out)])
    exit_code = reshape_tv_trades.main()
    assert exit_code == 0
    assert out.exists()


def test_cli_new_flags_emit_metadata(tmp_path: Path, monkeypatch) -> None:
    """New CLI: --symbol / --timeframe / --start / --end trigger the
    companion .meta.json emission.
    """
    inp = tmp_path / "input.csv"
    out = tmp_path / "fixture.trades.csv"
    inp.write_text(_valid_two_trade_csv(), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reshape_tv_trades.py",
            str(inp),
            str(out),
            "--symbol",
            "NASDAQ:AAPL",
            "--timeframe",
            "1D",
            "--start",
            "2025-01-01",
            "--end",
            "2025-06-30",
        ],
    )
    exit_code = reshape_tv_trades.main()
    assert exit_code == 0
    assert (tmp_path / "fixture.trades.meta.json").exists()
