"""Golden lock for the #81 Excel export (PRD §14.3, design §5.2 / Q-A option (i)).

The .xlsx format is a zip of XML with wall-clock timestamps in ``docProps`` and
engine-specific serialization, so byte-comparison is fragile and partly impossible
across openpyxl versions / engines. Instead -- per design Q-A option (i) -- we
write the workbook to a tmp path, read it back, normalize the user-visible
contents (sheet names + order, header + cell values, number formats, conditional-
formatting rule descriptors, disclaimer presence) into a stable JSON snapshot, and
lock that via the #71 :func:`~openbb_techtrade.testing.assert_matches_golden`
harness.

The snapshot covers:

* the canonical 6-sheet set + order (L2)
* every cell value across all sheets, with rows sorted segment -> conviction ->
  action -> symbol (L6)
* the Recommendations sheet's per-column ``number_format`` (Q-E + L9)
* CF rule kinds + target ranges on the Recommendations sheet (§3 / Q-B B1)
* the locked disclaimer string (L3 / Q9 RESOLVED)

Regenerate intentionally with ``TECHTRADE_REGEN_GOLDEN=1`` only after a *reviewed*
change to :data:`SHEET_SPEC`, :data:`FORMAT_SPEC`, the sort key, or any cell value
that flows through the writer.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from openbb_techtrade.models import (
    EntryExitRule,
    ExportConfig,
    Fill,
    IndicatorVote,
    MoverSignal,
    Order,
    Recommendation,
    TradePlan,
)
from openbb_techtrade.reporting.excel_export import (
    CANONICAL_SHEETS,
    DISCLAIMER,
    FORMAT_SPEC,
    SHEET_SPEC,
    export,
)
from openbb_techtrade.testing import assert_matches_golden

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.golden


# Worked-golden inputs aligned with the existing #76 / #77 / #80 fixture conventions.
_AS_OF = date(2024, 1, 12)
_FILL_TS = datetime(2024, 1, 16, 14, 30, tzinfo=timezone.utc)
_ATR = 1.90


def _make_plan(
    symbol: str,
    segment: str,
    *,
    direction: str,
    score: float,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    qty: Decimal,
    action: str,
    conviction: str,
) -> TradePlan:
    """Build a paper-filled TradePlan deterministically (no clock / random sources)."""
    votes = [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0 if direction == "long" else -1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=1.0 if direction == "long" else -1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.8 if direction == "long" else -0.8, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=0.6 if direction == "long" else -0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=1.0 if direction == "long" else -1.0, weight=0.15),
    ]
    sig = MoverSignal(
        symbol=symbol, segment=segment, as_of=_AS_OF,
        score=score, direction=direction, votes=votes, rank_in_segment=1,
    )
    if direction == "flat":
        rec = Recommendation(
            symbol=symbol, segment=segment, as_of=_AS_OF,
            action="HOLD/FLAT", conviction="Low", score=score,
            entry_price=entry, stop_price=entry, target_price=entry,
            stop_distance_pct=0.0, target_distance_pct=0.0, risk_reward=0.0, atr=_ATR,
            position_size=Decimal(0), risk_per_share=Decimal(0),
            risk_pct_of_notional=0.0, time_stop_bars=None,
            reasoning=f"Hold {symbol}: below the entry threshold.",
            top_factors=[], caveats="None.",
        )
        return TradePlan(
            symbol=symbol, segment=segment, as_of=_AS_OF,
            signal=sig, rule=EntryExitRule(), position_size=Decimal(0),
            orders=[], simulated_fills=[], recommendation=rec,
        )

    entry_side, exit_side = (("buy", "sell") if direction == "long" else ("sell_short", "buy_to_cover"))
    risk_per_share = abs(entry - stop)
    rec = Recommendation(
        symbol=symbol, segment=segment, as_of=_AS_OF,
        action=action, conviction=conviction, score=score,
        entry_price=entry, stop_price=stop, target_price=target,
        stop_distance_pct=float(risk_per_share / entry), target_distance_pct=float(abs(target - entry) / entry),
        risk_reward=float(abs(target - entry) / risk_per_share), atr=_ATR,
        position_size=qty, risk_per_share=risk_per_share,
        risk_pct_of_notional=float(qty * risk_per_share / Decimal("100000")),
        time_stop_bars=20,
        reasoning=f"{action} {symbol}: trend confirming.",
        top_factors=["macd_hist+ (trend)", "ema_cross+ (trend)"] if direction == "long" else ["macd_hist- (trend)"],
        caveats="None.",
    )
    orders = [
        Order(symbol=symbol, side=entry_side, quantity=qty, order_type="market", tif="day", intent="entry"),
        Order(symbol=symbol, side=exit_side, quantity=qty, order_type="stop", stop_price=stop, tif="gtc", intent="exit_stop"),
        Order(symbol=symbol, side=exit_side, quantity=qty, order_type="limit", limit_price=target, tif="gtc", intent="exit_target"),
    ]
    fills = [
        Fill(
            order_ref=f"{symbol}:entry", timestamp=_FILL_TS, symbol=symbol, side=entry_side,
            quantity=qty, price=entry, commission=Decimal("0"), slippage=Decimal("0.06"),
        )
    ]
    return TradePlan(
        symbol=symbol, segment=segment, as_of=_AS_OF,
        signal=sig, rule=EntryExitRule(), position_size=qty,
        orders=orders, simulated_fills=fills, recommendation=rec,
    )


def _golden_plans() -> list[TradePlan]:
    """Three plans across two segments: BUY high, SELL_SHORT high, HOLD/FLAT."""
    return [
        _make_plan(
            "NVDA", "Information Technology",
            direction="long", score=0.78, action="BUY", conviction="High",
            entry=Decimal("121.40"), stop=Decimal("117.60"), target=Decimal("129.00"),
            qty=Decimal("263"),
        ),
        _make_plan(
            "GLD", "Materials",
            direction="short", score=-0.78, action="SELL_SHORT", conviction="High",
            entry=Decimal("121.40"), stop=Decimal("125.20"), target=Decimal("113.80"),
            qty=Decimal("263"),
        ),
        _make_plan(
            "JPM", "Financials",
            direction="flat", score=0.05, action="HOLD/FLAT", conviction="Low",
            entry=Decimal("121.40"), stop=Decimal("121.40"), target=Decimal("121.40"),
            qty=Decimal(0),
        ),
    ]


def _snapshot_sheet(ws) -> dict:
    """Read every cell into a JSON-friendly grid (rows x cols of values)."""
    rows = []
    for row_index in range(1, ws.max_row + 1):
        row = []
        for col_index in range(1, ws.max_column + 1):
            value = ws.cell(row=row_index, column=col_index).value
            if isinstance(value, datetime):
                value = value.isoformat()
            row.append(value)
        rows.append(row)
    return {"rows": rows, "max_row": ws.max_row, "max_col": ws.max_column}


def _snapshot_number_formats(ws, header_row: int) -> dict[str, str]:
    """Read the data-row number_format for each column on ``ws``, keyed by header."""
    formats: dict[str, str] = {}
    if ws.max_row < header_row + 1:
        return formats
    for col_index in range(1, ws.max_column + 1):
        header = ws.cell(row=header_row, column=col_index).value
        if header is None:
            continue
        formats[str(header)] = ws.cell(row=header_row + 1, column=col_index).number_format
    return formats


def _snapshot_cf(ws) -> list[dict]:
    """Read every CF rule descriptor on ``ws`` (engine-agnostic structural view)."""
    out: list[dict] = []
    for cell_range, rules in ws.conditional_formatting._cf_rules.items():
        for rule in rules:
            out.append({
                "range": str(cell_range.sqref) if hasattr(cell_range, "sqref") else str(cell_range),
                "type": rule.type,
                "operator": getattr(rule, "operator", None),
                "formula": list(getattr(rule, "formula", []) or []),
            })
    # Sort for stable ordering -- the snapshot must not depend on dict iteration order.
    return sorted(out, key=lambda r: (r["range"], r["type"], r["operator"] or "", str(r["formula"])))


def _snapshot_workbook(path: str) -> dict:
    """Build the JSON snapshot for the golden lock (Q-A option (i))."""
    wb = load_workbook(path)
    snapshot: dict = {"sheets": wb.sheetnames, "disclaimer": DISCLAIMER, "by_sheet": {}}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        # Recommendations table header is on row 4 (title + disclaimer + blank above), others on row 1.
        header_row = 4 if sheet_name == "Recommendations" else 1
        snapshot["by_sheet"][sheet_name] = {
            "cells": _snapshot_sheet(ws),
            "number_formats": _snapshot_number_formats(ws, header_row),
            "conditional_formats": _snapshot_cf(ws),
        }
    return snapshot


def test_export_workbook_matches_golden_snapshot(tmp_path: Path):
    """Q-A option (i): write the workbook, read it back, lock the structural snapshot."""
    out = tmp_path / "techtrade_golden.xlsx"
    path = export(_golden_plans(), config=ExportConfig(path=str(out)))
    snapshot = _snapshot_workbook(path)
    assert_matches_golden("excel_export_recs", snapshot, fixture_dir=FIXTURES)


def test_export_workbook_sheet_set_matches_design(tmp_path: Path):
    """L2: independent of golden, the produced workbook always has the canonical 6 sheets."""
    out = tmp_path / "wb.xlsx"
    path = export(_golden_plans(), config=ExportConfig(path=str(out)))
    wb = load_workbook(path)
    assert wb.sheetnames == list(CANONICAL_SHEETS)


def test_format_spec_only_targets_canonical_sheets():
    """Static check: every FORMAT_SPEC rule targets a canonical sheet + a SHEET_SPEC column."""
    for rule in FORMAT_SPEC:
        assert rule.sheet in CANONICAL_SHEETS, f"FORMAT_SPEC rule targets unknown sheet {rule.sheet!r}"
        columns = [col.header for col in SHEET_SPEC.get(rule.sheet, [])]
        assert rule.column in columns, (
            f"FORMAT_SPEC rule targets unknown column {rule.column!r} on {rule.sheet!r}"
        )
