"""Tests for T5 P5 Activity CSV parser + bulk import (#1769)."""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest
from openbb_techtrade.execution.activity_csv_parser import (
    ActivityCsvError,
    ImportSummary,
    ParsedFill,
    _parse_decimal,
    _parse_run_date,
    import_fills,
    match_fills_to_orders,
    parse_activity_csv,
)
from openbb_techtrade.execution.order_sink import OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import (
    OrderStatus,
    SqlitePaperEngine,
)

# ---------------------------------------------------------------------------
# Sample Fidelity Activity CSV (synthetic — mirrors the real format)
# ---------------------------------------------------------------------------

_SAMPLE_CSV = dedent("""\
    Brokerage,Account Number,Description,Date Range,,
    Individual,***1234,History activity,From 2026-01-01 To 2026-01-31,,

    Run Date,Action,Symbol,Description,Type,Quantity,Price,Commission,Fees,Amount
    01/15/2026,YOU BOUGHT,MSFT,MICROSOFT CORP,Cash,50,400.00,1.00,0.00,$(20001.00)
    01/15/2026,YOU BOUGHT,AAPL,APPLE INC,Cash,100,180.00,1.00,0.00,$(18001.00)
    01/15/2026,DIVIDEND RECEIVED,SPAXX,FIDELITY GOVERNMENT MMF,Cash,,,,,$5.42
    01/16/2026,YOU SOLD,NVDA,NVIDIA CORP,Cash,25,140.00,1.00,0.00,$3499.00
    """)


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    p = tmp_path / "activity.csv"
    p.write_text(_SAMPLE_CSV, encoding="utf-8")
    return p


@pytest.fixture
def engine_with_pending(tmp_path: Path) -> SqlitePaperEngine:
    """Engine with PENDING orders for MSFT, AAPL, NVDA on 2026-01-14
    (one day before the CSV's fill dates).
    """
    eng = SqlitePaperEngine(tmp_path / "paper.db", starting_cash=Decimal("100000"))
    # Backdate submission by patching submitted_at via a small helper:
    # simpler: just submit and rely on the date_window_days tolerance.
    for symbol, action, qty, limit in (
        ("MSFT", "Buy", "50", "400.00"),
        ("AAPL", "Buy", "100", "180.00"),
        ("NVDA", "Sell", "25", "140.00"),
    ):
        eng.submit_batch(
            OrderBatch(
                tickets=(
                    OrderTicket(
                        symbol=symbol,
                        action=action,  # type: ignore[arg-type]
                        quantity=Decimal(qty),
                        order_type="Limit",
                        limit_price=Decimal(limit),
                    ),
                )
            )
        )
    return eng


# ---------------------------------------------------------------------------
# parse_activity_csv
# ---------------------------------------------------------------------------


class TestParseCsv:
    def test_parses_three_fills_dividend_filtered(self, csv_path: Path) -> None:
        """R7.11 twin: dropping the _CASH_ACTION_KEYWORDS filter would
        include the SPAXX dividend row and later fail to parse its
        empty quantity/price. Verified.
        """
        fills = parse_activity_csv(csv_path)
        assert len(fills) == 3
        symbols = {f.symbol for f in fills}
        assert symbols == {"MSFT", "AAPL", "NVDA"}

    def test_action_normalization(self, csv_path: Path) -> None:
        """R7.11 twin: `YOU BOUGHT` must map to `Buy` (not `bought`).
        The OrderTicket.action set requires exact strings.
        """
        fills = parse_activity_csv(csv_path)
        by_sym = {f.symbol: f for f in fills}
        assert by_sym["MSFT"].action == "Buy"
        assert by_sym["NVDA"].action == "Sell"

    def test_quantity_and_price_parsed(self, csv_path: Path) -> None:
        fills = parse_activity_csv(csv_path)
        by_sym = {f.symbol: f for f in fills}
        assert by_sym["MSFT"].quantity == Decimal("50")
        assert by_sym["MSFT"].price == Decimal("400.00")

    def test_commission_parsed(self, csv_path: Path) -> None:
        fills = parse_activity_csv(csv_path)
        by_sym = {f.symbol: f for f in fills}
        assert by_sym["MSFT"].commission == Decimal("1.00")

    def test_run_date_is_utc_midnight(self, csv_path: Path) -> None:
        fills = parse_activity_csv(csv_path)
        by_sym = {f.symbol: f for f in fills}
        assert by_sym["MSFT"].at == datetime(2026, 1, 15, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestParseErrors:
    def test_missing_header_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.csv"
        p.write_text("garbage,file,no,columns\n1,2,3,4\n", encoding="utf-8")
        with pytest.raises(ActivityCsvError, match="required columns"):
            parse_activity_csv(p)

    def test_unrecognized_action_raises(self, tmp_path: Path) -> None:
        """R7.11 twin: silently dropping an unknown action would
        under-import fills; loud raise catches schema drift.
        """
        p = tmp_path / "novel.csv"
        p.write_text(
            "Run Date,Action,Symbol,Description,Type,Quantity,Price\n"
            "01/15/2026,ALIEN OPERATION,XYZ,,,10,100.00\n",
            encoding="utf-8",
        )
        with pytest.raises(ActivityCsvError, match="unrecognized"):
            parse_activity_csv(p)

    def test_pending_update_price_raises(self, tmp_path: Path) -> None:
        """R7.11 twin: Fidelity's 'Pending Update' cell means the trade
        hasn't settled — we can't record a fill for an unknown price.
        """
        p = tmp_path / "pending.csv"
        p.write_text(
            "Run Date,Action,Symbol,Description,Type,Quantity,Price\n"
            "01/15/2026,YOU BOUGHT,MSFT,,,50,Pending Update\n",
            encoding="utf-8",
        )
        with pytest.raises(ActivityCsvError, match="Pending Update"):
            parse_activity_csv(p)


# ---------------------------------------------------------------------------
# _parse_decimal helpers
# ---------------------------------------------------------------------------


class TestParseDecimal:
    def test_plain(self) -> None:
        assert _parse_decimal("400.00") == Decimal("400.00")

    def test_currency_prefix(self) -> None:
        assert _parse_decimal("$1,234.56") == Decimal("1234.56")

    def test_parenthesized_negative(self) -> None:
        """R7.11 twin: Fidelity uses () for negatives (accounting
        format). Missing this would silently misparse -100 as +100.
        """
        assert _parse_decimal("(1,000.00)") == Decimal("-1000.00")

    def test_percentage(self) -> None:
        assert _parse_decimal("12.34%") == Decimal("12.34")

    def test_empty_raises(self) -> None:
        with pytest.raises(ActivityCsvError, match="empty"):
            _parse_decimal("")


class TestParseRunDate:
    def test_mmddyyyy(self) -> None:
        d = _parse_run_date("01/15/2026")
        assert d == datetime(2026, 1, 15, tzinfo=timezone.utc)

    def test_iso(self) -> None:
        d = _parse_run_date("2026-01-15")
        assert d == datetime(2026, 1, 15, tzinfo=timezone.utc)

    def test_unrecognized_raises(self) -> None:
        with pytest.raises(ActivityCsvError, match="unparseable Run Date"):
            _parse_run_date("nonsense")


# ---------------------------------------------------------------------------
# match_fills_to_orders
# ---------------------------------------------------------------------------


class TestMatcher:
    def test_matches_symbol_side_qty(
        self,
        engine_with_pending: SqlitePaperEngine,
    ) -> None:
        """3 fills, 3 orders → 3 matches, 0 unmatched."""
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("50"),
                price=Decimal("400"),
                commission=Decimal("1"),
                at=datetime.now(timezone.utc),
            ),
            ParsedFill(
                symbol="AAPL",
                action="Buy",
                quantity=Decimal("100"),
                price=Decimal("180"),
                commission=Decimal("1"),
                at=datetime.now(timezone.utc),
            ),
            ParsedFill(
                symbol="NVDA",
                action="Sell",
                quantity=Decimal("25"),
                price=Decimal("140"),
                commission=Decimal("1"),
                at=datetime.now(timezone.utc),
            ),
        ]
        matched, unmatched = match_fills_to_orders(fills, engine_with_pending)
        assert len(matched) == 3
        assert unmatched == []

    def test_wrong_side_unmatched(self, engine_with_pending: SqlitePaperEngine) -> None:
        """R7.11 twin: without the side check, a Sell fill could match
        a Buy order. Verified — the direction matters for cash + P&L.
        """
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Sell",  # engine has BUY MSFT PENDING
                quantity=Decimal("50"),
                price=Decimal("400"),
                commission=Decimal("0"),
                at=datetime.now(timezone.utc),
            ),
        ]
        matched, unmatched = match_fills_to_orders(fills, engine_with_pending)
        assert matched == []
        assert len(unmatched) == 1

    def test_partial_fill_matches(self, engine_with_pending: SqlitePaperEngine) -> None:
        """Fill for 30 of 50 MSFT should match — partial fills are OK."""
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("30"),
                price=Decimal("400"),
                commission=Decimal("0"),
                at=datetime.now(timezone.utc),
            ),
        ]
        matched, unmatched = match_fills_to_orders(fills, engine_with_pending)
        assert len(matched) == 1

    def test_overfill_unmatched(self, engine_with_pending: SqlitePaperEngine) -> None:
        """Fill for 100 MSFT when order is only 50 → unmatched (matcher
        won't create an overfill situation).
        """
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("100"),  # > 50 ordered
                price=Decimal("400"),
                commission=Decimal("0"),
                at=datetime.now(timezone.utc),
            ),
        ]
        matched, unmatched = match_fills_to_orders(fills, engine_with_pending)
        assert matched == []
        assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# import_fills
# ---------------------------------------------------------------------------


class TestImportFills:
    def test_dry_run_reports_but_does_not_import(
        self,
        engine_with_pending: SqlitePaperEngine,
    ) -> None:
        """R7.11 twin: dry_run must NOT touch the engine. Verified —
        after dry_run, all orders remain PENDING.
        """
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("50"),
                price=Decimal("400"),
                commission=Decimal("1"),
                at=datetime.now(timezone.utc),
            ),
        ]
        summary = import_fills(fills, engine_with_pending, dry_run=True)
        assert isinstance(summary, ImportSummary)
        assert summary.dry_run is True
        assert summary.imported == 0
        assert len(summary.matched) == 1
        # Engine state unchanged.
        pending = [
            o
            for o in engine_with_pending.get_orders()
            if o.status == OrderStatus.PENDING
        ]
        assert len(pending) == 3

    def test_real_import_records_fills(
        self,
        engine_with_pending: SqlitePaperEngine,
    ) -> None:
        """Full run should record every matched fill."""
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("50"),
                price=Decimal("400"),
                commission=Decimal("1"),
                at=datetime.now(timezone.utc),
            ),
        ]
        summary = import_fills(fills, engine_with_pending, dry_run=False)
        assert summary.imported == 1
        # MSFT order should now be FILLED.
        msft = [o for o in engine_with_pending.get_orders() if o.symbol == "MSFT"][0]
        assert msft.status == OrderStatus.FILLED

    def test_unmatched_raises_by_default(
        self,
        engine_with_pending: SqlitePaperEngine,
    ) -> None:
        """R7.11 twin: silent unmatched fills would silently under-
        import, drifting the paper book from reality.
        """
        fills = [
            ParsedFill(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("50"),
                price=Decimal("400"),
                commission=Decimal("0"),
                at=datetime.now(timezone.utc),
            ),
            ParsedFill(
                symbol="GOOGL",  # no matching order
                action="Buy",
                quantity=Decimal("10"),
                price=Decimal("180"),
                commission=Decimal("0"),
                at=datetime.now(timezone.utc),
            ),
        ]
        with pytest.raises(ActivityCsvError, match="no matching"):
            import_fills(fills, engine_with_pending, dry_run=False)

    def test_end_to_end_from_csv(
        self,
        tmp_path: Path,
        engine_with_pending: SqlitePaperEngine,
    ) -> None:
        """Full parse → match → import flow.

        Fill dates must be >= order submission date (a real fill can't
        precede its own order). We regenerate the CSV with today's date
        so the matcher's window logic is satisfied.

        The NVDA row is a SELL, so we need a long NVDA position first —
        establish one via a prior buy + fill before running the import.
        """
        # Establish an NVDA long via a full round-trip through the engine.
        [nvda_buy_id] = engine_with_pending.submit_batch(
            OrderBatch(
                tickets=(
                    OrderTicket(
                        symbol="NVDA",
                        action="Buy",
                        quantity=Decimal("25"),
                        order_type="Market",
                    ),
                )
            )
        )
        engine_with_pending.record_fill(
            nvda_buy_id,
            price=Decimal("135"),
            filled_qty=Decimal("25"),
            at=datetime.now(timezone.utc),
        )

        today = datetime.now(timezone.utc).date()
        today_str = today.strftime("%m/%d/%Y")
        p = tmp_path / "activity_today.csv"
        p.write_text(
            "Run Date,Action,Symbol,Description,Type,Quantity,Price,Commission,Fees,Amount\n"
            f"{today_str},YOU BOUGHT,MSFT,MICROSOFT CORP,Cash,50,400.00,1.00,0.00,$(20001.00)\n"
            f"{today_str},YOU BOUGHT,AAPL,APPLE INC,Cash,100,180.00,1.00,0.00,$(18001.00)\n"
            f"{today_str},YOU SOLD,NVDA,NVIDIA CORP,Cash,25,140.00,1.00,0.00,$3499.00\n",
            encoding="utf-8",
        )
        fills = parse_activity_csv(p)
        summary = import_fills(fills, engine_with_pending, dry_run=False)
        assert summary.imported == 3
        # All 3 CSV-imported orders should be FILLED + the setup NVDA buy = 4.
        filled = [
            o
            for o in engine_with_pending.get_orders()
            if o.status == OrderStatus.FILLED
        ]
        assert len(filled) == 4
