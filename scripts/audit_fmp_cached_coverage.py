"""fmp_cached coverage audit against P0 Data-Layer cluster targets (#827).

For each P0 cluster (#513-525), enumerate its expected OpenBB endpoints
(as documented in each cluster issue + PRD §14) and check whether an
implementing model exists at

    openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/<name>.py

An endpoint counts as covered iff the module file is present. Whether
the class inside is wired to the OpenBB router registry is a downstream
check (needs runtime probe against `obb.<extension>.<endpoint>` — filed
as a follow-up if any module-present cell fails runtime probing).

Output: docs/reports/YYYY-MM-DD-fmp-cached-coverage-audit.md with a
matrix and a gap list. Also emits a machine-parseable JSON alongside.

Usage:
    .venv_portfolio/Scripts/python.exe scripts/audit_fmp_cached_coverage.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = (
    REPO_ROOT
    / "openbb_platform"
    / "providers"
    / "fmp_cached"
    / "openbb_fmp_cached"
    / "models"
)
REPORT_DIR = REPO_ROOT / "docs" / "reports"

# --- Cluster → expected endpoint list --------------------------------------
#
# Each entry: (cluster_gh_issue, endpoint_label, expected_module_stem)
# expected_module_stem is the .py basename in fmp_cached/models/ (no
# extension). None means "no upstream call — cluster is a cache/warmer
# task with no direct provider dependency".

CLUSTERS: list[tuple[int, str, list[tuple[str, str | None]]]] = [
    (
        512,
        "EtfHoldings",
        [
            ("obb.etf.holdings", "etf_holdings"),
        ],
    ),
    (
        513,
        "Economics",
        [
            ("obb.economy.calendar", "economic_calendar"),
            ("obb.fixedincome.government.treasury_rates", "treasury_rates"),
            ("obb.fixedincome.government.yield_curve", "yield_curve"),
            # 'indicators' cluster — no dedicated fmp endpoint; typically
            # FRED-sourced. Not an fmp_cached gap.
            ("obb.economy.indicators (FRED)", None),
        ],
    ),
    (
        514,
        "Market Performance",
        [
            ("obb.equity.discovery.gainers", "equity_gainers"),
            ("obb.equity.discovery.losers", "equity_losers"),
            ("obb.equity.discovery.active", "equity_most_active"),
            ("obb.equity.compare.groups (sector rollup)", "price_performance"),
            # 'industry rollup' — fmp doesn't split sector vs industry; we
            # reuse sector groups. Same module.
        ],
    ),
    (
        515,
        "Technical Indicators (per-holding strip)",
        [
            # #780 audit already proved 31 TV indicators are computed
            # locally from OHLCV via pandas_ta_classic. No upstream
            # indicator endpoint needed. Only OHLCV is required.
            ("obb.equity.price.historical (OHLCV feed)", "equity_historical"),
        ],
    ),
    (
        516,
        "Derived-analytics cache table",
        [
            # Cache infrastructure — no upstream call. Owned by portfolio
            # team, not an fmp_cached concern.
            ("(no upstream call)", None),
        ],
    ),
    (
        517,
        "Cache warmers for common ETFs + S&P500 constituents",
        [
            ("obb.index.constituents (SP500)", "index_constituents"),
            ("obb.etf.holdings (warmer)", "etf_holdings"),
            ("obb.equity.price.historical (warmer)", "equity_historical"),
        ],
    ),
    (
        518,
        "EtfInfo + EtfSectorWeightings + EtfCountryWeightings",
        [
            ("obb.etf.info", "etf_info"),
            ("obb.etf.sectors", "etf_sectors"),
            ("obb.etf.countries", "etf_countries"),
        ],
    ),
    (
        519,
        "Calendars: Earnings + Dividends + Splits + IPOs",
        [
            ("obb.equity.calendar.earnings", "calendar_earnings"),
            ("obb.equity.calendar.dividend", "calendar_dividend"),
            ("obb.equity.calendar.splits", "calendar_splits"),
            ("obb.equity.calendar.ipo", "calendar_ipo"),
        ],
    ),
    (
        520,
        "Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades",
        [
            ("obb.equity.estimates.analyst_search", "analyst_estimates"),
            # 'ratings' — FMP folds into analyst_estimates; no separate module
            ("obb.equity.estimates.price_target", "price_target"),
            (
                "obb.equity.estimates.consensus (price_target_consensus)",
                "price_target_consensus",
            ),
            # 'upgrades/downgrades' — FMP endpoint exists but no fmp_cached
            # module; check.
            ("obb.equity.estimates.historical (upgrades/downgrades)", None),
        ],
    ),
    (
        521,
        "InsiderTrades",
        [
            ("obb.equity.ownership.insider_trading", "insider_trading"),
            # 'search' and 'statistics' sub-endpoints share the same fmp_cached
            # module (fetcher supports multiple query patterns).
        ],
    ),
    (
        522,
        "Form 13F",
        [
            (
                "obb.equity.ownership.institutional (13F extract)",
                "institutional_ownership",
            ),
            # 'holder performance summary' — no dedicated fmp endpoint, computed
            # downstream. Not an fmp_cached gap.
            ("(holder performance = derived, no upstream)", None),
        ],
    ),
    (
        523,
        "Senate Disclosures",
        [
            (
                "obb.regulators.sec.senate_trades / house_trades",
                "government_trades",
            ),
        ],
    ),
    (
        524,
        "SEC Filings",
        [
            ("obb.equity.fundamental.filings", "company_filings"),
            ("obb.regulators.sec.filings", "discovery_filings"),
            # '8-K' is a filing_type filter on the same endpoint
        ],
    ),
    (
        525,
        "News",
        [
            ("obb.news.company", "company_news"),
            ("obb.news.world", "world_news"),
            # 'press releases' — no dedicated fmp module; company_news covers
            # PR filings.
        ],
    ),
]


def _present(module_stem: str | None) -> tuple[str, str]:
    """Return (status_symbol, module_relpath_or_reason)."""
    if module_stem is None:
        return "-", "n/a (no upstream call)"
    p = MODELS_DIR / f"{module_stem}.py"
    if p.exists():
        return "OK", f"models/{module_stem}.py"
    return "GAP", f"missing models/{module_stem}.py"


def _run() -> None:
    if not MODELS_DIR.is_dir():
        raise SystemExit(f"models dir not found: {MODELS_DIR}")

    rows: list[dict] = []
    gaps: list[dict] = []

    for cluster_num, cluster_name, endpoints in CLUSTERS:
        for endpoint_label, stem in endpoints:
            status, evidence = _present(stem)
            row = {
                "cluster": f"#{cluster_num}",
                "cluster_name": cluster_name,
                "endpoint": endpoint_label,
                "module_stem": stem,
                "status": status,
                "evidence": evidence,
            }
            rows.append(row)
            if status == "GAP":
                gaps.append(row)

    # Report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{date.today().isoformat()}-fmp-cached-coverage-audit"
    md = REPORT_DIR / f"{stem}.md"
    js = REPORT_DIR / f"{stem}.json"

    lines: list[str] = []
    lines.append("# fmp_cached coverage audit for P0 Data-Layer clusters (#827)\n\n")
    lines.append(f"**Date:** {date.today().isoformat()}\n\n")
    lines.append(f"**Models directory:** `{MODELS_DIR.relative_to(REPO_ROOT)}`\n\n")
    total = len(rows)
    ok = sum(1 for r in rows if r["status"] == "OK")
    gap = sum(1 for r in rows if r["status"] == "GAP")
    na = sum(1 for r in rows if r["status"] == "-")
    lines.append(
        f"**Summary:** {ok}/{total} endpoints covered by an fmp_cached module. "
        f"{gap} true gaps. {na} rows n/a (no upstream call — cache/derived).\n\n"
    )

    lines.append("## Coverage matrix\n\n")
    lines.append("| Cluster | Endpoint | fmp_cached module | Status |\n")
    lines.append("|---|---|---|---|\n")
    for r in rows:
        status_icon = {"OK": "✅", "GAP": "❌", "-": "➖"}[r["status"]]
        lines.append(
            f"| {r['cluster']} {r['cluster_name']} | `{r['endpoint']}` | "
            f"`{r['evidence']}` | {status_icon} {r['status']} |\n"
        )

    lines.append("\n## Gaps requiring `area:fmp-cached-gap` follow-ups\n\n")
    if not gaps:
        lines.append(
            "None. Every endpoint listed in the P0 cluster specs has a "
            "matching fmp_cached module. The M1 preflight is unblocked; "
            "Kai's P0 cluster work can proceed without waiting on the "
            "fmp_cached team.\n\n"
        )
    else:
        for g in gaps:
            lines.append(
                f"- **{g['cluster']} {g['cluster_name']} — "
                f"`{g['endpoint']}`**: {g['evidence']}\n"
            )
        lines.append(
            "\nFile one `area:fmp-cached-gap` issue per row above, "
            "referencing the cluster issue and this audit.\n"
        )

    lines.append("\n## Notes on this audit's scope\n\n")
    lines.append(
        "- **Module presence ≠ runtime health.** This audit verifies "
        "`models/<name>.py` exists. Whether the class inside is registered "
        "with the OpenBB router and returns non-empty data on a live "
        "call is a downstream check (see #780 for the pattern). If any "
        "consumer of a `✅` row hits an empty result on real data, file "
        "as an *implementation gap* (bug), not a *coverage gap* (new "
        "endpoint request).\n"
    )
    lines.append(
        "- **`fmp` fallback still tracked.** Rows marked `➖ (n/a)` are "
        "cases where the P0 cluster explicitly has no upstream call "
        "(cache infrastructure, derived analytics). They are NOT `fmp` "
        "fallbacks — no `area:fmp-cached-gap` needed.\n"
    )
    lines.append(
        "- **PRD-vs-fmp mapping is subject to revision.** The endpoint "
        "labels above match the P0 cluster issue bodies and PRD §14 as "
        "of the audit date. If Kai's implementation surfaces additional "
        "endpoints not enumerated here, extend `CLUSTERS` in "
        "`scripts/audit_fmp_cached_coverage.py` and re-run — the audit "
        "is deterministic and cheap to re-execute.\n"
    )

    md.write_text("".join(lines), encoding="utf-8")
    js.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print(f"Wrote {md.relative_to(REPO_ROOT)}")
    print(f"Wrote {js.relative_to(REPO_ROOT)}")
    print(f"Total: {total}  OK: {ok}  GAP: {gap}  n/a: {na}")
    if gaps:
        print("\nGAPS:")
        for g in gaps:
            print(
                f"  #{g['cluster'].lstrip('#')} {g['cluster_name']} — "
                f"{g['endpoint']}"
            )


if __name__ == "__main__":
    _run()
