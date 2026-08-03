"""Tests for T5 P3.c reconciliation (#1767)."""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import SqlitePaperEngine
from openbb_techtrade.execution.reconciliation import (
    reconcile,
    reconcile_from_snapshot,
)


@pytest.fixture
def paper_msft_aapl(tmp_path: Path) -> SqlitePaperEngine:
    """Paper engine holding: MSFT 10 @ 400, AAPL 20 @ 180."""
    eng = SqlitePaperEngine(tmp_path / "paper.db", starting_cash=Decimal("100000"))
    for symbol, qty, price in (("MSFT", "10", "400"), ("AAPL", "20", "180")):
        [oid] = eng.submit_batch(
            OrderBatch(
                tickets=(
                    OrderTicket(
                        symbol=symbol,
                        action="Buy",
                        quantity=Decimal(qty),
                        order_type="Limit",
                        limit_price=Decimal(price),
                    ),
                )
            )
        )
        eng.record_fill(
            oid,
            price=Decimal(price),
            filled_qty=Decimal(qty),
            at=datetime.now(timezone.utc),
        )
    return eng


# ---------------------------------------------------------------------------
# All-matched: paper and real agree exactly
# ---------------------------------------------------------------------------


class TestAllMatched:
    def test_full_match_is_reconciled(self, paper_msft_aapl) -> None:
        """R7.11 twin: dropping the `paper_qty == real_qty` check would
        mis-classify matched rows as QTY_VARIANCE. Verified.
        """
        report = reconcile(
            paper_msft_aapl, {"MSFT": Decimal("10"), "AAPL": Decimal("20")}
        )
        assert report.is_reconciled
        assert report.variance_count == 0
        assert len(report.matched) == 2

    def test_decimal_precision_equivalence(self, paper_msft_aapl) -> None:
        """R7.11 twin: 10 == 10.000 with Decimal, but if we cast to float
        somewhere the comparison could go weird. Verified — using Decimal
        end-to-end, 10 and 10.000 are equal.
        """
        report = reconcile(
            paper_msft_aapl, {"MSFT": Decimal("10.000"), "AAPL": Decimal("20.00")}
        )
        assert report.is_reconciled


# ---------------------------------------------------------------------------
# Quantity variance — both sides have it, different quantities
# ---------------------------------------------------------------------------


class TestQuantityVariance:
    def test_qty_variance_computes_correct_delta(self, paper_msft_aapl) -> None:
        """Fidelity has 12 MSFT, paper has 10. Delta = 12 - 10 = +2 (real minus paper).

        R7.11 twin: if delta were `paper - real`, the sign would flip.
        Verified — +2 vs -2 uniquely identifies the ordering.
        """
        report = reconcile(
            paper_msft_aapl, {"MSFT": Decimal("12"), "AAPL": Decimal("20")}
        )
        assert not report.is_reconciled
        [var] = report.qty_variance
        assert var.symbol == "MSFT"
        assert var.paper_qty == Decimal("10")
        assert var.real_qty == Decimal("12")
        assert var.delta == Decimal("2")

    def test_negative_delta_when_paper_over_real(self, paper_msft_aapl) -> None:
        """Paper thinks 10 MSFT, Fidelity says only 8 → delta = -2."""
        report = reconcile(
            paper_msft_aapl, {"MSFT": Decimal("8"), "AAPL": Decimal("20")}
        )
        [var] = report.qty_variance
        assert var.delta == Decimal("-2")


# ---------------------------------------------------------------------------
# PAPER_ONLY — paper says we hold it, real doesn't
# ---------------------------------------------------------------------------


class TestPaperOnly:
    def test_symbol_missing_from_real_is_paper_only(self, paper_msft_aapl) -> None:
        """R7.11 twin: without the `elif paper_qty is not None` branch,
        a paper-only symbol would incorrectly land as QTY_VARIANCE with
        real_qty=0 delta. Verified — the categorization is what
        differentiates 'missed manual fill' from 'wrong quantity'.
        """
        report = reconcile(paper_msft_aapl, {"AAPL": Decimal("20")})
        assert len(report.paper_only) == 1
        [row] = report.paper_only
        assert row.symbol == "MSFT"
        assert row.paper_qty == Decimal("10")
        assert row.real_qty is None
        assert row.delta is None


# ---------------------------------------------------------------------------
# FIDELITY_ONLY — real has it, paper doesn't
# ---------------------------------------------------------------------------


class TestFidelityOnly:
    def test_symbol_missing_from_paper_is_fidelity_only(self, paper_msft_aapl) -> None:
        """R7.11 twin: same discipline as PAPER_ONLY but the other
        direction. The classifier must know which side is missing.
        """
        report = reconcile(
            paper_msft_aapl,
            {"MSFT": Decimal("10"), "AAPL": Decimal("20"), "GOOGL": Decimal("5")},
        )
        assert len(report.fidelity_only) == 1
        [row] = report.fidelity_only
        assert row.symbol == "GOOGL"
        assert row.paper_qty is None
        assert row.real_qty == Decimal("5")


# ---------------------------------------------------------------------------
# Case normalization + zero filtering
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_case_normalization(self, paper_msft_aapl) -> None:
        """Real positions with lowercase symbols still match paper (uppercase).

        R7.11 twin: without the .upper() call, msft != MSFT would produce
        two rows (one PAPER_ONLY, one FIDELITY_ONLY). Verified.
        """
        report = reconcile(
            paper_msft_aapl, {"msft": Decimal("10"), "aapl": Decimal("20")}
        )
        assert report.is_reconciled

    def test_zero_qty_symbols_filtered_out(self, paper_msft_aapl) -> None:
        """A real position that flattened to 0 shouldn't show up as
        variance if paper also flattened. R7.11 twin: without the
        `qty != 0` filter, a stale 0-qty row on either side would
        incorrectly surface as a variance.
        """
        report = reconcile(
            paper_msft_aapl,
            {"MSFT": Decimal("10"), "AAPL": Decimal("20"), "OLD": Decimal("0")},
        )
        assert report.is_reconciled
        assert not any(r.symbol == "OLD" for r in report.rows)


# ---------------------------------------------------------------------------
# reconcile_from_snapshot — None handling
# ---------------------------------------------------------------------------


class TestReconcileFromSnapshot:
    def test_none_snapshot_raises_not_silent(self, paper_msft_aapl) -> None:
        """R7.11 twin: a missing snapshot silently reconciled as "all
        paper-only" would give the operator a false 'no drift' when the
        actual state is 'we couldn't check'.
        """
        with pytest.raises(ValueError, match="no Fidelity snapshot"):
            reconcile_from_snapshot(paper_msft_aapl, None, user_id="daaji")

    def test_empty_snapshot_reconciles_as_all_paper_only(self, paper_msft_aapl) -> None:
        """Empty dict means "we checked and Fidelity has nothing" — legitimate."""
        report = reconcile_from_snapshot(paper_msft_aapl, {}, user_id="daaji")
        assert len(report.paper_only) == 2
        assert report.variance_count == 2


# ---------------------------------------------------------------------------
# Report structural properties
# ---------------------------------------------------------------------------


class TestReportProperties:
    def test_variance_count_matches_non_matched_rows(self, paper_msft_aapl) -> None:
        """R7.11 twin: if variance_count included matched rows, the
        operator's 'action list' would falsely include the ones they
        don't need to act on.
        """
        report = reconcile(
            paper_msft_aapl,
            {"MSFT": Decimal("12"), "GOOGL": Decimal("5")},
        )
        # MSFT: qty_variance. AAPL: paper_only. GOOGL: fidelity_only.
        assert report.variance_count == 3
        assert len(report.matched) == 0

    def test_symbol_counts_reflect_input(self, paper_msft_aapl) -> None:
        report = reconcile(
            paper_msft_aapl,
            {"MSFT": Decimal("10"), "AAPL": Decimal("20"), "GOOGL": Decimal("5")},
        )
        assert report.paper_symbol_count == 2
        assert report.real_symbol_count == 3

    def test_rows_are_alphabetical(self, paper_msft_aapl) -> None:
        report = reconcile(
            paper_msft_aapl,
            {"MSFT": Decimal("10"), "AAPL": Decimal("20"), "GOOGL": Decimal("5")},
        )
        symbols = [r.symbol for r in report.rows]
        assert symbols == sorted(symbols)


# ---------------------------------------------------------------------------
# Cross-cutting: all four kinds in one report
# ---------------------------------------------------------------------------


class TestFullMixedReport:
    def test_all_four_variance_kinds_in_one_report(
        self, paper_msft_aapl, tmp_path: Path
    ) -> None:
        """Extend paper with a third symbol (NVDA) so we can produce every
        classification in a single report.
        """
        [nvda_oid] = paper_msft_aapl.submit_batch(
            OrderBatch(
                tickets=(
                    OrderTicket(
                        symbol="NVDA",
                        action="Buy",
                        quantity=Decimal("5"),
                        order_type="Market",
                    ),
                )
            )
        )
        paper_msft_aapl.record_fill(
            nvda_oid,
            price=Decimal("130"),
            filled_qty=Decimal("5"),
            at=datetime.now(timezone.utc),
        )

        report = reconcile(
            paper_msft_aapl,
            {
                "MSFT": Decimal("10"),  # matched
                "AAPL": Decimal("18"),  # qty variance
                # NVDA missing: paper-only
                "GOOGL": Decimal("3"),  # fidelity-only
            },
        )
        assert len(report.matched) == 1
        assert len(report.qty_variance) == 1
        assert len(report.paper_only) == 1
        assert len(report.fidelity_only) == 1
        assert report.variance_count == 3
