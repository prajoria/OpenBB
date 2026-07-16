"""Excel workbook builder (P5.2).

Reuse posture (NG3): call ``openbb_techtrade.reporting.excel_export.export()``
for the 6-sheet base workbook (Recommendations, Levels, Reasoning, Orders,
Fills, Summary — techtrade's contract). Then open the file with openpyxl
and append 3 intraday-specific sheets (Fills, Vetoes, PerSymbolPnL —
where "Fills" is the fmp_trading name; techtrade already has a Fills
sheet in the base workbook, so ours is named ``IntradayFills`` to
avoid collision).

DO NOT reimplement techtrade internals. If the export signature changes,
we adapt the _call_techtrade_export adapter here; if SHEET_SPEC changes,
we accept whatever techtrade produces and lay our sheets on top.

Money precision (review finding #3, P2): PerSymbolPnL accumulates in
``Decimal``, not float. Excel cell value is the ``Decimal`` string
representation so 0.1 + 0.2 renders as "0.30", not "0.30000000000000004".

Contract adaptation note: techtrade's ``export()`` takes ``plans:
list[TradePlan]`` from the SIGNAL pipeline (not from journal FillEvents).
In P5.2 shipping we hand it an empty ``plans=[]`` — that produces a
header-only base workbook per techtrade's own docstring. The intraday
data lives in our appended sheets. Follow-up: when a journal-to-
TradePlan adapter exists, populate ``plans`` from FillEvents so the
Recommendations/Orders/Fills sheets show real data too.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class XLSXUnavailable(Exception):
    """openbb-techtrade not importable — install it (already a required
    dep but transitive imports can be broken)."""


def build_workbook(
    session_id: str,
    events: list[Any],
    metrics,
    output_path: Path,
    engine: str = "openpyxl",
) -> Path:
    """Build the 6+3 sheet end-of-day workbook. See design-spec §4.3."""
    try:
        from openbb_techtrade.reporting import excel_export  # noqa: F401
    except ImportError as exc:
        raise XLSXUnavailable(
            "openbb-techtrade required for XLSX report; install it"
        ) from exc

    from openpyxl import load_workbook

    output_path = Path(output_path)
    # Step 1: techtrade produces the base 6-sheet workbook.
    _call_techtrade_export(session_id, events, metrics, output_path, engine=engine)

    # Step 2: open + append 3 intraday sheets.
    #
    # `load_workbook(path)` validates the file extension (openpyxl rejects
    # anything that isn't .xlsx / .xlsm / .xltx / .xltm). When the caller
    # is `report.py`, it writes to a `<name>.xlsx.<rand>.tmp` file first
    # then does an atomic rename — so the path we receive here has a `.tmp`
    # extension and load_workbook refuses it. Load via BytesIO to bypass
    # the extension check (the file content is still a valid xlsx zip).
    with open(output_path, "rb") as f:
        _wb_bytes = f.read()
    from io import BytesIO
    wb = load_workbook(BytesIO(_wb_bytes))
    _append_intraday_fills_sheet(wb, events)
    _append_vetoes_sheet(wb, events)
    _append_per_symbol_pnl_sheet(wb, events)
    wb.save(output_path)
    return output_path


def _call_techtrade_export(
    session_id: str,
    events: list[Any],
    metrics,
    output_path: Path,
    engine: str,
) -> None:
    """Adapter: invoke openbb_techtrade.reporting.excel_export.export().

    Signature verified against the shipped code at
    openbb_platform/extensions/techtrade/openbb_techtrade/reporting/
    excel_export.py:29.

      export(
        plans: list[TradePlan],
        *,
        config: ExportConfig | None = None,
        context: dict[str, Any] | None = None,
      ) -> str  # returns path

    ``TradePlan`` comes from the signal pipeline; a journal-driven report
    doesn't have TradePlan objects readily available (they'd need to be
    reconstructed from OrderEvent + FillEvent payloads). For P5.2
    shipping we pass ``plans=[]`` which produces a header-only base
    workbook — the intraday data lives in our appended sheets.

    A future follow-up bead can build a journal-to-TradePlan reconstructor
    and populate the base sheets too. Filed as `P5-followup-2`.
    """
    from openbb_techtrade.models import ExportConfig
    from openbb_techtrade.reporting import excel_export

    try:
        cfg = ExportConfig(path=str(output_path), engine=engine)
        excel_export.export(
            plans=[],
            config=cfg,
            context={
                "session_id": session_id,
                "session_events_count": len(events),
            },
        )
    except TypeError as exc:
        # techtrade's signature diverged from what we adapted for.
        # Do NOT ship a placeholder workbook (review finding #1) — fail loud.
        raise XLSXUnavailable(
            f"openbb-techtrade excel_export.export() signature has diverged "
            f"from P5.2's adapter (got: {exc}). Update _call_techtrade_export "
            f"to match; do NOT ship a placeholder workbook."
        ) from exc


def _append_intraday_fills_sheet(wb, events):
    """Fills sheet from journal FillEvent payloads.

    Named ``IntradayFills`` to avoid colliding with techtrade's own
    ``Fills`` sheet in the base workbook. The base sheet holds
    signal-pipeline fills; this one holds journal-recorded intraday
    execution fills.
    """
    ws = wb.create_sheet("IntradayFills")
    ws.append(["ts", "symbol", "side", "qty", "fill_price", "commission", "slippage"])
    for e in events:
        if getattr(e, "event_type", None) == "fill":
            p = getattr(e, "payload", {}) or {}
            ws.append([
                str(getattr(e, "ts", "")),
                p.get("symbol", ""),
                p.get("side", ""),
                p.get("qty", ""),
                p.get("fill_price", ""),
                p.get("commission", ""),
                p.get("slippage", ""),
            ])


def _append_vetoes_sheet(wb, events):
    """Vetoes sheet from journal VetoEvent payloads."""
    ws = wb.create_sheet("Vetoes")
    ws.append(["ts", "symbol", "reason_code", "gate", "plan"])
    for e in events:
        if getattr(e, "event_type", None) == "veto":
            p = getattr(e, "payload", {}) or {}
            ws.append([
                str(getattr(e, "ts", "")),
                p.get("symbol", ""),
                p.get("reason_code", ""),
                p.get("gate", ""),
                str(p.get("plan", "")),
            ])


def _append_per_symbol_pnl_sheet(wb, events):
    """PerSymbolPnL — accumulate in Decimal, not float (review finding #3).

    The operator reads THIS sheet to judge which names worked today.
    Float accumulation across a day of fills silently drifts. Decimal
    preserves precision end-to-end (P2 constraint)."""
    ws = wb.create_sheet("PerSymbolPnL")
    ws.append(["symbol", "realized_pnl", "fill_count"])
    per_symbol: dict[str, dict] = defaultdict(
        lambda: {"pnl": Decimal("0"), "fills": 0}
    )
    for e in events:
        if getattr(e, "event_type", None) == "fill":
            p = getattr(e, "payload", {}) or {}
            sym = p.get("symbol", "")
            per_symbol[sym]["fills"] += 1
            rp = p.get("realized_pnl")
            if rp is not None:
                try:
                    per_symbol[sym]["pnl"] += Decimal(str(rp))
                except (TypeError, ValueError):
                    pass
    for sym, data in sorted(per_symbol.items()):
        # Write the Decimal as its string repr — openpyxl stores it as
        # a string cell, giving exact display without float coercion.
        ws.append([sym, str(data["pnl"]), data["fills"]])


__all__ = ["XLSXUnavailable", "build_workbook"]
