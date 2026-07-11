"""Unit tests for the #81 Excel export (PRD §14.3, design §5.1).

Fully offline + deterministic: hand-built TradePlan fixtures, no network. Asserts
each acceptance point of the design doc -- sheet set + order (L2), row sort (L6),
title + disclaimer (L3 / Q9 LOCKED), number formats (Q-E unrounded + literal-suffix
percent), conditional formatting rules present (§3 / Q-B B1), kwargs override
config (Q-D), default path resolution (Q-F), Summary context derivations, FLAT
zero-distance rendering, include_sheets subsetting, multi-engine smoke (xlsxwriter
imports lazily and only when requested).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
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
    EXPORT_BASE_ENV,
    FORMAT_SPEC,
    SHEET_SPEC,
    export,
)
from openpyxl import load_workbook

# --- Constants reused across plans -------------------------------------------------------------
_AS_OF = date(2024, 1, 12)
_FILL_TS = datetime(2024, 1, 16, 14, 30, tzinfo=timezone.utc)
_ENTRY = Decimal("121.40")
_STOP_LONG = Decimal("117.60")
_TARGET_LONG = Decimal("129.00")
_QTY = Decimal("263")
_ATR = 1.90


def _votes_long() -> list[IndicatorVote]:
    """Return a complete, all-positive vote set across four families."""
    return [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.40),
        IndicatorVote(family="trend", name="ema_cross", vote=1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.8, weight=0.25),
        IndicatorVote(family="volatility", name="bb_pctb", vote=0.6, weight=0.20),
        IndicatorVote(family="volume", name="obv_slope", vote=1.0, weight=0.15),
        IndicatorVote(family="volume", name="cmf", vote=1.0, weight=0.15),
    ]


def _make_plan(
    symbol: str = "NVDA",
    segment: str = "Information Technology",
    *,
    direction: str = "long",
    action: str = "BUY",
    conviction: str = "High",
    score: float = 0.78,
) -> TradePlan:
    """Build a paper-filled TradePlan suitable for export."""
    sig = MoverSignal(
        symbol=symbol,
        segment=segment,
        as_of=_AS_OF,
        score=score,
        direction=direction,
        votes=_votes_long(),
        rank_in_segment=1,
    )
    if direction == "flat":
        rec = Recommendation(
            symbol=symbol,
            segment=segment,
            as_of=_AS_OF,
            action="HOLD/FLAT",
            conviction="Low",
            score=score,
            entry_price=_ENTRY,
            stop_price=_ENTRY,
            target_price=_ENTRY,
            stop_distance_pct=0.0,
            target_distance_pct=0.0,
            risk_reward=0.0,
            atr=_ATR,
            position_size=Decimal(0),
            risk_per_share=Decimal(0),
            risk_pct_of_notional=0.0,
            time_stop_bars=None,
            reasoning=f"Hold {symbol}: below the entry threshold.",
            top_factors=[],
            caveats="None.",
        )
        return TradePlan(
            symbol=symbol,
            segment=segment,
            as_of=_AS_OF,
            signal=sig,
            rule=EntryExitRule(),
            position_size=Decimal(0),
            orders=[],
            simulated_fills=[],
            recommendation=rec,
        )
    rec = Recommendation(
        symbol=symbol,
        segment=segment,
        as_of=_AS_OF,
        action=action,
        conviction=conviction,
        score=score,
        entry_price=_ENTRY,
        stop_price=_STOP_LONG,
        target_price=_TARGET_LONG,
        stop_distance_pct=0.03130148270181219,
        target_distance_pct=0.06260296540362438,
        risk_reward=2.0,
        atr=_ATR,
        position_size=_QTY,
        risk_per_share=Decimal("3.80"),
        risk_pct_of_notional=0.009994,
        time_stop_bars=20,
        reasoning=f"Long {symbol}: trend strong positive.",
        top_factors=["macd_hist+ (trend)", "ema_cross+ (trend)"],
        caveats="None.",
    )
    orders = [
        Order(
            symbol=symbol,
            side="buy",
            quantity=_QTY,
            order_type="market",
            tif="day",
            intent="entry",
        ),
        Order(
            symbol=symbol,
            side="sell",
            quantity=_QTY,
            order_type="stop",
            stop_price=_STOP_LONG,
            tif="gtc",
            intent="exit_stop",
        ),
        Order(
            symbol=symbol,
            side="sell",
            quantity=_QTY,
            order_type="limit",
            limit_price=_TARGET_LONG,
            tif="gtc",
            intent="exit_target",
        ),
    ]
    fills = [
        Fill(
            order_ref=f"{symbol}:entry",
            timestamp=_FILL_TS,
            symbol=symbol,
            side="buy",
            quantity=_QTY,
            price=_ENTRY,
            commission=Decimal("0"),
            slippage=Decimal("0.06"),
        )
    ]
    return TradePlan(
        symbol=symbol,
        segment=segment,
        as_of=_AS_OF,
        signal=sig,
        rule=EntryExitRule(),
        position_size=_QTY,
        orders=orders,
        simulated_fills=fills,
        recommendation=rec,
    )


@pytest.fixture
def out_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build an ephemeral output path inside pytest's tmp_path.

    Sets ``TECHTRADE_EXPORT_ALLOW_ABSOLUTE=1`` because tests need to write to
    an absolute pytest ``tmp_path``. Production callers must NOT set this env
    — cfg.path is otherwise sandboxed inside the base dir via safe_join to
    defend against path-traversal (bd-cwer / bd-qawo).
    """
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    return tmp_path / "workbook.xlsx"


# --- Sheet / column / order acceptance ---------------------------------------------------------


def test_export_writes_all_six_canonical_sheets(out_path: Path):
    """L2: workbook carries exactly the six canonical sheets, in canonical order."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    assert wb.sheetnames == list(CANONICAL_SHEETS)


def test_export_returns_absolute_string_path(out_path: Path):
    """Q-F: export returns the absolute path of the written workbook as a str."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    assert isinstance(path, str)
    assert Path(path).is_absolute()
    assert Path(path).exists()


def test_export_writes_title_and_disclaimer_on_recommendations(out_path: Path):
    """L3 / Q9 LOCKED: every workbook prints the disclaimer on the Recommendations sheet."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec_sheet = wb["Recommendations"]
    assert "OpenBB TechTrade" in rec_sheet["A1"].value
    assert rec_sheet["A1"].value.endswith("2024-01-12")
    assert rec_sheet["A2"].value == DISCLAIMER


def test_disclaimer_is_a_literal_constant():
    """L3: the disclaimer string is the locked constant -- never edited at runtime."""
    assert DISCLAIMER == "Research/paper output - not investment advice"


def test_recommendations_header_starts_on_row_4(out_path: Path):
    """Recommendations: title (row 1) + disclaimer (row 2) + blank (row 3) + header (row 4)."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    assert wb["Recommendations"]["A4"].value == "Segment"
    assert wb["Recommendations"]["B4"].value == "Symbol"


# --- Row sort order (L6) -----------------------------------------------------------------------


def test_rows_sorted_segment_then_conviction(out_path: Path):
    """L6: rows sort by segment -> conviction (High first) -> action -> symbol."""
    plans = [
        _make_plan(symbol="AAA", segment="Materials", conviction="Low", score=0.45),
        _make_plan(symbol="ZZZ", segment="Materials", conviction="High", score=0.85),
        _make_plan(symbol="BBB", segment="Energy", conviction="Medium", score=0.55),
    ]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    # Data starts on row 5 (header row 4). Segment col A.
    rows = [
        (
            rec.cell(row=r, column=1).value,
            rec.cell(row=r, column=2).value,
            rec.cell(row=r, column=4).value,
        )
        for r in range(5, 8)
    ]
    assert rows == [
        ("Energy", "BBB", "Medium"),
        ("Materials", "ZZZ", "High"),  # High before Low within Materials
        ("Materials", "AAA", "Low"),
    ]


# --- Number formats (Q-E + L9) -----------------------------------------------------------------


def test_currency_format_on_entry_column(out_path: Path):
    """Q-E: currency columns render with '"$"#,##0.00' format."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    # Entry is column F (index 6) on row 5
    assert rec.cell(row=5, column=6).number_format == '"$"#,##0.00'


def test_score_format_with_explicit_sign(out_path: Path):
    """Q-E: score uses '+0.00;-0.00' so the sign is always visible."""
    plans = [_make_plan(score=0.78)]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    # Score column E (index 5) on row 5
    assert rec.cell(row=5, column=5).number_format == "+0.00;-0.00"


def test_percent_uses_literal_suffix_no_x100(out_path: Path):
    """Q-E option (a): percent fields use '0.00"%"' so cell value equals model field (no x100)."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    # Stop % is column I (index 9); cell value should be 3.13... (model_pct * 100, NOT *100*100)
    stop_pct = rec.cell(row=5, column=9)
    assert stop_pct.number_format == '0.00"%"'
    # Original model: stop_distance_pct = 0.0313 (fraction). SHEET_SPEC multiplies by 100 once
    # (so the displayed number is a percent), and the literal-suffix format does NOT multiply again.
    assert stop_pct.value == pytest.approx(3.130148270181219, abs=1e-9)


def test_decimal_stored_as_unrounded_float(out_path: Path):
    """Q-E / L9: Decimal money is written as float(Decimal) unrounded (cell value == model value)."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    assert rec.cell(row=5, column=6).value == pytest.approx(121.40)  # entry
    assert rec.cell(row=5, column=7).value == pytest.approx(117.60)  # stop
    assert rec.cell(row=5, column=8).value == pytest.approx(129.00)  # target


# --- Conditional formatting (§3 / Q-B B1) ------------------------------------------------------


def test_conditional_formatting_rules_present_on_recommendations(out_path: Path):
    """§3 / Q-B B1: openpyxl CF rules are present on Action, Conviction, Score, Stop %, R:R."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    # FORMAT_SPEC declares 5 rules on Recommendations; the count of distinct ranges should match.
    cf_ranges = list(rec.conditional_formatting._cf_rules.keys())
    expected_rule_count = sum(
        1 for rule in FORMAT_SPEC if rule.sheet == "Recommendations"
    )
    assert len(cf_ranges) == expected_rule_count


def test_conditional_formatting_disabled_when_config_off(out_path: Path):
    """L5: ExportConfig.conditional_formatting=False yields zero CF rules."""
    plans = [_make_plan()]
    path = export(
        plans, config=ExportConfig(path=str(out_path), conditional_formatting=False)
    )
    wb = load_workbook(path)
    rec = wb["Recommendations"]
    assert len(list(rec.conditional_formatting._cf_rules.keys())) == 0


# --- include_sheets subsetting (L2) -------------------------------------------------------------


def test_include_sheets_subsets_but_preserves_canonical_order(out_path: Path):
    """L2: include_sheets may subset but never reorder; output is the canonical-order intersection."""
    plans = [_make_plan()]
    # Pass sheets in WRONG order in the config; output must still be canonical.
    cfg = ExportConfig(
        path=str(out_path),
        include_sheets=["Summary", "Recommendations", "Orders"],
    )
    path = export(plans, config=cfg)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Recommendations", "Orders", "Summary"]


# --- FLAT plan rendering (Q-D zero-distance branch) --------------------------------------------


def test_flat_plan_renders_zero_distance_and_no_orders(out_path: Path):
    """Q-D: FLAT plan exports with zero-distance levels, no orders, no fills, 'None.' caveats."""
    plans = [
        _make_plan(direction="flat", action="HOLD/FLAT", conviction="Low", score=0.05)
    ]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    # Recommendations row exists with zero-distance gaps.
    rec = wb["Recommendations"]
    assert rec.cell(row=5, column=3).value == "HOLD/FLAT"
    assert rec.cell(row=5, column=9).value == pytest.approx(0.0)
    # Orders + Fills sheets are header-only (no data rows).
    orders = wb["Orders"]
    fills = wb["Fills"]
    # Orders header row at 1, no data rows -> max_row should still report only the header.
    assert all(
        orders.cell(row=2, column=c).value is None
        for c in range(1, len(SHEET_SPEC["Orders"]) + 1)
    )
    assert all(
        fills.cell(row=2, column=c).value is None
        for c in range(1, len(SHEET_SPEC["Fills"]) + 1)
    )


# --- Summary context derivations (Q-D option (i)) ----------------------------------------------


def test_summary_uses_na_when_context_absent(out_path: Path):
    """Q-D (i): missing context cells render as 'n/a' rather than failing or omitting the row."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    summary = wb["Summary"]
    rows = {
        summary.cell(row=r, column=1).value: summary.cell(row=r, column=2).value
        for r in range(2, summary.max_row + 1)
        if summary.cell(row=r, column=1).value
    }
    assert rows["Calendar"] == "n/a"
    assert rows["Preset"] == "n/a"
    assert rows["Submodule pin (pandas-ta-classic)"] == "n/a"


def test_summary_uses_context_when_provided(out_path: Path):
    """Q-D (i): non-derivable cells take values from the optional context mapping."""
    plans = [_make_plan()]
    context = {
        "calendar": "XNYS",
        "preset": "trend_follow",
        "weights": "0.40/0.25/0.20/0.15",
        "submodule_pin": "cfda99036ba64a4983e5871d42d1865743b7c6a9",
    }
    path = export(plans, config=ExportConfig(path=str(out_path)), context=context)
    wb = load_workbook(path)
    summary = wb["Summary"]
    rows = {
        summary.cell(row=r, column=1).value: summary.cell(row=r, column=2).value
        for r in range(2, summary.max_row + 1)
        if summary.cell(row=r, column=1).value
    }
    assert rows["Calendar"] == "XNYS"
    assert rows["Preset"] == "trend_follow"
    assert (
        rows["Submodule pin (pandas-ta-classic)"]
        == "cfda99036ba64a4983e5871d42d1865743b7c6a9"
    )


def test_summary_action_counts_are_derived(out_path: Path):
    """Q-C / Q-D: BUY / SELL_SHORT / HOLD/FLAT counts are derived from plans."""
    plans = [
        _make_plan(symbol="A", action="BUY"),
        _make_plan(symbol="B", action="BUY"),
        _make_plan(
            symbol="C",
            direction="flat",
            action="HOLD/FLAT",
            conviction="Low",
            score=0.05,
        ),
    ]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    summary = wb["Summary"]
    rows = {
        summary.cell(row=r, column=1).value: summary.cell(row=r, column=2).value
        for r in range(2, summary.max_row + 1)
        if summary.cell(row=r, column=1).value
    }
    assert rows["BUY"] == 2
    assert rows["HOLD/FLAT"] == 1
    assert rows["SELL_SHORT"] == 0


def test_summary_avg_rr_is_actionable_only(out_path: Path):
    """Q-C: avg R:R averages over actionable rows only (FLAT plans excluded)."""
    plans = [
        _make_plan(symbol="A"),
        _make_plan(symbol="B"),
        _make_plan(
            symbol="C",
            direction="flat",
            action="HOLD/FLAT",
            conviction="Low",
            score=0.05,
        ),
    ]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    summary = wb["Summary"]
    rows = {
        summary.cell(row=r, column=1).value: summary.cell(row=r, column=2).value
        for r in range(2, summary.max_row + 1)
        if summary.cell(row=r, column=1).value
    }
    assert rows["Avg R:R (actionable)"] == pytest.approx(2.0)


# --- Reasoning sheet vote breakdown (Q-C) ------------------------------------------------------


def test_reasoning_sheet_has_per_family_vote_columns(out_path: Path):
    """Q-C answer 2: Reasoning sheet has Trend / Momentum / Volatility / Volume columns."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    reasoning = wb["Reasoning"]
    headers = [
        reasoning.cell(row=1, column=c).value
        for c in range(1, reasoning.max_column + 1)
    ]
    for family in ("Trend", "Momentum", "Volatility", "Volume"):
        assert family in headers


def test_reasoning_family_contribution_is_signed_sum(out_path: Path):
    """Q-C answer 2: family cell = sum(weight * vote) over that family (signed)."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    reasoning = wb["Reasoning"]
    headers = [
        reasoning.cell(row=1, column=c).value
        for c in range(1, reasoning.max_column + 1)
    ]
    trend_col = headers.index("Trend") + 1
    # Two trend votes: 1.0 * 0.40 + 1.0 * 0.40 = 0.80
    assert reasoning.cell(row=2, column=trend_col).value == pytest.approx(0.80)


# --- Engine selection / default path / overwrite behaviour ---------------------------------------


def test_default_path_uses_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Q-F: TECHTRADE_EXPORT_DIR env override redirects the default base dir."""
    monkeypatch.setenv(EXPORT_BASE_ENV, str(tmp_path))
    plans = [_make_plan()]
    # Pass config without path so the default-path resolver runs.
    path = export(plans, config=ExportConfig(path=None))
    assert Path(path).parent == tmp_path
    assert Path(path).name == f"techtrade_{_AS_OF.isoformat()}.xlsx"


def test_same_as_of_overwrites_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Q-F: same as-of => same filename overwrites silently (deterministic, re-runnable artifact)."""
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    plans = [_make_plan()]
    out = tmp_path / "fixed.xlsx"
    path_a = export(plans, config=ExportConfig(path=str(out)))
    path_b = export(plans, config=ExportConfig(path=str(out)))
    assert path_a == path_b
    assert Path(path_a).exists()


def test_export_creates_missing_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Q-F: missing parent directory is auto-created (mkdir parents=True)."""
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    deep = tmp_path / "nested" / "deep" / "dir"
    out = deep / "wb.xlsx"
    assert not deep.exists()
    plans = [_make_plan()]
    export(plans, config=ExportConfig(path=str(out)))
    assert out.exists()


# --- xlsxwriter engine smoke (best-effort richer) ------------------------------------------------


def test_xlsxwriter_engine_writes_six_sheets(out_path: Path):
    """L1 / Q-B B1: xlsxwriter engine writes the same six sheets when selected (best-effort)."""
    xlsxwriter = pytest.importorskip("xlsxwriter")  # noqa: F841 - optional dep
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path), engine="xlsxwriter"))
    wb = load_workbook(path)
    assert wb.sheetnames == list(CANONICAL_SHEETS)
    # Disclaimer + title still present (rendered by xlsxwriter writer).
    rec_sheet = wb["Recommendations"]
    assert "OpenBB TechTrade" in rec_sheet["A1"].value
    assert rec_sheet["A2"].value == DISCLAIMER


# --- Empty / edge inputs -------------------------------------------------------------------------


def test_empty_plans_yields_header_only_workbook(out_path: Path):
    """Edge: zero plans -> workbook with all 6 sheets but no data rows; disclaimer still printed."""
    path = export([], config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    assert wb.sheetnames == list(CANONICAL_SHEETS)
    # Recommendations: title + disclaimer + header on row 4, no data on row 5.
    rec_sheet = wb["Recommendations"]
    assert rec_sheet["A2"].value == DISCLAIMER
    assert rec_sheet["A4"].value == "Segment"
    assert rec_sheet["A5"].value is None


def test_fill_timestamp_is_naive_in_cell(out_path: Path):
    """Excel does not support tz-aware datetimes; the coerce boundary strips tzinfo (UTC-converted)."""
    plans = [_make_plan()]
    path = export(plans, config=ExportConfig(path=str(out_path)))
    wb = load_workbook(path)
    fills_sheet = wb["Fills"]
    # Timestamp is the last column on the Fills sheet.
    headers = [
        fills_sheet.cell(row=1, column=c).value
        for c in range(1, fills_sheet.max_column + 1)
    ]
    ts_col = headers.index("Timestamp") + 1
    cell_value = fills_sheet.cell(row=2, column=ts_col).value
    assert isinstance(cell_value, datetime)
    assert cell_value.tzinfo is None
    # Original UTC instant preserved (14:30 UTC).
    assert cell_value.year == 2024 and cell_value.month == 1 and cell_value.day == 16
    assert cell_value.hour == 14 and cell_value.minute == 30


# --- Determinism (L6) ---------------------------------------------------------------------------


def test_two_runs_with_identical_inputs_produce_identical_logical_workbook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L6: same plans + same out path -> same sheet names, same cell values across runs."""
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    plans = [_make_plan(symbol="A"), _make_plan(symbol="B")]
    out_a = tmp_path / "a.xlsx"
    out_b = tmp_path / "b.xlsx"
    export(plans, config=ExportConfig(path=str(out_a)))
    export(plans, config=ExportConfig(path=str(out_b)))
    wb_a = load_workbook(out_a)
    wb_b = load_workbook(out_b)

    def _snapshot(wb):
        return {
            sheet: [
                [
                    wb[sheet].cell(row=r, column=c).value
                    for c in range(1, wb[sheet].max_column + 1)
                ]
                for r in range(1, wb[sheet].max_row + 1)
            ]
            for sheet in wb.sheetnames
        }

    assert _snapshot(wb_a) == _snapshot(wb_b)


# ---------------------------------------------------------------------------
# Path-traversal defenses (bd-cwer, closes qawo)
# ---------------------------------------------------------------------------


def test_export_rejects_absolute_cfg_path_without_env_optin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A web-facing caller can't set cfg.path to an arbitrary absolute location.

    Regression test for OpenBBTechnical-qawo: the REST-facing
    ``export_router.export()`` forwards ``cfg.path`` verbatim, so an API client
    supplying ``path='../../etc/passwd.xlsx'`` used to get arbitrary write.
    Now absolute paths require ``TECHTRADE_EXPORT_ALLOW_ABSOLUTE=1`` — trusted
    CLI/notebook callers opt in explicitly; REST callers can't reach the env.
    """
    from openbb_core.app.paths import PathTraversalError

    monkeypatch.delenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", raising=False)
    monkeypatch.setenv("TECHTRADE_EXPORT_DIR", str(tmp_path))
    absolute = str(tmp_path / "workbook.xlsx")  # absolute, points inside tmp
    plans = [_make_plan()]
    with pytest.raises(PathTraversalError, match="absolute"):
        export(plans, config=ExportConfig(path=absolute))


def test_export_rejects_parent_traversal_in_cfg_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relative cfg.path containing '..' segments raises PathTraversalError."""
    from openbb_core.app.paths import PathTraversalError

    monkeypatch.delenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", raising=False)
    monkeypatch.setenv("TECHTRADE_EXPORT_DIR", str(tmp_path))
    plans = [_make_plan()]
    with pytest.raises(PathTraversalError):
        export(plans, config=ExportConfig(path="../evil.xlsx"))


def test_export_accepts_relative_cfg_path_sandboxed_in_base_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A benign relative path is joined onto base dir via safe_join."""
    monkeypatch.delenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", raising=False)
    monkeypatch.setenv("TECHTRADE_EXPORT_DIR", str(tmp_path))
    plans = [_make_plan()]
    result = export(plans, config=ExportConfig(path="myrun.xlsx"))
    assert result == str((tmp_path / "myrun.xlsx").resolve())
    assert (tmp_path / "myrun.xlsx").exists()


def test_export_accepts_absolute_cfg_path_with_env_optin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When TECHTRADE_EXPORT_ALLOW_ABSOLUTE=1 is set, absolute cfg.path is allowed.

    The tmp_path fixture uses the system temp dir, which is in the
    allowlist returned by ``_absolute_path_allowlist()``.
    """
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    absolute = tmp_path / "explicit.xlsx"
    plans = [_make_plan()]
    result = export(plans, config=ExportConfig(path=str(absolute)))
    assert result == str(absolute.resolve())
    assert absolute.exists()


# ---------------------------------------------------------------------------
# Round-1 review findings: allowlist + audit-log on env opt-in (bd-cwer)
# ---------------------------------------------------------------------------


def test_export_rejects_absolute_path_outside_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with the env opt-in, absolute paths outside the allowlist raise.

    Regression test for silent-failure-hunter Round-1 F2/F3 findings — a
    docker/systemd env inheritance that leaks TECHTRADE_EXPORT_ALLOW_ABSOLUTE=1
    into a REST server used to give full arbitrary-write. Now the resolved
    path must sit under EXPORT_BASE_ENV OR system tmp; anywhere else raises.
    """
    from openbb_core.app.paths import PathTraversalError

    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    # Point EXPORT_BASE_ENV somewhere that ISN'T the attack target
    export_base = tmp_path / "allowed_base"
    export_base.mkdir()
    monkeypatch.setenv("TECHTRADE_EXPORT_DIR", str(export_base))

    # Attack: write outside both the base dir AND the system tmp dir.
    # Use the repo root (or any well-known-not-tmp path). We test with a
    # sibling of tmp_path that we ensure is outside the tempdir by using
    # a fresh directory under a NON-tempdir root.
    # On Windows, C:\Windows is definitely not the tempdir; on POSIX /etc is.
    attack = (
        "C:\\Windows\\attacker_write_target.xlsx"
        if os.name == "nt"
        else "/etc/attacker_write_target.xlsx"
    )
    plans = [_make_plan()]
    with pytest.raises(PathTraversalError, match="allowlisted"):
        export(plans, config=ExportConfig(path=attack))


def test_export_accepts_absolute_under_configured_export_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absolute paths under the configured EXPORT_BASE_ENV are allowed with the opt-in."""
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    export_base = tmp_path / "configured_base"
    export_base.mkdir()
    monkeypatch.setenv("TECHTRADE_EXPORT_DIR", str(export_base))

    # Path is absolute AND inside the configured base — should succeed.
    absolute_in_base = export_base / "sub" / "wb.xlsx"
    plans = [_make_plan()]
    result = export(plans, config=ExportConfig(path=str(absolute_in_base)))
    assert result == str(absolute_in_base.resolve())
    assert absolute_in_base.exists()


def test_export_rejects_null_byte_in_cfg_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Null bytes in cfg.path raise, even with the env opt-in set."""
    from openbb_core.app.paths import PathTraversalError

    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    monkeypatch.setenv("TECHTRADE_EXPORT_DIR", str(tmp_path))
    plans = [_make_plan()]
    with pytest.raises(PathTraversalError, match="null byte"):
        export(plans, config=ExportConfig(path="wb\x00.xlsx"))


def test_export_logs_warning_when_env_optin_honored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every honored absolute cfg.path emits a WARNING log line (audit trail).

    Regression test for silent-failure-hunter F2: a misconfigured
    production host (docker env leak) should surface in operator logs,
    not silently accept arbitrary absolute writes.
    """
    import logging

    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    absolute = tmp_path / "logged.xlsx"
    plans = [_make_plan()]
    with caplog.at_level(
        logging.WARNING,
        logger="openbb_techtrade.reporting.excel_export",
    ):
        export(plans, config=ExportConfig(path=str(absolute)))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "Expected a WARNING log line for the honored absolute path"
    combined = "\n".join(r.getMessage() for r in warnings)
    assert "TECHTRADE_EXPORT_ALLOW_ABSOLUTE" in combined
    assert str(absolute) in combined or str(absolute.resolve()) in combined
