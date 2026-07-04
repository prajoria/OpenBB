"""Multi-sheet Excel recommendation export (issue #81, PRD §14.3).

The report-generator face of techtrade: turn a list of paper-filled
:class:`~openbb_techtrade.models.TradePlan` into a polished, deterministic
**6-sheet ``.xlsx`` workbook** (Recommendations, Levels, Reasoning, Orders, Fills,
Summary) with conditional formatting, a per-workbook compliance disclaimer
(*"Research/paper output - not investment advice"*) on the Recommendations sheet,
and a freezable / filterable header row.

The module is **pure + offline + deterministic** (design L6):

* Depends on :mod:`openbb_techtrade.models`, :mod:`pandas`, and :mod:`openpyxl` only.
  :mod:`xlsxwriter` is imported **lazily**, only when ``engine="xlsxwriter"``. No
  ``obb.*`` call, no network, no ``openbb.build()`` requirement.
* Single source of truth for layout: :data:`SHEET_SPEC` declares every sheet's
  ordered ``(column header, accessor)`` pairs; the per-sheet ``_build_*_df``
  helpers are thin DataFrame-builders over that spec. Adding / renaming /
  reordering a column is a one-line edit to ``SHEET_SPEC`` (mirrors the
  ``selector.SOURCE_TABLE`` discipline from #73).
* Single source of truth for conditional formatting: :data:`FORMAT_SPEC` declares
  every CF rule descriptor (target column, kind, thresholds / colors). Two thin
  engine appliers (:func:`_apply_openpyxl_cf`, :func:`_apply_xlsxwriter_cf`)
  render the same spec onto each engine -- one place to maintain (design Q-B B1).
* Rows are sorted by ``segment`` then ``conviction`` then ``symbol`` (L6), with
  ``conviction`` ordered ``High > Medium > Low`` so the strongest setups float to
  the top of each segment band.
* Money / quantities stay :class:`~decimal.Decimal` end-to-end; cells store the
  unrounded ``float(Decimal)`` and Excel ``number_format`` controls *display*
  rounding only (design Q-E + L9 -- presentation is not storage).
* The only datetime cell written is :class:`~openbb_techtrade.models.Fill`'s
  deterministic ``timestamp`` (the *t+1* session-close localized by #78 Q-F).
  ``datetime.now()`` is never called -- the filename date is the run's ``as_of``.

The headline determinism win: identical ``plans`` + ``context`` produce an
identical *logical* workbook (sheets / values / formats / CF descriptors). That
is what the #71-harness golden lock asserts (design Q-A option (i): structural
snapshot, not raw bytes -- the .xlsx zip carries wall-clock ``docProps``
timestamps and engine-specific XML quirks that byte-comparison cannot survive).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import (
    CellIsRule,
    ColorScaleRule,
    DataBarRule,
)
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from openbb_techtrade.models import (
    ExportConfig,
    Fill,
    IndicatorVote,
    Order,
    Recommendation,
    TradePlan,
)

#: Compliance disclaimer printed on the Recommendations title block (design L3 / Q9 RESOLVED).
DISCLAIMER: str = "Research/paper output - not investment advice"

#: The canonical sheet ordering (design L2). ``ExportConfig.include_sheets`` may subset but never reorder.
CANONICAL_SHEETS: tuple[str, ...] = (
    "Recommendations",
    "Levels",
    "Reasoning",
    "Orders",
    "Fills",
    "Summary",
)

#: Conviction sort order (design L6 -- High first inside each segment band).
_CONVICTION_RANK: dict[str, int] = {"High": 0, "Medium": 1, "Low": 2}

#: Action sort order (design Q-C -- BUY first, then SELL_SHORT, then HOLD/FLAT).
_ACTION_RANK: dict[str, int] = {"BUY": 0, "SELL_SHORT": 1, "HOLD/FLAT": 2}

#: Currency display format (Q-E).
_CURRENCY_FMT = '"$"#,##0.00'
#: Share / qty display format (Q-E).
_QTY_FMT = "#,##0"
#: Score display format with explicit sign (Q-E).
_SCORE_FMT = "+0.00;-0.00"
#: R:R display format -- 1dp (Q-E).
_RR_FMT = "0.0"
#: Percent literal-suffix format -- avoids Excel's ``'0.0%'`` x100 (design Q-E option a).
_PCT_FMT = '0.00"%"'
#: Risk-fraction format -- input is already a fraction (e.g. 0.009994); display as percent x100 (Q-E).
_RISK_PCT_FMT = "0.00%"

#: Engine-agnostic conditional-formatting rule kinds (design FORMAT_SPEC, Q-B B1).
_CFKind = Literal[
    "action_fill",
    "conviction_shade",
    "data_bar",
    "color_scale_3",
    "color_scale_3_centered",
]


@dataclass(frozen=True)
class ColumnSpec:
    """One column on a sheet: header label + accessor.

    The ``accessor`` is a callable taking the row's source object (a ``TradePlan``,
    an ``Order``, a ``Fill``, or a Summary key) and returning the raw value to
    write into the cell. Returning ``None`` leaves the cell blank; returning a
    :class:`~decimal.Decimal` lets the writer coerce to ``float(Decimal)``
    once at the cell-write boundary (Q-E unrounded storage).

    Parameters
    ----------
    header : str
        The column header text shown in row 1 of the sheet.
    accessor : Callable[[Any], Any]
        Function that extracts this column's raw value from a row source.
    number_format : str | None, optional
        Excel display format applied to every cell in this column (e.g.
        ``'"$"#,##0.00'``). ``None`` leaves the cell with its default format.
    """

    header: str
    accessor: Callable[[Any], Any]
    number_format: str | None = None


@dataclass(frozen=True)
class CFRule:
    """One conditional-formatting rule descriptor (engine-agnostic, design FORMAT_SPEC).

    Rules are declared **once** here, then rendered by :func:`_apply_openpyxl_cf`
    (the in-scope default engine, design Q-B B1) and by
    :func:`_apply_xlsxwriter_cf` (best-effort richer, no parity required for v1).

    Parameters
    ----------
    sheet : str
        Sheet name the rule applies to.
    column : str
        Column header the rule targets (resolved to a column index via the
        sheet's header row -- so a column reorder in :data:`SHEET_SPEC`
        relocates the rule automatically).
    kind : _CFKind
        Rule kind (action fill, conviction shade, data-bar, 3-color scale).
    """

    sheet: str
    column: str
    kind: _CFKind


# ---------------------------------------------------------------------------
# SHEET_SPEC -- the single source of truth for sheet / column layout (Q-C)
# ---------------------------------------------------------------------------


def _rec(plan: TradePlan) -> Recommendation:
    """Return the plan's recommendation -- thin alias for accessor readability."""
    return plan.recommendation


def _votes_by_family(votes: list[IndicatorVote], family: str) -> float:
    """Sum ``vote * weight`` over a family (the #74 attribution key, sign-preserving).

    The Reasoning sheet renders one column per family (design Q-C answer 2) holding
    the **signed family contribution** -- compact + readable, while the full
    per-vote breakdown stays in the ``reasoning`` narrative and ``top_factors``.
    """
    return sum(vote.weight * vote.vote for vote in votes if vote.family == family)


def _truncate(text: str | None, max_len: int = 60) -> str:
    """Truncate a long text field to ``max_len`` chars with an ellipsis (Q-C Reasoning short)."""
    if not text:
        return ""
    return text if len(text) <= max_len else text[: max_len - 1] + "..."


def _factors(plan: TradePlan) -> str:
    """Join ``top_factors`` for the Reasoning sheet (comma + space)."""
    return ", ".join(plan.recommendation.top_factors)


#: SHEET_SPEC -- the single declarative source of truth for sheet layout (design Q-C / §1 module rule).
SHEET_SPEC: dict[str, list[ColumnSpec]] = {
    "Recommendations": [
        ColumnSpec("Segment", lambda p: _rec(p).segment),
        ColumnSpec("Symbol", lambda p: _rec(p).symbol),
        ColumnSpec("Action", lambda p: _rec(p).action),
        ColumnSpec("Conviction", lambda p: _rec(p).conviction),
        ColumnSpec("Score", lambda p: _rec(p).score, number_format=_SCORE_FMT),
        ColumnSpec("Entry", lambda p: _rec(p).entry_price, number_format=_CURRENCY_FMT),
        ColumnSpec("Stop", lambda p: _rec(p).stop_price, number_format=_CURRENCY_FMT),
        ColumnSpec(
            "Target", lambda p: _rec(p).target_price, number_format=_CURRENCY_FMT
        ),
        ColumnSpec(
            "Stop %",
            lambda p: _rec(p).stop_distance_pct * 100.0,
            number_format=_PCT_FMT,
        ),
        ColumnSpec("R:R", lambda p: _rec(p).risk_reward, number_format=_RR_FMT),
        ColumnSpec("Shares", lambda p: _rec(p).position_size, number_format=_QTY_FMT),
        ColumnSpec("Reasoning", lambda p: _truncate(_rec(p).reasoning)),
    ],
    "Levels": [
        ColumnSpec("Symbol", lambda p: _rec(p).symbol),
        ColumnSpec("Entry", lambda p: _rec(p).entry_price, number_format=_CURRENCY_FMT),
        ColumnSpec("Stop", lambda p: _rec(p).stop_price, number_format=_CURRENCY_FMT),
        ColumnSpec(
            "Target", lambda p: _rec(p).target_price, number_format=_CURRENCY_FMT
        ),
        ColumnSpec(
            "Stop Distance %",
            lambda p: _rec(p).stop_distance_pct * 100.0,
            number_format=_PCT_FMT,
        ),
        ColumnSpec(
            "Target Distance %",
            lambda p: _rec(p).target_distance_pct * 100.0,
            number_format=_PCT_FMT,
        ),
        ColumnSpec("ATR(14)", lambda p: _rec(p).atr),
        ColumnSpec(
            "Risk/Share", lambda p: _rec(p).risk_per_share, number_format=_CURRENCY_FMT
        ),
        ColumnSpec(
            "Risk %",
            lambda p: _rec(p).risk_pct_of_notional,
            number_format=_RISK_PCT_FMT,
        ),
        ColumnSpec("Time Stop (bars)", lambda p: _rec(p).time_stop_bars),
    ],
    "Reasoning": [
        ColumnSpec("Symbol", lambda p: _rec(p).symbol),
        ColumnSpec("Reasoning (full)", lambda p: _rec(p).reasoning),
        ColumnSpec("Top Factors", _factors),
        ColumnSpec("Caveats", lambda p: _rec(p).caveats),
        ColumnSpec(
            "Trend",
            lambda p: _votes_by_family(p.signal.votes, "trend"),
            number_format=_SCORE_FMT,
        ),
        ColumnSpec(
            "Momentum",
            lambda p: _votes_by_family(p.signal.votes, "momentum"),
            number_format=_SCORE_FMT,
        ),
        ColumnSpec(
            "Volatility",
            lambda p: _votes_by_family(p.signal.votes, "volatility"),
            number_format=_SCORE_FMT,
        ),
        ColumnSpec(
            "Volume",
            lambda p: _votes_by_family(p.signal.votes, "volume"),
            number_format=_SCORE_FMT,
        ),
    ],
    "Orders": [
        ColumnSpec("Symbol", lambda o: o.symbol),
        ColumnSpec("Side", lambda o: o.side),
        ColumnSpec("Qty", lambda o: o.quantity, number_format=_QTY_FMT),
        ColumnSpec("Type", lambda o: o.order_type),
        ColumnSpec("Limit", lambda o: o.limit_price, number_format=_CURRENCY_FMT),
        ColumnSpec("Stop", lambda o: o.stop_price, number_format=_CURRENCY_FMT),
        ColumnSpec("TIF", lambda o: o.tif),
        ColumnSpec("Intent", lambda o: o.intent),
    ],
    "Fills": [
        ColumnSpec("Symbol", lambda f: f.symbol),
        ColumnSpec("Side", lambda f: f.side),
        ColumnSpec("Qty", lambda f: f.quantity, number_format=_QTY_FMT),
        ColumnSpec("Fill Price", lambda f: f.price, number_format=_CURRENCY_FMT),
        ColumnSpec("Commission", lambda f: f.commission, number_format=_CURRENCY_FMT),
        ColumnSpec("Slippage", lambda f: f.slippage, number_format=_CURRENCY_FMT),
        # ``timestamp`` is the only datetime cell -- deterministic (#78 Q-F), never wall-clock (design L6).
        ColumnSpec("Timestamp", lambda f: f.timestamp),
    ],
}

#: FORMAT_SPEC -- one place to declare every CF rule (design Q-B B1 / §3).
FORMAT_SPEC: tuple[CFRule, ...] = (
    CFRule(sheet="Recommendations", column="Action", kind="action_fill"),
    CFRule(sheet="Recommendations", column="Conviction", kind="conviction_shade"),
    CFRule(sheet="Recommendations", column="Score", kind="color_scale_3_centered"),
    CFRule(sheet="Recommendations", column="Stop %", kind="color_scale_3"),
    CFRule(sheet="Recommendations", column="R:R", kind="data_bar"),
)


# ---------------------------------------------------------------------------
# Row sorting (design L6: segment -> conviction -> symbol)
# ---------------------------------------------------------------------------


def _plan_sort_key(plan: TradePlan) -> tuple[str, int, int, str]:
    """Total-order sort key: ``(segment, conviction_rank, action_rank, symbol)`` (design L6).

    ``segment`` is alphabetical (canonical GICS order is preserved by the upstream
    scan, but here we just keep cross-segment determinism explicit). ``conviction``
    sorts High -> Medium -> Low so the strongest setups float to the top inside each
    segment band, and ``action`` is the secondary tie-break (BUY before SELL_SHORT
    before HOLD/FLAT). ``symbol`` is the final tie-breaker for a stable, total order.
    """
    rec = plan.recommendation
    return (
        rec.segment,
        _CONVICTION_RANK.get(rec.conviction, len(_CONVICTION_RANK)),
        _ACTION_RANK.get(rec.action, len(_ACTION_RANK)),
        rec.symbol,
    )


def _sorted_plans(plans: list[TradePlan]) -> list[TradePlan]:
    """Return ``plans`` sorted by the deterministic L6 key."""
    return sorted(plans, key=_plan_sort_key)


# ---------------------------------------------------------------------------
# Sheet builders -- each turns the input list into a DataFrame for to_excel
# ---------------------------------------------------------------------------


def _coerce(value: Any) -> Any:
    """Coerce a model value to an Excel-friendly cell value (Q-E unrounded boundary).

    ``Decimal`` becomes ``float(Decimal)`` (unrounded -- display rounding lives in
    ``number_format``). ``None`` becomes the empty string so blank cells stay blank
    rather than rendering as ``"None"``. **Tz-aware datetimes are converted to UTC
    then stripped of tzinfo** -- openpyxl rejects tz-aware datetimes outright
    (Excel has no timezone concept). The conversion preserves the exact instant;
    only the tz label is dropped, so the deterministic ``Fill.timestamp`` cell
    still round-trips losslessly for any reader that knows the workbook is UTC.
    Other values pass through.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    if value is None:
        return ""
    return value


def _build_df(rows: list[Any], spec: list[ColumnSpec]) -> pd.DataFrame:
    """Build a DataFrame from ``rows`` using ``spec``'s ordered accessors."""
    headers = [col.header for col in spec]
    data = [[_coerce(col.accessor(row)) for col in spec] for row in rows]
    return pd.DataFrame(data, columns=headers)


def _plan_rows_df(plans: list[TradePlan], sheet: str) -> pd.DataFrame:
    """Build one of the plan-row sheets (Recommendations / Levels / Reasoning)."""
    return _build_df(plans, SHEET_SPEC[sheet])


def _orders_df(plans: list[TradePlan]) -> pd.DataFrame:
    """Build the Orders sheet: one row per ``Order``, in plan-then-intent order."""
    rows: list[Order] = []
    for plan in plans:
        rows.extend(plan.orders)
    return _build_df(rows, SHEET_SPEC["Orders"])


def _fills_df(plans: list[TradePlan]) -> pd.DataFrame:
    """Build the Fills sheet: one row per ``Fill``, in plan-then-fill order."""
    rows: list[Fill] = []
    for plan in plans:
        rows.extend(plan.simulated_fills)
    return _build_df(rows, SHEET_SPEC["Fills"])


def _summary_rows(
    plans: list[TradePlan], context: dict[str, Any] | None
) -> list[tuple[str, Any]]:
    """Build the Summary sheet's (key, value) pairs (design Q-C / Q-D).

    Derived from ``plans`` (as-of, segment counts, action counts, avg R:R, validation
    coverage); the four non-derivable fields (calendar, preset, weights, submodule
    pin) come from the optional ``context`` mapping -- ``"n/a"`` when absent (design
    Q-D option (i)).
    """
    as_of = plans[0].as_of if plans else None
    segments_counts = {}
    action_counts = {"BUY": 0, "SELL_SHORT": 0, "HOLD/FLAT": 0}
    rr_actionable: list[float] = []
    validation_count = 0
    for plan in plans:
        rec = plan.recommendation
        segments_counts[rec.segment] = segments_counts.get(rec.segment, 0) + 1
        if rec.action in action_counts:
            action_counts[rec.action] += 1
        if rec.action != "HOLD/FLAT":
            rr_actionable.append(rec.risk_reward)
        if plan.validation is not None:
            validation_count += 1

    ctx = context or {}
    avg_rr = sum(rr_actionable) / len(rr_actionable) if rr_actionable else 0.0

    rows: list[tuple[str, Any]] = [
        ("As-of", as_of.isoformat() if as_of else "n/a"),
        ("Calendar", ctx.get("calendar", "n/a")),
        ("Preset", ctx.get("preset", "n/a")),
        ("Weights", ctx.get("weights", "n/a")),
        ("Submodule pin (pandas-ta-classic)", ctx.get("submodule_pin", "n/a")),
        ("Plans (total)", len(plans)),
        ("BUY", action_counts["BUY"]),
        ("SELL_SHORT", action_counts["SELL_SHORT"]),
        ("HOLD/FLAT", action_counts["HOLD/FLAT"]),
        ("Avg R:R (actionable)", round(avg_rr, 4)),
        ("Validation coverage", validation_count),
    ]
    # Append per-segment counts in alphabetical (deterministic) order.
    for segment in sorted(segments_counts):
        rows.append((f"Segment: {segment}", segments_counts[segment]))
    return rows


def _summary_df(plans: list[TradePlan], context: dict[str, Any] | None) -> pd.DataFrame:
    """Build the Summary sheet's DataFrame (two columns: Key, Value)."""
    rows = _summary_rows(plans, context)
    return pd.DataFrame(
        [[_coerce(value) for value in row] for row in rows], columns=["Key", "Value"]
    )


# ---------------------------------------------------------------------------
# Openpyxl rendering -- title block + disclaimer + formatting + CF (Q-B B1)
# ---------------------------------------------------------------------------

_TITLE_FONT = Font(bold=True, size=12)
_HEADER_FONT = Font(bold=True)
_HEADER_FILL = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
_DISCLAIMER_FONT = Font(italic=True, color="808080")


def _write_title_and_disclaimer(ws, as_of: date | None) -> int:
    """Write the title block + disclaimer onto the Recommendations sheet (design L3 / §2.7).

    Occupies the first two rows; returns the row index where the table header should
    start (row 4 -- one blank row after the disclaimer, then the header on row 4).
    """
    title = (
        f"OpenBB TechTrade - Top-Mover Recommendations - {as_of.isoformat()}"
        if as_of
        else "OpenBB TechTrade"
    )
    ws.cell(row=1, column=1, value=title).font = _TITLE_FONT
    ws.cell(row=2, column=1, value=DISCLAIMER).font = _DISCLAIMER_FONT
    return 4  # header on row 4 (blank row 3)


def _write_dataframe(
    ws, df: pd.DataFrame, start_row: int, spec: list[ColumnSpec] | None
) -> None:
    """Write ``df`` onto ``ws`` starting at ``start_row``, with bold header + number_format.

    The first row written is the header (bold, light-grey fill). Each subsequent row
    is one DataFrame row, with cells formatted according to ``spec`` (when provided)
    -- currency / percent / R:R / score formats from the column's ``number_format``.
    """
    # Header row.
    for col_index, header in enumerate(df.columns, start=1):
        cell = ws.cell(row=start_row, column=col_index, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="left")

    # Data rows.
    format_by_col = {col.header: col.number_format for col in (spec or [])}
    for row_offset, row_values in enumerate(df.itertuples(index=False), start=1):
        for col_index, value in enumerate(row_values, start=1):
            cell = ws.cell(row=start_row + row_offset, column=col_index, value=value)
            number_format = format_by_col.get(df.columns[col_index - 1])
            if number_format is not None:
                cell.number_format = number_format


def _autosize_columns(ws, df: pd.DataFrame, header_row: int) -> None:
    """Set each column width to fit its widest cell (deterministic, content-derived, L6).

    Excel column width units are ~character widths; we cap at 60 to keep extreme
    cells (long ``reasoning`` strings) from blowing out the layout.
    """
    for col_index, header in enumerate(df.columns, start=1):
        max_len = len(str(header))
        for row in df[header]:
            row_len = len(str(row)) if row is not None else 0
            max_len = max(max_len, row_len)
        ws.column_dimensions[get_column_letter(col_index)].width = min(max_len + 2, 60)


def _apply_filter_and_freeze(ws, header_row: int, n_cols: int, n_rows: int) -> None:
    """Apply an autofilter over the data range and freeze the header row (always-on, §3)."""
    if n_rows == 0:
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
        return
    last_col = get_column_letter(n_cols)
    ws.auto_filter.ref = f"A{header_row}:{last_col}{header_row + n_rows}"
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


# ---------------------------------------------------------------------------
# Conditional formatting -- openpyxl applier (Q-B B1)
# ---------------------------------------------------------------------------

#: Action colors (design §3).
_ACTION_FILLS: dict[str, PatternFill] = {
    "BUY": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
    "SELL_SHORT": PatternFill(
        start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"
    ),
    "HOLD/FLAT": PatternFill(
        start_color="D9D9D9", end_color="D9D9D9", fill_type="solid"
    ),
}

#: Conviction shades (design §3 -- High darkest).
_CONVICTION_FILLS: dict[str, PatternFill] = {
    "High": PatternFill(start_color="B7E1CD", end_color="B7E1CD", fill_type="solid"),
    "Medium": PatternFill(start_color="DDEFE2", end_color="DDEFE2", fill_type="solid"),
    "Low": PatternFill(start_color="F0F4F2", end_color="F0F4F2", fill_type="solid"),
}


def _column_letter_for_header(ws, header_row: int, header: str) -> str | None:
    """Resolve a header label to its Excel column letter via the header row.

    Returns ``None`` when the header is not found (lets CF setup skip cleanly for a
    column the user dropped via ``include_sheets`` subsetting, design L2).
    """
    for col_index in range(1, ws.max_column + 1):
        cell = ws.cell(row=header_row, column=col_index)
        if cell.value == header:
            return get_column_letter(col_index)
    return None


def _apply_openpyxl_cf(ws, header_row: int, n_rows: int) -> None:
    """Apply every :data:`FORMAT_SPEC` rule onto ``ws`` via openpyxl (design Q-B B1).

    Each rule's column header is resolved at runtime via the sheet's header row so
    a column reorder in :data:`SHEET_SPEC` automatically relocates the CF range.
    Rules whose column is absent (subsetted out) are skipped silently. A zero-row
    sheet skips all CF (nothing to format).
    """
    if n_rows == 0:
        return
    for rule in FORMAT_SPEC:
        if rule.sheet != ws.title:
            continue
        col_letter = _column_letter_for_header(ws, header_row, rule.column)
        if col_letter is None:
            continue
        cell_range = f"{col_letter}{header_row + 1}:{col_letter}{header_row + n_rows}"
        for openpyxl_rule in _build_openpyxl_rule(rule.kind):
            ws.conditional_formatting.add(cell_range, openpyxl_rule)


def _build_openpyxl_rule(kind: _CFKind) -> list:
    """Translate a CFRule kind into one or more openpyxl rule objects."""
    if kind == "action_fill":
        return [
            CellIsRule(operator="equal", formula=['"BUY"'], fill=_ACTION_FILLS["BUY"]),
            CellIsRule(
                operator="equal",
                formula=['"SELL_SHORT"'],
                fill=_ACTION_FILLS["SELL_SHORT"],
            ),
            CellIsRule(
                operator="equal",
                formula=['"HOLD/FLAT"'],
                fill=_ACTION_FILLS["HOLD/FLAT"],
            ),
        ]
    if kind == "conviction_shade":
        return [
            CellIsRule(
                operator="equal", formula=['"High"'], fill=_CONVICTION_FILLS["High"]
            ),
            CellIsRule(
                operator="equal", formula=['"Medium"'], fill=_CONVICTION_FILLS["Medium"]
            ),
            CellIsRule(
                operator="equal", formula=['"Low"'], fill=_CONVICTION_FILLS["Low"]
            ),
        ]
    if kind == "data_bar":
        return [DataBarRule(start_type="min", end_type="max", color="63BE7B")]
    if kind == "color_scale_3":
        return [
            ColorScaleRule(
                start_type="min",
                start_color="63BE7B",
                mid_type="percentile",
                mid_value=50,
                mid_color="FFEB84",
                end_type="max",
                end_color="F8696B",
            )
        ]
    if kind == "color_scale_3_centered":
        return [
            ColorScaleRule(
                start_type="min",
                start_color="F8696B",
                mid_type="num",
                mid_value=0,
                mid_color="FFEB84",
                end_type="max",
                end_color="63BE7B",
            )
        ]
    return []  # pragma: no cover -- kind is constrained by _CFKind Literal


# ---------------------------------------------------------------------------
# xlsxwriter applier -- best-effort richer (Q-B B1 second engine)
# ---------------------------------------------------------------------------


def _apply_xlsxwriter_cf(
    workbook, worksheet, rule: CFRule, df: pd.DataFrame, header_row: int
) -> None:
    """Apply one :data:`FORMAT_SPEC` rule via xlsxwriter (best-effort, no parity guarantee).

    Imported lazily by :func:`_write_workbook_xlsxwriter` -- only callers using
    ``engine="xlsxwriter"`` pay the dependency cost. Rules whose column is absent
    are skipped silently.
    """
    n_rows = len(df)
    if n_rows == 0 or rule.column not in df.columns:
        return
    col_index = list(df.columns).index(rule.column)
    cell_range = (header_row, col_index, header_row + n_rows - 1, col_index)

    if rule.kind == "action_fill":
        for value, color in (
            ("BUY", "#C6EFCE"),
            ("SELL_SHORT", "#FFC7CE"),
            ("HOLD/FLAT", "#D9D9D9"),
        ):
            worksheet.conditional_format(
                *cell_range,
                {
                    "type": "cell",
                    "criteria": "equal to",
                    "value": f'"{value}"',
                    "format": workbook.add_format({"bg_color": color}),
                },
            )
    elif rule.kind == "conviction_shade":
        for value, color in (
            ("High", "#B7E1CD"),
            ("Medium", "#DDEFE2"),
            ("Low", "#F0F4F2"),
        ):
            worksheet.conditional_format(
                *cell_range,
                {
                    "type": "cell",
                    "criteria": "equal to",
                    "value": f'"{value}"',
                    "format": workbook.add_format({"bg_color": color}),
                },
            )
    elif rule.kind == "data_bar":
        worksheet.conditional_format(*cell_range, {"type": "data_bar"})
    elif rule.kind == "color_scale_3":
        worksheet.conditional_format(*cell_range, {"type": "3_color_scale"})
    elif rule.kind == "color_scale_3_centered":
        worksheet.conditional_format(
            *cell_range,
            {
                "type": "3_color_scale",
                "min_color": "#F8696B",
                "mid_color": "#FFEB84",
                "max_color": "#63BE7B",
                "mid_type": "num",
                "mid_value": 0,
            },
        )


# ---------------------------------------------------------------------------
# Workbook writers -- one per engine
# ---------------------------------------------------------------------------


def _resolved_sheets(config: ExportConfig) -> list[str]:
    """Return the sheets to render, in canonical order, subset by config (design L2)."""
    requested = (
        set(config.include_sheets) if config.include_sheets else set(CANONICAL_SHEETS)
    )
    return [sheet for sheet in CANONICAL_SHEETS if sheet in requested]


def _build_dataframes(
    plans: list[TradePlan], context: dict[str, Any] | None, sheets: list[str]
) -> dict[str, pd.DataFrame]:
    """Build one DataFrame per requested sheet (skipping anything not in ``sheets``)."""
    dataframes: dict[str, pd.DataFrame] = {}
    for sheet in sheets:
        if sheet in ("Recommendations", "Levels", "Reasoning"):
            dataframes[sheet] = _plan_rows_df(plans, sheet)
        elif sheet == "Orders":
            dataframes[sheet] = _orders_df(plans)
        elif sheet == "Fills":
            dataframes[sheet] = _fills_df(plans)
        elif sheet == "Summary":
            dataframes[sheet] = _summary_df(plans, context)
    return dataframes


def _write_workbook_openpyxl(
    path: Path,
    sheets: list[str],
    dataframes: dict[str, pd.DataFrame],
    config: ExportConfig,
    as_of: date | None,
) -> None:
    """Write the workbook via openpyxl -- the default + core engine (design L1)."""
    workbook = Workbook()
    # The new workbook ships with one default "Sheet" -- replace it with our first sheet.
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    for sheet_name in sheets:
        df = dataframes[sheet_name]
        ws = workbook.create_sheet(title=sheet_name)
        header_row = 1
        if sheet_name == "Recommendations":
            header_row = _write_title_and_disclaimer(ws, as_of)
        spec = SHEET_SPEC.get(sheet_name)
        _write_dataframe(ws, df, header_row, spec)
        _autosize_columns(ws, df, header_row)
        _apply_filter_and_freeze(ws, header_row, len(df.columns), len(df))
        if config.conditional_formatting:
            _apply_openpyxl_cf(ws, header_row, len(df))

    workbook.save(path)


def _write_workbook_xlsxwriter(
    path: Path,
    sheets: list[str],
    dataframes: dict[str, pd.DataFrame],
    config: ExportConfig,
    as_of: date | None,
) -> None:
    """Write the workbook via xlsxwriter -- lazy-imported, best-effort richer (Q-B B1)."""
    # Lazy import -- the dep is optional; only this path pays the cost.
    import xlsxwriter  # noqa: F401 -- engine resolved by pandas via ExcelWriter

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "bg_color": "#DDDDDD"})

        for sheet_name in sheets:
            df = dataframes[sheet_name]
            # Title + disclaimer take rows 0-1; the table starts at row 3 (header) / 4+ (data).
            header_row = 3 if sheet_name == "Recommendations" else 0
            df.to_excel(
                writer,
                sheet_name=sheet_name,
                startrow=header_row,
                index=False,
                header=False,
            )
            worksheet = writer.sheets[sheet_name]

            if sheet_name == "Recommendations":
                title = (
                    f"OpenBB TechTrade - Top-Mover Recommendations - {as_of.isoformat()}"
                    if as_of
                    else "OpenBB TechTrade"
                )
                worksheet.write(
                    0, 0, title, workbook.add_format({"bold": True, "font_size": 12})
                )
                worksheet.write(
                    1,
                    0,
                    DISCLAIMER,
                    workbook.add_format({"italic": True, "color": "#808080"}),
                )

            # Header row with bold fill.
            for col_index, header in enumerate(df.columns):
                worksheet.write(header_row, col_index, header, header_format)

            # Per-column number formats.
            spec = SHEET_SPEC.get(sheet_name) or []
            for col_index, col in enumerate(spec):
                if col.number_format is None or col.header not in df.columns:
                    continue
                fmt = workbook.add_format({"num_format": col.number_format})
                worksheet.set_column(col_index, col_index, None, fmt)

            # Freeze header + autofilter.
            worksheet.freeze_panes(header_row + 1, 0)
            if len(df) > 0:
                worksheet.autofilter(
                    header_row, 0, header_row + len(df), len(df.columns) - 1
                )

            # Conditional formatting (best-effort).
            if config.conditional_formatting:
                for rule in FORMAT_SPEC:
                    if rule.sheet == sheet_name:
                        _apply_xlsxwriter_cf(
                            workbook, worksheet, rule, df, header_row + 1
                        )


# ---------------------------------------------------------------------------
# Path resolution (design Q-F: resolved base dir, never CWD)
# ---------------------------------------------------------------------------

#: Env var that overrides the default export base dir (Q-F: configurable, repo-relative default).
EXPORT_BASE_ENV: str = "TECHTRADE_EXPORT_DIR"

#: Env var that opts in to accepting an absolute ``ExportConfig.path``. Default
#: behavior sandboxes ``cfg.path`` inside the base dir via ``safe_join``, so a
#: web-facing caller who supplies ``path='../../etc/passwd.xlsx'`` gets a
#: ``PathTraversalError`` (bd-cwer / bd-qawo). A trusted CLI/notebook caller
#: who genuinely wants an absolute path (common in unit tests + local runs)
#: sets ``TECHTRADE_EXPORT_ALLOW_ABSOLUTE=1``.
EXPORT_ALLOW_ABSOLUTE_ENV: str = "TECHTRADE_EXPORT_ALLOW_ABSOLUTE"

#: Repo-relative default base dir (matches PRD §14.3 / L4).
_DEFAULT_BASE_REL = Path("Analysis") / "exports"


def _repo_root() -> Path:
    """Resolve the repository root from this module's location (5 parents up)."""
    return Path(__file__).resolve().parents[5]


def _export_base_dir() -> Path:
    """Return the configured export base directory (env-override or default)."""
    base_override = os.environ.get(EXPORT_BASE_ENV)
    return Path(base_override) if base_override else (_repo_root() / _DEFAULT_BASE_REL)


def _resolve_export_path(cfg_path: str | None, as_of: date | None) -> Path:
    """Resolve ``ExportConfig.path`` to a safe absolute path.

    * ``cfg_path is None`` → default ``<base>/techtrade_<as_of>.xlsx`` (design L4)
    * ``cfg_path`` relative → sandboxed inside base dir via ``safe_join``
    * ``cfg_path`` absolute → allowed iff ``TECHTRADE_EXPORT_ALLOW_ABSOLUTE=1``,
      else raises ``PathTraversalError``

    Regression defense for OpenBBTechnical-qawo (bd-cwer): the REST-facing
    ``export_router.export()`` used to forward ``cfg.path`` unmodified into
    ``Path(cfg.path)`` → ``workbook.save(path)``, letting a web caller write
    anywhere on the filesystem the process could reach.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_core.app.paths import PathTraversalError, safe_join

    base = _export_base_dir()
    base.mkdir(parents=True, exist_ok=True)

    if cfg_path is None:
        date_token = (as_of or date.today()).isoformat()
        return safe_join(base, f"techtrade_{date_token}.xlsx")

    candidate = Path(cfg_path)
    if candidate.is_absolute() or candidate.drive:
        allow = os.environ.get(EXPORT_ALLOW_ABSOLUTE_ENV, "").strip().lower()
        if allow in ("1", "true", "yes", "on"):
            return candidate.resolve()
        raise PathTraversalError(
            f"ExportConfig.path is absolute: {cfg_path!r}. Set env "
            f"{EXPORT_ALLOW_ABSOLUTE_ENV}=1 to permit absolute paths, or pass "
            f"a path relative to the export base dir "
            f"(default: <repo>/Analysis/exports, override via {EXPORT_BASE_ENV})."
        )

    return safe_join(base, cfg_path)


def _default_path(as_of: date | None) -> Path:
    """Build the default export path: ``<base>/techtrade_<as_of>.xlsx`` (design L4).

    Kept for backward compatibility with existing callers; new code should
    use :func:`_resolve_export_path` which centralises the safe-path logic.
    """
    base = _export_base_dir()
    date_token = (as_of or date.today()).isoformat()
    return base / f"techtrade_{date_token}.xlsx"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export(
    plans: list[TradePlan],
    *,
    config: ExportConfig | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Write the 6-sheet recommendation workbook and return the file path (PRD §14.3).

    The pure, deterministic core behind ``obb.techtrade.export``. Renders the
    requested sheets (canonical order, may be subset via ``config.include_sheets``)
    onto the engine declared by ``config.engine`` (``openpyxl`` default, design L1),
    with conditional formatting on by default (design L5), the compliance disclaimer
    on the Recommendations sheet (design L3), and rows sorted segment -> conviction ->
    action -> symbol (design L6).

    Parameters
    ----------
    plans : list[TradePlan]
        Paper-filled trade plans (one per signal). Each plan carries the
        ``recommendation``, ``signal.votes``, ``orders``, and ``simulated_fills``
        that feed the six sheets. An empty list yields a header-only workbook.
    config : ExportConfig | None, optional
        Workbook configuration: ``path`` (output path), ``engine`` (``openpyxl`` /
        ``xlsxwriter``), ``include_sheets`` (subset, never reorder), and
        ``conditional_formatting`` (on by default). Defaults to ``ExportConfig()``.
    context : dict[str, Any] | None, optional
        Optional run-context for the Summary sheet's non-derivable cells
        (``calendar``, ``preset``, ``weights``, ``submodule_pin``). Produced by
        ``scan`` (#79). Missing fields render as ``"n/a"`` (design Q-D option (i)).

    Returns
    -------
    str
        The absolute path of the written workbook (design Q-F).
    """
    cfg = config or ExportConfig()
    sheets = _resolved_sheets(cfg)
    sorted_plans = _sorted_plans(plans)
    dataframes = _build_dataframes(sorted_plans, context, sheets)

    as_of = sorted_plans[0].as_of if sorted_plans else None
    # cfg.path is sandboxed via _resolve_export_path — absolute paths require
    # explicit env opt-in (see EXPORT_ALLOW_ABSOLUTE_ENV) to defend the
    # REST-facing export_router.export() from path-traversal (bd-cwer / bd-qawo).
    path = _resolve_export_path(cfg.path, as_of)
    path.parent.mkdir(parents=True, exist_ok=True)

    if cfg.engine == "xlsxwriter":
        _write_workbook_xlsxwriter(path, sheets, dataframes, cfg, as_of)
    else:
        _write_workbook_openpyxl(path, sheets, dataframes, cfg, as_of)

    return str(path.resolve())
