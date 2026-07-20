"""Runtime probe of P0 Data-Layer endpoints (#513-#525).

For each cluster in #513-#525, live-hit every documented endpoint via
``obb.<endpoint>`` on a small representative fixture, record shape +
row count, and emit a report. This is the **runtime** counterpart to
the module-presence audit shipped as PR #925 (#827) — that one checked
"does the .py file exist"; this one checks "does the endpoint return
non-empty data on live fmp_cached."

## Output

- ``docs/reports/YYYY-MM-DD-p0-data-runtime-audit.md``: markdown matrix
- ``docs/reports/YYYY-MM-DD-p0-data-runtime-audit.json``: machine-parseable

## Usage

    .venv_portfolio/Scripts/python.exe scripts/audit_p0_data_runtime.py

Requires FMP API key in user_settings.json (auto-loaded by OpenBB).

## Interpretation

For each (cluster, endpoint) row:
- ``OK``  — endpoint returned a non-empty result. Downstream widgets can use it.
- ``EMPTY`` — endpoint returned an empty result but did not crash. May be
  a valid state (e.g. no IPOs today) OR a silent-fail bug — investigate
  each case.
- ``ERROR`` — endpoint raised. Reason recorded.
- ``UNAVAILABLE`` — endpoint not on ``obb.*`` in the current venv. Missing
  extension install; file as env-sync bug.
- ``SKIPPED`` — deliberately not probed (e.g. cache-warmer clusters that
  don't call upstream directly).
"""

from __future__ import annotations

import json
import traceback
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "docs" / "reports"

# Test symbol universe — small basket that should return data on every
# endpoint. AAPL is the canonical single-name; SPY for ETF; ^GSPC for
# broad-market where a benchmark symbol is required.
TEST_SYMBOL = "AAPL"
TEST_ETF = "SPY"
TEST_INDEX = "sp500"


@dataclass
class ProbeResult:
    cluster: int
    endpoint: str
    label: str
    status: str  # OK | EMPTY | ERROR | UNAVAILABLE | SKIPPED
    row_count: int | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Per-cluster probes
# ---------------------------------------------------------------------------


def _try(cluster: int, endpoint: str, label: str, fn) -> ProbeResult:
    """Wrap one endpoint call in try/except; classify the outcome."""
    try:
        resp = fn()
    except AttributeError as exc:
        return ProbeResult(
            cluster=cluster,
            endpoint=endpoint,
            label=label,
            status="UNAVAILABLE",
            reason=f"AttributeError on obb.*: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(
            cluster=cluster,
            endpoint=endpoint,
            label=label,
            status="ERROR",
            reason=f"{type(exc).__name__}: {exc}"[:200],
        )
    results = getattr(resp, "results", None)
    if results is None:
        return ProbeResult(
            cluster=cluster,
            endpoint=endpoint,
            label=label,
            status="EMPTY",
            row_count=0,
            reason="no .results attribute",
        )
    n = len(results) if hasattr(results, "__len__") else 1
    return ProbeResult(
        cluster=cluster,
            endpoint=endpoint,
            label=label,
            status="OK" if n > 0 else "EMPTY",
            row_count=n,
    )


def _probe_513_economics(obb) -> list[ProbeResult]:
    """#513 Economics: calendar + treasury rates + indicators."""
    end = date.today()
    start = end - timedelta(days=7)
    return [
        _try(513, "obb.economy.calendar", "Economic calendar",
             lambda: obb.economy.calendar(start_date=start, end_date=end, provider="fmp_cached")),
        _try(513, "obb.fixedincome.government.treasury_rates", "Treasury rates",
             lambda: obb.fixedincome.government.treasury_rates(provider="fmp_cached")),
        _try(513, "obb.economy.indicators", "Economic indicators (FRED)",
             lambda: obb.economy.indicators(symbol="GDP", provider="fred")),
    ]


def _probe_514_market_performance(obb) -> list[ProbeResult]:
    """#514 Market Performance: sector + industry + gainers/losers."""
    return [
        _try(514, "obb.equity.discovery.gainers", "Gainers",
             lambda: obb.equity.discovery.gainers(provider="fmp_cached")),
        _try(514, "obb.equity.discovery.losers", "Losers",
             lambda: obb.equity.discovery.losers(provider="fmp_cached")),
        _try(514, "obb.equity.discovery.active", "Most active",
             lambda: obb.equity.discovery.active(provider="fmp_cached")),
        _try(514, "obb.equity.compare.groups", "Sector rollup",
             lambda: obb.equity.compare.groups(provider="fmp_cached")),
    ]


def _probe_515_technical_indicators(obb) -> list[ProbeResult]:
    """#515 Technical Indicators: OHLCV feed (indicators computed locally).

    Per audit #925: 31 TV indicators covered via pandas_ta_classic on
    OHLCV — no upstream indicator endpoint needed. Only OHLCV is probed.
    """
    return [
        _try(515, "obb.equity.price.historical", "OHLCV for TA (per-holding strip)",
             lambda: obb.equity.price.historical(symbol=TEST_SYMBOL, provider="fmp_cached", interval="1d")),
    ]


def _probe_516_cache_table() -> list[ProbeResult]:
    """#516 Derived-analytics cache table — infra, no upstream call."""
    return [
        ProbeResult(
            cluster=516,
            endpoint="(no upstream)",
            label="portfolio_intel_cache table",
            status="SKIPPED",
            reason="Cache infrastructure — no upstream endpoint to probe",
        )
    ]


def _probe_517_warmers(obb) -> list[ProbeResult]:
    """#517 Cache warmers: SP500 constituents + ETF holdings."""
    return [
        _try(517, "obb.index.constituents", "SP500 constituents (warmer)",
             lambda: obb.index.constituents(symbol=TEST_INDEX, provider="fmp_cached")),
        _try(517, "obb.etf.holdings", "ETF holdings warmer",
             lambda: obb.etf.holdings(symbol=TEST_ETF, provider="fmp_cached")),
        _try(517, "obb.equity.price.historical", "OHLCV warmer",
             lambda: obb.equity.price.historical(symbol=TEST_SYMBOL, provider="fmp_cached", interval="1d")),
    ]


def _probe_518_etf_meta(obb) -> list[ProbeResult]:
    """#518 EtfInfo + SectorWeightings + CountryWeightings."""
    return [
        _try(518, "obb.etf.info", "ETF info",
             lambda: obb.etf.info(symbol=TEST_ETF, provider="fmp_cached")),
        _try(518, "obb.etf.sectors", "ETF sector weightings",
             lambda: obb.etf.sectors(symbol=TEST_ETF, provider="fmp_cached")),
        _try(518, "obb.etf.countries", "ETF country weightings",
             lambda: obb.etf.countries(symbol=TEST_ETF, provider="fmp_cached")),
    ]


def _probe_519_calendars(obb) -> list[ProbeResult]:
    """#519 Calendars: Earnings + Dividends + Splits + IPOs."""
    end = date.today() + timedelta(days=30)
    start = date.today()
    return [
        _try(519, "obb.equity.calendar.earnings", "Earnings calendar",
             lambda: obb.equity.calendar.earnings(start_date=start, end_date=end, provider="fmp_cached")),
        _try(519, "obb.equity.calendar.dividend", "Dividend calendar",
             lambda: obb.equity.calendar.dividend(start_date=start, end_date=end, provider="fmp_cached")),
        _try(519, "obb.equity.calendar.splits", "Splits calendar",
             lambda: obb.equity.calendar.splits(start_date=start, end_date=end, provider="fmp_cached")),
        _try(519, "obb.equity.calendar.ipo", "IPO calendar",
             lambda: obb.equity.calendar.ipo(start_date=start, end_date=end, provider="fmp_cached")),
    ]


def _probe_520_analyst(obb) -> list[ProbeResult]:
    """#520 Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades."""
    return [
        _try(520, "obb.equity.estimates.analyst_search", "Analyst estimates",
             lambda: obb.equity.estimates.analyst_search(symbol=TEST_SYMBOL, provider="fmp_cached")),
        _try(520, "obb.equity.estimates.price_target", "Price target",
             lambda: obb.equity.estimates.price_target(symbol=TEST_SYMBOL, provider="fmp_cached")),
        _try(520, "obb.equity.estimates.consensus", "Price-target consensus",
             lambda: obb.equity.estimates.consensus(symbol=TEST_SYMBOL, provider="fmp_cached")),
    ]


def _probe_521_insider(obb) -> list[ProbeResult]:
    """#521 InsiderTrades."""
    return [
        _try(521, "obb.equity.ownership.insider_trading", "Insider trading",
             lambda: obb.equity.ownership.insider_trading(symbol=TEST_SYMBOL, provider="fmp_cached")),
    ]


def _probe_522_form_13f(obb) -> list[ProbeResult]:
    """#522 Form 13F (institutional ownership)."""
    return [
        _try(522, "obb.equity.ownership.institutional", "Institutional ownership",
             lambda: obb.equity.ownership.institutional(symbol=TEST_SYMBOL, provider="fmp_cached")),
    ]


def _probe_523_senate(obb) -> list[ProbeResult]:
    """#523 Senate disclosures."""
    return [
        _try(523, "obb.regulators.sec.senate_trades", "Senate trades",
             lambda: obb.regulators.sec.senate_trades(symbol=TEST_SYMBOL)),
    ]


def _probe_524_sec_filings(obb) -> list[ProbeResult]:
    """#524 SEC Filings (search + company search + 8-K)."""
    return [
        _try(524, "obb.equity.fundamental.filings", "Company filings",
             lambda: obb.equity.fundamental.filings(symbol=TEST_SYMBOL, provider="fmp_cached")),
    ]


def _probe_525_news(obb) -> list[ProbeResult]:
    """#525 News (stock + press releases + general latest)."""
    return [
        _try(525, "obb.news.company", "Company news",
             lambda: obb.news.company(symbol=TEST_SYMBOL, provider="fmp_cached")),
        _try(525, "obb.news.world", "World / general news",
             lambda: obb.news.world(provider="fmp_cached")),
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _run_all(obb) -> list[ProbeResult]:
    rows: list[ProbeResult] = []
    rows += _probe_513_economics(obb)
    rows += _probe_514_market_performance(obb)
    rows += _probe_515_technical_indicators(obb)
    rows += _probe_516_cache_table()
    rows += _probe_517_warmers(obb)
    rows += _probe_518_etf_meta(obb)
    rows += _probe_519_calendars(obb)
    rows += _probe_520_analyst(obb)
    rows += _probe_521_insider(obb)
    rows += _probe_522_form_13f(obb)
    rows += _probe_523_senate(obb)
    rows += _probe_524_sec_filings(obb)
    rows += _probe_525_news(obb)
    return rows


def _write_report(rows: list[ProbeResult]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{date.today().isoformat()}-p0-data-runtime-audit"
    md = REPORT_DIR / f"{stem}.md"
    js = REPORT_DIR / f"{stem}.json"

    total = len(rows)
    ok = sum(1 for r in rows if r.status == "OK")
    empty = sum(1 for r in rows if r.status == "EMPTY")
    err = sum(1 for r in rows if r.status == "ERROR")
    unav = sum(1 for r in rows if r.status == "UNAVAILABLE")
    skip = sum(1 for r in rows if r.status == "SKIPPED")

    lines: list[str] = [
        "# P0 Data-Layer runtime audit (#513-#525)\n\n",
        f"**Date:** {date.today().isoformat()}\n\n",
        f"**Symbol universe:** AAPL / SPY / sp500\n\n",
        "**Summary:** "
        f"{ok}/{total} OK, {empty} EMPTY, {err} ERROR, {unav} UNAVAILABLE, "
        f"{skip} SKIPPED.\n\n",
        "## Legend\n\n",
        "- **OK** — endpoint returned non-empty results. Downstream widgets unblocked.\n"
        "- **EMPTY** — endpoint returned no rows; may be valid (e.g. no IPOs today) "
        "or silent-fail bug — investigate case-by-case.\n"
        "- **ERROR** — endpoint raised. Reason recorded.\n"
        "- **UNAVAILABLE** — endpoint not on ``obb.*`` in the current venv "
        "(missing extension install). File as env-sync bug.\n"
        "- **SKIPPED** — deliberately not probed (cache infra with no upstream).\n\n",
        "## Coverage matrix\n\n",
        "| Cluster | Endpoint | Label | Status | Rows | Notes |\n",
        "|--------:|----------|-------|--------|-----:|-------|\n",
    ]
    icon = {"OK": "✅", "EMPTY": "⚠️", "ERROR": "❌", "UNAVAILABLE": "❓", "SKIPPED": "➖"}
    for r in rows:
        n = "" if r.row_count is None else str(r.row_count)
        lines.append(
            f"| #{r.cluster} | `{r.endpoint}` | {r.label} | "
            f"{icon[r.status]} {r.status} | {n} | {r.reason or ''} |\n"
        )
    lines.append("\n")

    md.write_text("".join(lines), encoding="utf-8")
    js.write_text(json.dumps([asdict(r) for r in rows], indent=2), encoding="utf-8")
    print(f"Wrote {md.relative_to(REPO_ROOT)}")
    print(f"Wrote {js.relative_to(REPO_ROOT)}")
    print(f"Total: {total}  OK: {ok}  EMPTY: {empty}  ERROR: {err}  UNAVAILABLE: {unav}  SKIPPED: {skip}")


def _main() -> None:
    try:
        from openbb import obb
    except Exception as exc:  # noqa: BLE001
        print(f"failed to import openbb: {exc}")
        traceback.print_exc()
        return
    rows = _run_all(obb)
    _write_report(rows)


if __name__ == "__main__":
    _main()
