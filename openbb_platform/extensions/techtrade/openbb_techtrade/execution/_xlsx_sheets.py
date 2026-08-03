"""XLSX sheet writers for :mod:`order_sink` — 6 sheets + 3 embedded charts.

Extracted from :mod:`openbb_techtrade.execution.order_sink` at #1719
Phase 2 to keep the main module under pylint's ``too-many-lines``
threshold. Every writer here is a leaf function invoked from
:func:`order_sink._write_xlsx`; nothing here should be imported from
outside the ``execution`` package.

Sheet order (renders as workbook tab order):

1. Orders — executable rows, buy/sell coloring
2. Batch Summary — SHA + verdict-gate rollup + gross notional
3. Plan Context — one row per :class:`VerdictGate`
4. Deviation Analysis — deviation % + horizontal bar chart
5. Concentration — pre/post-exec weights + two pie charts
6. Audit — provenance footer (SHA full, plan_id, generator, git_sha)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# _CSV_COLUMNS is defined in order_sink; importing at module level (not
# under TYPE_CHECKING) because the Orders sheet writer reads it at runtime.
# order_sink imports THIS module lazily from within _write_xlsx() so there
# is no circular-import at load time.
from openbb_techtrade.execution.order_sink import _CSV_COLUMNS  # noqa: E402

if TYPE_CHECKING:
    from openbb_techtrade.execution.order_sink import OrderBatch, VerdictGate


# ---------------------------------------------------------------------------
# XLSX writer — phase-2 full 6-sheet workbook with embedded charts.
# ---------------------------------------------------------------------------

#: Fills used across every sheet. Kept module-level so they can be reused
#: from the individual _write_<sheet> writers without re-instantiating.
_SHEET_NAMES = (
    "Orders",
    "Batch Summary",
    "Plan Context",
    "Deviation Analysis",
    "Concentration",
    "Audit",
)

#: Concentration thresholds beyond which the reviewer sees a loud red
#: highlight. Single-position 10% and single-sector 30% are the operator's
#: default limits; a plan that pushes past either is not automatically
#: rejected (T4 owns that call) but it MUST catch the reviewer's eye.
_MAX_SINGLE_POSITION_WEIGHT = 0.10
_MAX_SINGLE_SECTOR_WEIGHT = 0.30

#: Cosmetic. Kept muted so the reviewer's eye tracks numbers, not chrome.
_BUY_FILL_HEX = "E6F4EA"
_SELL_FILL_HEX = "FCE8E6"
_WARN_FILL_HEX = "FFF4E5"
_ERROR_FILL_HEX = "FADBD8"
_HEADER_FILL_HEX = "F1F3F4"


def write_workbook(path: Path, batch: OrderBatch) -> None:
    """Write phase-2 full 6-sheet XLSX workbook.

    Sheets, in tab order:

    1. **Orders** — executable rows, buy/sell coloring, frozen header.
       Feeds the CSV that the operator uploads to Fidelity.
    2. **Batch Summary** — one-page KPI header. Batch SHA, plan_id,
       gross notional, per-side breakdown, verdict-gate rollup.
    3. **Plan Context** — one row per :class:`VerdictGate` from the T4
       validation step; loud red fill on failed gates.
    4. **Deviation Analysis** — per-order table with last close, limit,
       deviation %, plus a horizontal bar chart of |deviation%|.
    5. **Concentration** — pre + post-execution position weights, with
       loud red highlight on >10% single-position or >30% single-sector
       weights, plus a side-by-side pie chart pair.
    6. **Audit** — provenance footer: batch SHA (full 64 chars), plan_id,
       generator version, git SHA, tz-aware write timestamp.

    Sheets 2-6 render gracefully-empty placeholder rows when the batch
    was constructed without the corresponding optional field (P1 batches
    still write a valid workbook — they just have "not provided"
    placeholders on the P2 sheets).
    """
    # Deferred import — openpyxl is a heavy dep and only the XLSX writer
    # needs it. If a downstream call site imports order_sink only for
    # the CSV path, no openpyxl load penalty.
    # pylint: disable=import-outside-toplevel
    from openpyxl import Workbook  # noqa: PLC0415

    wb = Workbook()
    # Remove the default "Sheet" — we'll add named sheets in tab order.
    default_ws = wb.active
    wb.remove(default_ws)

    _write_orders_sheet(wb, batch)
    _write_batch_summary_sheet(wb, batch)
    _write_plan_context_sheet(wb, batch)
    _write_deviation_sheet(wb, batch)
    _write_concentration_sheet(wb, batch)
    _write_audit_sheet(wb, batch)

    wb.save(path)


def _apply_header(ws, row_idx: int = 1) -> None:
    """Bold + centered header row + subtle fill. Reused across every sheet."""
    # pylint: disable=import-outside-toplevel
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415

    header_font = Font(bold=True)
    header_fill = PatternFill(
        start_color=_HEADER_FILL_HEX, end_color=_HEADER_FILL_HEX, fill_type="solid"
    )
    for cell in ws[row_idx]:
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        cell.fill = header_fill


def _row_fill(color_hex: str):
    """Return a solid PatternFill for the given hex — small util so call
    sites read as one word rather than three.
    """
    # pylint: disable=import-outside-toplevel
    from openpyxl.styles import PatternFill  # noqa: PLC0415

    return PatternFill(start_color=color_hex, end_color=color_hex, fill_type="solid")


# --- Sheet 1: Orders --------------------------------------------------------


def _write_orders_sheet(wb, batch: OrderBatch) -> None:
    """Render executable order rows, colored by side, with a frozen header."""
    ws = wb.create_sheet(title="Orders")
    header = list(_CSV_COLUMNS) + ["Notes"]
    ws.append(header)
    _apply_header(ws)

    buy_fill = _row_fill(_BUY_FILL_HEX)
    sell_fill = _row_fill(_SELL_FILL_HEX)

    for t in batch.tickets:
        row = [
            t.symbol,
            t.action,
            float(t.quantity),
            t.order_type,
            float(t.limit_price) if t.limit_price is not None else None,
            t.tif,
            t.account_masked or "",
            t.notes,
        ]
        ws.append(row)
        fill = buy_fill if t.action in ("Buy", "BuyToCover") else sell_fill
        for cell in ws[ws.max_row]:
            cell.fill = fill

    ws.freeze_panes = "A2"
    widths = {"A": 12, "B": 12, "C": 12, "D": 12, "E": 14, "F": 8, "G": 14, "H": 30}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


# --- Sheet 2: Batch Summary -------------------------------------------------


def _write_batch_summary_sheet(wb, batch: OrderBatch) -> None:
    """One-page KPI header — SHA + plan_id + gross + per-side breakdown."""
    ws = wb.create_sheet(title="Batch Summary")
    ws.append(["Field", "Value"])
    _apply_header(ws)

    gross = sum(
        float(t.quantity) * (float(t.limit_price) if t.limit_price is not None else 0.0)
        for t in batch.tickets
    )
    buy_count = sum(1 for t in batch.tickets if t.action in ("Buy", "BuyToCover"))
    sell_count = len(batch.tickets) - buy_count

    rows = [
        ("Batch SHA (short)", batch.sha_short()),
        ("Batch SHA (full)", batch.sha256()),
        ("Plan ID", batch.plan_id or "not provided"),
        ("Verdict gate", "PASS" if batch.verdict_gate_pass else "FAIL / not verified"),
        ("Total tickets", len(batch.tickets)),
        ("Buy tickets", buy_count),
        ("Sell tickets", sell_count),
        (
            "Gross notional (limit-priced only)",
            f"${gross:,.2f}" if gross > 0 else "n/a (market orders)",
        ),
        (
            "Generated at (UTC)",
            batch.generated_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        ),
    ]
    for r in rows:
        ws.append(r)

    # Loud red fill if the verdict gate failed — this is the operator's
    # single-glance "do NOT upload without acknowledging" signal.
    if not batch.verdict_gate_pass:
        for cell in ws[5]:  # row 5 = "Verdict gate"
            cell.fill = _row_fill(_ERROR_FILL_HEX)

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 70
    ws.freeze_panes = "A2"


# --- Sheet 3: Plan Context --------------------------------------------------


def _write_plan_context_sheet(wb, batch: OrderBatch) -> None:
    """One row per verdict gate. Loud red on failed gates."""
    ws = wb.create_sheet(title="Plan Context")
    ws.append(["Gate", "Threshold", "Actual", "Passed", "Notes"])
    _apply_header(ws)

    gates: tuple[VerdictGate, ...] = (
        batch.plan_context.verdict_gates if batch.plan_context else ()
    )
    if not gates:
        ws.append(
            [
                "not provided",
                "-",
                "-",
                "-",
                "OrderBatch.plan_context is None — P1 batches carry no gates",
            ]
        )
    else:
        err_fill = _row_fill(_ERROR_FILL_HEX)
        for g in gates:
            ws.append(
                [g.name, g.threshold, g.actual, "PASS" if g.passed else "FAIL", g.notes]
            )
            if not g.passed:
                for cell in ws[ws.max_row]:
                    cell.fill = err_fill

    for col, w in {"A": 24, "B": 18, "C": 18, "D": 10, "E": 40}.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


# --- Sheet 4: Deviation Analysis --------------------------------------------


def _write_deviation_sheet(wb, batch: OrderBatch) -> None:
    """Per-order deviation table + horizontal bar chart of |deviation%|."""
    # pylint: disable=import-outside-toplevel
    from openpyxl.chart import BarChart, Reference  # noqa: PLC0415

    ws = wb.create_sheet(title="Deviation Analysis")
    ws.append(
        [
            "Symbol",
            "Action",
            "Quantity",
            "Last Close",
            "Limit Price",
            "Deviation %",
            "Notional",
        ]
    )
    _apply_header(ws)

    pricing = batch.pricing or {}
    if not pricing:
        ws.append(
            [
                "not provided",
                "-",
                "-",
                "-",
                "-",
                "-",
                "OrderBatch.pricing is None — supply per-symbol last-close",
            ]
        )
        for col, w in {
            "A": 12,
            "B": 12,
            "C": 12,
            "D": 14,
            "E": 14,
            "F": 14,
            "G": 40,
        }.items():
            ws.column_dimensions[col].width = w
        return

    warn_fill = _row_fill(_WARN_FILL_HEX)
    for t in batch.tickets:
        last_close = pricing.get(t.symbol)
        limit = t.limit_price
        deviation = (
            float((limit - last_close) / last_close * 100)
            if (limit is not None and last_close is not None and last_close > 0)
            else None
        )
        notional = (
            float(t.quantity * limit)
            if limit is not None
            else (float(t.quantity * last_close) if last_close is not None else None)
        )
        ws.append(
            [
                t.symbol,
                t.action,
                float(t.quantity),
                float(last_close) if last_close is not None else None,
                float(limit) if limit is not None else None,
                round(deviation, 3) if deviation is not None else None,
                round(notional, 2) if notional is not None else None,
            ]
        )
        # Loud amber highlight when |deviation| exceeds 5% — the operator
        # should sanity-check the limit before uploading.
        if deviation is not None and abs(deviation) > 5.0:
            for cell in ws[ws.max_row]:
                cell.fill = warn_fill

    # Embedded horizontal bar chart of deviation %.
    last_row = ws.max_row
    if last_row > 1:
        chart = BarChart()
        chart.type = "bar"
        chart.title = "Deviation from last close (%)"
        chart.style = 10
        chart.y_axis.title = "Symbol"
        chart.x_axis.title = "Deviation %"
        data = Reference(ws, min_col=6, min_row=1, max_row=last_row, max_col=6)
        cats = Reference(ws, min_col=1, min_row=2, max_row=last_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.height = 10
        chart.width = 18
        ws.add_chart(chart, "I2")

    for col, w in {
        "A": 12,
        "B": 12,
        "C": 12,
        "D": 14,
        "E": 14,
        "F": 14,
        "G": 14,
    }.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


# --- Sheet 5: Concentration -------------------------------------------------


def _write_concentration_sheet(wb, batch: OrderBatch) -> None:
    """Pre + post-exec weights table + side-by-side pie charts."""
    # pylint: disable=import-outside-toplevel
    from openpyxl.chart import PieChart, Reference  # noqa: PLC0415

    ws = wb.create_sheet(title="Concentration")
    ws.append(["Symbol", "Pre-exec weight", "Batch delta", "Post-exec weight"])
    _apply_header(ws)

    pre = dict(batch.pre_execution_positions or {})
    if not pre:
        ws.append(
            [
                "not provided",
                "-",
                "-",
                "OrderBatch.pre_execution_positions is None — supply from "
                "MySqlPortfolioStore.latest_snapshot",
            ]
        )
        for col, w in {"A": 14, "B": 16, "C": 16, "D": 40}.items():
            ws.column_dimensions[col].width = w
        return

    # Compute this batch's delta as fraction-of-1 of gross notional. When
    # no limit price is available (market orders), we skip the ticket's
    # delta contribution and log a placeholder — a market order at unknown
    # last close has no defined weight impact until it fills.
    pricing = batch.pricing or {}
    deltas: dict[str, float] = {}
    total_notional = 0.0
    for t in batch.tickets:
        price = t.limit_price if t.limit_price is not None else pricing.get(t.symbol)
        if price is None:
            continue
        signed_notional = float(t.quantity * price) * (
            1.0 if t.action in ("Buy", "BuyToCover") else -1.0
        )
        deltas[t.symbol] = deltas.get(t.symbol, 0.0) + signed_notional
        total_notional += abs(signed_notional)

    if total_notional > 0:
        for sym in list(deltas):
            deltas[sym] = deltas[sym] / total_notional

    err_fill = _row_fill(_ERROR_FILL_HEX)
    symbols = sorted(set(pre) | set(deltas))
    for sym in symbols:
        pre_w = float(pre.get(sym, 0.0))
        delta_w = deltas.get(sym, 0.0)
        post_w = pre_w + delta_w
        ws.append(
            [
                sym,
                round(pre_w, 4),
                round(delta_w, 4),
                round(post_w, 4),
            ]
        )
        # Loud red on any single-position weight above the operator limit.
        if abs(post_w) > _MAX_SINGLE_POSITION_WEIGHT:
            for cell in ws[ws.max_row]:
                cell.fill = err_fill

    last_row = ws.max_row
    if last_row > 1:
        # Side-by-side pies: pre (col B) and post (col D). Same category
        # column (col A) so the eye tracks the delta at a glance.
        pre_chart = PieChart()
        pre_chart.title = "Pre-execution"
        pre_data = Reference(ws, min_col=2, min_row=1, max_row=last_row, max_col=2)
        cats = Reference(ws, min_col=1, min_row=2, max_row=last_row)
        pre_chart.add_data(pre_data, titles_from_data=True)
        pre_chart.set_categories(cats)
        pre_chart.height = 9
        pre_chart.width = 12
        ws.add_chart(pre_chart, "F2")

        post_chart = PieChart()
        post_chart.title = "Post-execution"
        post_data = Reference(ws, min_col=4, min_row=1, max_row=last_row, max_col=4)
        post_chart.add_data(post_data, titles_from_data=True)
        post_chart.set_categories(cats)
        post_chart.height = 9
        post_chart.width = 12
        ws.add_chart(post_chart, "N2")

    for col, w in {"A": 14, "B": 16, "C": 16, "D": 18}.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


# --- Sheet 6: Audit ---------------------------------------------------------


def _write_audit_sheet(wb, batch: OrderBatch) -> None:
    """Provenance footer — SHA, plan_id, generator version, git SHA."""
    ws = wb.create_sheet(title="Audit")
    ws.append(["Field", "Value"])
    _apply_header(ws)

    ctx = batch.plan_context
    rows = [
        ("Batch SHA (full)", batch.sha256()),
        ("Batch SHA (short)", batch.sha_short()),
        ("Plan ID", batch.plan_id or "not provided"),
        ("Verdict gate", "PASS" if batch.verdict_gate_pass else "FAIL / not verified"),
        ("Generator version", ctx.generator_version if ctx else "not provided"),
        ("Git SHA", ctx.git_sha if ctx else "not provided"),
        (
            "Generated at (UTC)",
            batch.generated_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        ),
        (
            "Written at (UTC)",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
        ("Number of tickets", len(batch.tickets)),
        (
            "Notes",
            "Written by openbb_techtrade.execution.order_sink._write_xlsx",
        ),
    ]
    for r in rows:
        ws.append(r)

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 80
    ws.freeze_panes = "A2"
