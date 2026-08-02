"""Unit tests for #1460 — redact_basket_preview.

The renderer MUST NEVER emit real usernames, CUSIPs, or per-position
weights at the default ``level='aggregate'``. Bucketed level hides the
exact weight number behind a coarse bucket. ``level='raw'`` is escape
hatch for CLI/live use and emits a stderr warning that the notebook
must not be committed after running with it.
"""

from __future__ import annotations

import re

import pytest

from portfolio_snapshot_importer.basket_bridge import (
    _bucket_weight,
    redact_basket_preview,
)

_CUSIP = re.compile(r"\b[0-9A-Z]{8,9}\b")


def _synthetic_basket() -> dict:
    """3-row synthetic basket that exercises every bucket band."""
    return {
        "basket": [
            {"symbol": "MSFT", "weight": 0.3075},  # >30% (concentration)
            {"symbol": "09261F614", "weight": 0.1736},  # 15-30% + CUSIP
            {"symbol": "NVDA", "weight": 0.015},  # <5%
        ],
        "metadata": {
            "source": "portfolio_snapshot_importer",
            "snapshot_id": "hashy",
            "snapshot_date": "2026-07-18",
            "user_id": "alice",  # real-name shape
            "n_positions_in_snapshot": 56,
            "n_positions_in_basket": 3,
        },
    }


class TestBucketWeight:
    """The bucketer never leaks precise weight."""

    @pytest.mark.parametrize(
        "w,expected",
        [
            (0.001, "<5%"),
            (0.049, "<5%"),
            (0.05, "5-15%"),
            (0.149, "5-15%"),
            (0.15, "15-30%"),
            (0.30, ">30%"),
            (0.99, ">30%"),
        ],
    )
    def test_boundaries(self, w: float, expected: str) -> None:
        assert _bucket_weight(w) == expected


class TestAggregateLevel:
    """Default level. Committing this into notebook output is safe."""

    def test_only_counts_no_row_data(self) -> None:
        out = redact_basket_preview(_synthetic_basket())
        # Must have the "3 positions kept of 56" aggregate.
        assert "3 positions" in out
        assert "56" in out
        # Must NOT contain real symbols, CUSIPs, usernames, or weights.
        assert "MSFT" not in out
        assert "NVDA" not in out
        assert "09261F614" not in out
        assert "alice" not in out
        assert not _CUSIP.search(out.replace(" positions kept of ", ""))
        # No percent numbers other than the ones in labels ("<5%", etc.
        # — but those don't appear at aggregate level).
        assert "%" not in out
        assert "30.75" not in out and "17.36" not in out

    def test_aggregate_is_default(self) -> None:
        default_out = redact_basket_preview(_synthetic_basket())
        explicit_out = redact_basket_preview(_synthetic_basket(), level="aggregate")
        assert default_out == explicit_out


class TestBucketedLevel:
    """Pedagogical: shows shape ("you're concentrated") without values."""

    def test_masks_symbols_and_weights(self) -> None:
        out = redact_basket_preview(_synthetic_basket(), level="bucketed")
        # Aggregate line still there.
        assert "3 positions" in out
        # Each real symbol is masked as SYM_i.
        assert "SYM_1" in out
        assert "SYM_2" in out
        assert "SYM_3" in out
        # No real symbols or CUSIP leaked.
        assert "MSFT" not in out
        assert "NVDA" not in out
        assert "09261F614" not in out
        assert not _CUSIP.search(out.replace("SYM_", ""))
        # Buckets present, but no precise weight numbers.
        assert ">30%" in out  # MSFT bucket
        assert "15-30%" in out  # 09261F614 bucket
        assert "<5%" in out  # NVDA bucket
        assert "30.75" not in out and "17.36" not in out and "1.50" not in out


class TestRawLevel:
    """Escape hatch. Must warn on stderr; must contain real values."""

    def test_emits_real_values(self, capsys: pytest.CaptureFixture) -> None:
        out = redact_basket_preview(_synthetic_basket(), level="raw")
        assert "MSFT" in out
        assert "NVDA" in out
        assert "09261F614" in out
        assert "30.75" in out
        assert "17.36" in out
        assert "1.50" in out

    def test_stderr_warning_on_raw(self, capsys: pytest.CaptureFixture) -> None:
        redact_basket_preview(_synthetic_basket(), level="raw")
        err = capsys.readouterr().err
        assert "Do NOT commit" in err
        assert "level='raw'" in err


class TestValidation:
    def test_unknown_level_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown level"):
            redact_basket_preview(_synthetic_basket(), level="bogus")

    def test_empty_basket_still_safe(self) -> None:
        empty = {"basket": [], "metadata": {"n_positions_in_snapshot": 0}}
        out = redact_basket_preview(empty)
        assert "0 positions" in out
        out2 = redact_basket_preview(empty, level="bucketed")
        assert "SYM_" not in out2  # no rows, no masked labels either
