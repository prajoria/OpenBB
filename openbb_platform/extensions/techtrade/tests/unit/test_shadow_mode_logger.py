"""Tests for the shadow-mode logger (bd-7ct.12, bd-9yg).

Shadow mode = compute BOTH panels (classic + extended), act on the
extended, log the divergence. Design spec §D2 + §D8 justify the pattern:
once family PRs land, shadow logs let us empirically measure whether the
extended panel is materially different before defaulting it on. Feature-
toggle canary deployment applied to trading signals.

**In bd-7ct (stubs pass-through):** divergence is always zero. Every
test in this file confirms zero-delta behavior. Family PRs will add
tests that assert *non-zero* deltas — this file establishes the
zero-drift baseline.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine import confluence, indicators
from openbb_techtrade.engine.panel_config import PANEL_CLASSIC, PANEL_EXTENDED
from openbb_techtrade.engine.panel_eval import (
    ShadowDiff,
    shadow_diff,
    write_shadow_log,
)


def _make_ohlcv_records(n: int = 100) -> list[dict]:
    """Same synthetic OHLCV as the other test files."""
    import pandas_ta_classic  # noqa: F401 - registers .ta
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 + np.arange(n) * 0.5
    df = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000_000.0) + np.arange(n) * 100,
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df.reset_index(names="timestamp").to_dict(orient="records")


@pytest.fixture(scope="module")
def classic_and_extended_signals():
    """Build one classic + one extended signal on the same panel for
    ``shadow_diff`` to compare."""
    records = _make_ohlcv_records(100)
    as_of = date(2024, 5, 20)
    panel_classic = indicators.build_indicator_panel(
        symbol="TEST", as_of=as_of, ohlcv_rows=records,
        panel_config=PANEL_CLASSIC,
    )
    panel_extended = indicators.build_indicator_panel(
        symbol="TEST", as_of=as_of, ohlcv_rows=records,
        panel_config=PANEL_EXTENDED,
    )
    sig_classic = confluence.build_signal(
        panel_classic, segment="TEST_SECTOR", panel_config=PANEL_CLASSIC,
    )
    sig_extended = confluence.build_signal(
        panel_extended, segment="TEST_SECTOR", panel_config=PANEL_EXTENDED,
    )
    return sig_classic, sig_extended


# --------------------------------------------------------------------------- #
# ShadowDiff dataclass
# --------------------------------------------------------------------------- #


class TestShadowDiffShape:
    """The dataclass fields are the contract downstream analysis code
    relies on. Drift would break parquet schema."""

    def test_all_fields_present(self, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)
        assert isinstance(diff, ShadowDiff)
        for field in ("symbol", "as_of", "score_delta",
                      "vote_count_classic", "vote_count_extended",
                      "added_vote_names", "removed_vote_names",
                      "per_family_score_delta"):
            assert hasattr(diff, field), f"ShadowDiff missing field: {field}"


class TestShadowDiffZeroDeltasToday:
    """In bd-7ct (stubs pass-through), classic and extended signals are
    byte-identical, so every delta must be exactly 0.0 (float equality,
    not approx — we're not doing floating-point arithmetic on the panel
    dispatch)."""

    def test_score_delta_is_zero(self, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        assert shadow_diff(sig_classic, sig_extended).score_delta == 0.0

    def test_vote_counts_equal(self, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)
        assert diff.vote_count_classic == diff.vote_count_extended

    def test_no_added_or_removed_votes(self, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)
        assert diff.added_vote_names == []
        assert diff.removed_vote_names == []

    def test_per_family_deltas_all_zero(self, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)
        for family, delta in diff.per_family_score_delta.items():
            assert delta == 0.0, (
                f"family {family} shows non-zero delta {delta} in bd-7ct "
                f"— pass-through stubs must produce byte-identical votes."
            )


# --------------------------------------------------------------------------- #
# shadow_diff detects non-identity (simulate the future family-PR world)
# --------------------------------------------------------------------------- #


class TestShadowDiffDetectsRealDifferences:
    """R7.11 forward-looking: family PRs will diverge extended from
    classic. The diff primitive must detect three kinds of divergence:
    score drift, vote-count change, and family-slice score movement."""

    def test_score_delta_captures_difference(self, classic_and_extended_signals):
        """Manually construct an "extended" signal with a different
        score — diff must report score_delta = extended - classic."""
        sig_classic, sig_extended = classic_and_extended_signals
        # Fabricate a diverged extended signal (pydantic v2 model_copy)
        sig_ext_diverged = sig_extended.model_copy(update={"score": sig_extended.score + 0.15})
        diff = shadow_diff(sig_classic, sig_ext_diverged)
        assert abs(diff.score_delta - 0.15) < 1e-9

    def test_added_votes_captured(self, classic_and_extended_signals):
        """If the extended signal has vote names the classic doesn't,
        they appear in ``added_vote_names``."""
        from openbb_techtrade.models import IndicatorVote
        sig_classic, sig_extended = classic_and_extended_signals
        # Append a fabricated new vote to the extended signal
        new_votes = list(sig_extended.votes) + [
            IndicatorVote(family="trend", name="aroon_osc", vote=0.5, weight=0.4)
        ]
        sig_ext_augmented = sig_extended.model_copy(update={"votes": new_votes})
        diff = shadow_diff(sig_classic, sig_ext_augmented)
        assert "aroon_osc" in diff.added_vote_names
        assert diff.vote_count_extended == diff.vote_count_classic + 1

    def test_removed_votes_captured(self, classic_and_extended_signals):
        """Symmetric: if classic has vote names extended lacks,
        they appear in ``removed_vote_names``. Unusual for a widening
        expansion but a real possibility if the reviewer's C1 (drop
        MACD signal-cross) style change ever removes a classic vote."""
        sig_classic, sig_extended = classic_and_extended_signals
        # Simulate extended having dropped one classic vote
        pruned = [v for v in sig_extended.votes if v.name != "ema_cross"]
        sig_ext_pruned = sig_extended.model_copy(update={"votes": pruned})
        diff = shadow_diff(sig_classic, sig_ext_pruned)
        assert "ema_cross" in diff.removed_vote_names


# --------------------------------------------------------------------------- #
# write_shadow_log
# --------------------------------------------------------------------------- #


class TestWriteShadowLog:
    """Parquet writer for the shadow log. Rows-per-symbol-per-day; each
    row is a ``ShadowDiff`` flattened."""

    def test_writes_parquet_file(self, tmp_path, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)
        write_shadow_log([diff], out_dir=tmp_path)

        # Parquet file with today's date should exist
        matching = list(tmp_path.glob("panel_shadow_*.parquet"))
        assert len(matching) == 1
        df = pd.read_parquet(matching[0])
        assert len(df) == 1
        assert "symbol" in df.columns
        assert "score_delta" in df.columns

    def test_appends_to_existing_file(self, tmp_path, classic_and_extended_signals):
        """Two writes with different (symbol, date) tuples produce a
        2-row file. Idempotent-append is important because scans run
        in batches — each batch's write should extend, not overwrite."""
        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)
        write_shadow_log([diff], out_dir=tmp_path)
        write_shadow_log([diff], out_dir=tmp_path)

        matching = list(tmp_path.glob("panel_shadow_*.parquet"))
        assert len(matching) == 1  # same date → same file
        df = pd.read_parquet(matching[0])
        assert len(df) == 2

    def test_missing_dir_survives_with_warning(self, tmp_path, classic_and_extended_signals, caplog):
        """R7.3 loud-empty: if the target dir doesn't exist AND can't be
        created (parent is a file, or permission denied), log a WARNING
        and continue — do NOT blow up the whole pipeline. Trading
        pipelines should never crash on a telemetry write failure."""
        # Create a file where the shadow dir would need to be
        blocker = tmp_path / "blocked"
        blocker.write_text("this is a file, not a dir")
        # Try to write into a subdir of the file — will fail
        bad_dir = blocker / "cannot_exist"

        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)

        with caplog.at_level(logging.WARNING, logger="openbb_techtrade.engine.panel_eval"):
            write_shadow_log([diff], out_dir=bad_dir)

        # Should have logged a warning, not raised
        assert any(
            "shadow log" in record.getMessage().lower()
            for record in caplog.records
        ), (
            f"expected R7.3 WARNING on write failure; got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_empty_diff_list_is_no_op(self, tmp_path):
        """No diffs → no file. Not an error — a scan with only the
        classic panel (flag=False) never accumulates diffs."""
        write_shadow_log([], out_dir=tmp_path)
        assert list(tmp_path.glob("panel_shadow_*.parquet")) == []

    def test_missing_dir_warning_includes_diagnostic_content(
        self, tmp_path, classic_and_extended_signals, caplog,
    ):
        """iter-1 pr-test L1: the WARNING on write failure must include
        enough diagnostic content that ops can debug from the log line
        alone — the target path AND the underlying exception class.
        A bare "shadow log write failed" is not actionable."""
        blocker = tmp_path / "blocked"
        blocker.write_text("this is a file, not a dir")
        bad_dir = blocker / "cannot_exist"

        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)

        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.engine.panel_eval",
        ):
            write_shadow_log([diff], out_dir=bad_dir)

        matching = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and str(bad_dir) in r.getMessage()
        ]
        assert matching, (
            f"WARNING must include the bad path {bad_dir}; got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_parquet_write_failure_survives_with_warning(
        self, tmp_path, classic_and_extended_signals, caplog, monkeypatch,
    ):
        """iter-1 pr-test L3: the second write-failure branch (parquet
        engine raises AFTER the dir is created) also gracefully logs
        + returns. Monkeypatch ``pd.DataFrame.to_parquet`` to raise;
        the shadow logger must warn, not crash."""
        import pandas as pd

        def _raise(*args, **kwargs):
            raise OSError("disk full simulation")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise)

        sig_classic, sig_extended = classic_and_extended_signals
        diff = shadow_diff(sig_classic, sig_extended)

        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.engine.panel_eval",
        ):
            # Must NOT raise
            write_shadow_log([diff], out_dir=tmp_path)

        assert any(
            "disk full simulation" in r.getMessage()
            for r in caplog.records
        ), (
            f"parquet write failure must be logged with the underlying "
            f"error message; got: {[r.getMessage() for r in caplog.records]}"
        )


class TestShadowDiffSymbolMismatch:
    """iter-1 silent-hunter F2 + pr-test M1: ``shadow_diff`` MUST fail
    loud on (symbol, as_of) mismatch — the previous docstring said the
    intent was "catch loudly" but the code didn't. Now it does.

    Load-bearing R7.11: mutating the ``if a != b: raise`` guards back
    to permissive behavior would silently canonicalise mismatched-symbol
    rows into the log, producing garbage divergence stats family PRs
    would then over-interpret."""

    def test_mismatched_symbol_raises(self, classic_and_extended_signals):
        sig_classic, sig_extended = classic_and_extended_signals
        # Fabricate an extended signal for a DIFFERENT symbol
        sig_ext_wrong_symbol = sig_extended.model_copy(update={"symbol": "OTHER"})
        with pytest.raises(ValueError, match="symbol mismatch"):
            shadow_diff(sig_classic, sig_ext_wrong_symbol)

    def test_mismatched_as_of_raises(self, classic_and_extended_signals):
        from datetime import date

        sig_classic, sig_extended = classic_and_extended_signals
        # Extended for a different session
        sig_ext_wrong_date = sig_extended.model_copy(update={"as_of": date(2023, 1, 1)})
        with pytest.raises(ValueError, match="as_of mismatch"):
            shadow_diff(sig_classic, sig_ext_wrong_date)
