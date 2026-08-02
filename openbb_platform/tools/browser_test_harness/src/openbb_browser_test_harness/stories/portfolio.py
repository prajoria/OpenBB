"""Portfolio Intelligence Terminal story — 16 steps mapped to NB01-NB08.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §6.1
Preview guide: docs/browser_test_harness/preview_guides/portfolio-manual-guide-preview.md
"""

from __future__ import annotations

from ..steps import ActionKind, Persona, Step, Story

_STEPS: tuple[Step, ...] = (
    # ==================================================================
    # Act 0 — Provider Health (W0) — NB01
    # ==================================================================
    Step(
        id="W0.provider-health",
        story="portfolio",
        notebook_ref="notebooks/portfolio/01-getting-started-and-providers.ipynb",
        persona=Persona.ANALYST,
        tab_id="overview",
        action=ActionKind.OBSERVE,
        human_title="Step W0 — Look at the provider health strip",
        human_description=(
            "Every tab of the terminal has a provider-health chrome strip at "
            "the top showing the 5-tier data-sourcing chain (Track A paid, "
            "Track B free)."
        ),
        human_expected=(
            "Two rows of tier-status badges: 'Track A (paid): fmp_cached / "
            "fmp / cboe / sec / yfinance-snap' and 'Track B (free): cboe / "
            "sec / yfinance', each tier tagged healthy / degraded / down."
        ),
        endpoint="pi/health/providers",
    ),
    # ==================================================================
    # Act 1 — Symbol Deep-Dive (W1) — NB02
    # ==================================================================
    Step(
        id="W1.symbol-header",
        story="portfolio",
        notebook_ref="notebooks/portfolio/02-single-name-deep-dive.ipynb",
        persona=Persona.ANALYST,
        tab_id="overview",
        action=ActionKind.OBSERVE,
        human_title="Step W1 — Read the profile header",
        human_description="Enter symbol=AAPL; read pi_equity_profile_header.",
        human_expected="Header shows Exchange, Sector/Industry, Price, Day Change.",
        endpoint="pi/equity/header",
        params={"symbol": "AAPL"},
    ),
    Step(
        id="W1.key-stats",
        story="portfolio",
        notebook_ref="notebooks/portfolio/02-single-name-deep-dive.ipynb",
        persona=Persona.ANALYST,
        tab_id="overview",
        action=ActionKind.OBSERVE,
        human_title="Step W1 — Read the Key Stats table",
        human_description="Read pi_equity_key_stats for the ticker on the Overview tab.",
        human_expected=(
            "Table with Market Cap, P/E (TTM), Forward P/E, EV/EBITDA, "
            "P/S (TTM), Short Interest, Insider Ownership rows."
        ),
        endpoint="pi/equity/key-stats",
        params={"symbol": "AAPL"},
    ),
    # ==================================================================
    # Act 2 — Financials (W2)
    # ==================================================================
    Step(
        id="W2.financials",
        story="portfolio",
        notebook_ref="notebooks/portfolio/02-single-name-deep-dive.ipynb",
        persona=Persona.ANALYST,
        tab_id="financials",
        action=ActionKind.OBSERVE,
        human_title="Step W2 — Read Financial Statements (annual)",
        human_description="On the Financials tab, verify period=annual returns 9 line items.",
        human_expected=(
            "9 rows: Revenue, Gross Profit, Operating Income, Net Income, "
            "Total Assets, Total Debt, Cash & Equivalents, OCF, FCF."
        ),
        endpoint="pi/equity/statements",
        params={"symbol": "AAPL", "period": "annual"},
    ),
    # ==================================================================
    # Act 3 — X-Ray composition (W3) — NB03
    # ==================================================================
    Step(
        id="W3.xray-sector",
        story="portfolio",
        notebook_ref="notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        persona=Persona.PM,
        tab_id="xray",
        action=ActionKind.OBSERVE,
        human_title="Step W3 — Sector composition pie",
        human_description="Read pi_xray_sector on the X-Ray tab.",
        human_expected="6 sector rows totaling ~1.0; Information Technology ~0.38.",
        endpoint="pi/xray/sector",
        params={"account_id": "demo"},
    ),
    Step(
        id="W3.xray-country",
        story="portfolio",
        notebook_ref="notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        persona=Persona.PM,
        tab_id="xray",
        action=ActionKind.OBSERVE,
        human_title="Step W3 — Country composition pie",
        human_description="Read pi_xray_country on the X-Ray tab.",
        human_expected="6 country rows; United States ~0.72.",
        endpoint="pi/xray/country",
        params={"account_id": "demo"},
    ),
    Step(
        id="W3.concentration",
        story="portfolio",
        notebook_ref="notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        persona=Persona.PM,
        tab_id="xray",
        action=ActionKind.OBSERVE,
        human_title="Step W3 — Concentration gauge (HHI)",
        human_description="Read pi_concentration_gauge.",
        human_expected="HHI metric between 0 and 1; demo value ~0.26.",
        endpoint="pi/concentration",
        params={"account_id": "demo"},
    ),
    # ==================================================================
    # Act 4 — Risk & Attribution (W4) — NB03/NB05
    # ==================================================================
    Step(
        id="W4.risk-dashboard",
        story="portfolio",
        notebook_ref="notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        persona=Persona.PM,
        tab_id="risk",
        action=ActionKind.OBSERVE,
        human_title="Step W4 — Read the risk dashboard",
        human_description="Read pi_risk_dashboard.",
        human_expected=(
            "vol_annualized, var_95_1d, beta_spy numeric values present, note "
            "field = 'demo book'."
        ),
        endpoint="pi/risk/dashboard",
        params={"account_id": "demo"},
    ),
    Step(
        id="W4.brinson",
        story="portfolio",
        notebook_ref="notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        persona=Persona.PM,
        tab_id="risk",
        action=ActionKind.OBSERVE,
        human_title="Step W4 — Brinson attribution waterfall",
        human_description="Read pi_brinson_attribution.",
        human_expected="Sector rows with allocation, selection, interaction, total.",
        endpoint="pi/attribution",
        params={"window": "1Y", "benchmark_symbol": "SPY"},
    ),
    # ==================================================================
    # Act 5 — Events & Alerts (W5) — NB04
    # ==================================================================
    Step(
        id="W5.calendar",
        story="portfolio",
        notebook_ref="notebooks/portfolio/04-events-and-smart-money.ipynb",
        persona=Persona.PM,
        tab_id="calendar",
        action=ActionKind.OBSERVE,
        human_title="Step W5 — Read the event calendar",
        human_description="Read pi_event_calendar on the Calendar tab.",
        human_expected="5+ rows covering earnings, ex_dividend, form_8k events.",
        endpoint="pi/events/calendar",
        params={"account_id": "demo", "horizon_days": "30"},
    ),
    Step(
        id="W5.alerts",
        story="portfolio",
        notebook_ref="notebooks/portfolio/04-events-and-smart-money.ipynb",
        persona=Persona.PM,
        tab_id="alerts",
        action=ActionKind.OBSERVE,
        human_title="Step W5 — Read the alerts panel",
        human_description="Read pi_alerts_panel on the Alerts tab.",
        human_expected="At least one alert row present.",
        endpoint="pi/alerts",
        params={"account_id": "demo"},
    ),
    # ==================================================================
    # Act 6 — Paper Trading (W6) — NB05
    # ==================================================================
    Step(
        id="W6.paper-kpis",
        story="portfolio",
        notebook_ref="notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        persona=Persona.PM,
        tab_id="paper",
        action=ActionKind.OBSERVE,
        human_title="Step W6 — Read the paper account KPIs",
        human_description="Read pi_paper_perf_kpis on the Paper Trading tab.",
        human_expected="Total return, Sharpe, max drawdown numeric values.",
        endpoint="pi/paper/perf-kpis",
        params={"account_id": "demo"},
    ),
    # ==================================================================
    # Act 7 — What-If (W7) — NB05
    # ==================================================================
    Step(
        id="W7.whatif",
        story="portfolio",
        notebook_ref="notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        persona=Persona.PM,
        tab_id="risk",
        action=ActionKind.INPUT,
        human_title="Step W7 — Try a hypothetical BUY",
        human_description="Set delta_shares=100 on AAPL in pi_whatif_diff.",
        human_expected="Markdown body labeled BUY AAPL x 100 with position deltas.",
        endpoint="pi/whatif",
        params={"symbol": "AAPL", "delta_shares": "100"},
    ),
    # ==================================================================
    # Act 8 — Morning Review (W8) — NB06/07
    # ==================================================================
    Step(
        id="W8.morning-review",
        story="portfolio",
        notebook_ref="notebooks/portfolio/07-offline-recording-and-end-to-end.ipynb",
        persona=Persona.PM,
        tab_id="morning-review",
        action=ActionKind.NAVIGATE,
        human_title="Step W8 — Load the Morning Review composed one-pager",
        human_description=(
            "Navigate to the Morning Review tab. It composes 5 REUSE widgets: "
            "concentration + risk dashboard + paper KPIs + event calendar + "
            "alerts panel."
        ),
        human_expected=(
            "All 5 widgets visible on one page. No blank slots. "
            "The apps.json layout is what B4's expected_layouts fixture validates."
        ),
        endpoint=None,  # NAVIGATE-only, no endpoint hit
        tags=("navigation",),
    ),
    # ==================================================================
    # Act 9 — Basket Analyst Consensus (W9) — NB08
    # ==================================================================
    Step(
        id="W9.basket-consensus",
        story="portfolio",
        notebook_ref="notebooks/portfolio/08-analyst-recommendations-basket.ipynb",
        persona=Persona.ANALYST,
        tab_id="estimates",
        action=ActionKind.OBSERVE,
        human_title="Step W9 — Read the demo basket consensus",
        human_description="Read pi_basket_analyst_consensus with basket_id=demo.",
        human_expected=(
            "5 rows (AAPL, MSFT, GOOGL, NVDA, META) with avg_target, buy, "
            "hold, sell, consensus fields."
        ),
        endpoint="pi/equity/basket-analyst-consensus",
        params={"basket_id": "demo"},
    ),
    Step(
        id="W9.basket-guard",
        story="portfolio",
        notebook_ref="notebooks/portfolio/08-analyst-recommendations-basket.ipynb",
        persona=Persona.ANALYST,
        tab_id="estimates",
        action=ActionKind.ASSERT,
        human_title="Step W9 — Verify basket safety invariant",
        human_description=(
            "Try basket_id=real_book. The endpoint MUST return 422 with a "
            "pointer to follow-up #1714, NOT demo rows disguised with a "
            "marker note."
        ),
        human_expected=(
            "HTTP 422 with detail 'basket_input_wiring_deferred' and "
            "follow_up = '#1714'. This is the load-bearing safety invariant "
            "codified in test_non_demo_basket_id_returns_422."
        ),
        endpoint="pi/equity/basket-analyst-consensus",
        params={"basket_id": "real_book"},
        expected_status=422,
        tags=("safety", "checker:non-demo-basket-is-422"),
    ),
)


# ==================================================================
# Widget-completeness coverage (B8, #1733)
# ==================================================================
# One step per widget in widgets.json that isn't already exercised by the
# W0-W9 narrative spine. Kept as a distinct tuple so the story's narrative
# ordering (act by act) stays reviewable — the coverage steps live in a
# labelled batch at the end and use CX.NN ids so they're visually distinct
# from the W steps.
#
# Every step:
# - Uses the widget's default params from widgets.json (so it exercises the
#   real happy path a user hits on first render)
# - Anchors to the notebook that introduced the widget
# - Has action=ActionKind.OBSERVE (widget-completeness, not safety-invariant)


def _coverage(
    step_id: str,
    tab_id: str,
    endpoint: str,
    params: dict[str, str],
    notebook_ref: str,
    persona: Persona,
    human_title: str,
    human_expected: str,
) -> Step:
    """Compact helper — most coverage steps have similar boilerplate."""
    return Step(
        id=step_id,
        story="portfolio",
        notebook_ref=notebook_ref,
        persona=persona,
        tab_id=tab_id,
        action=ActionKind.OBSERVE,
        human_title=human_title,
        human_description=(
            "Widget-completeness coverage step (B8 #1733). Confirms the "
            "widget's default endpoint responds with the expected shape."
        ),
        human_expected=human_expected,
        endpoint=endpoint,
        params=params,
        tags=("coverage",),
    )


_COVERAGE_STEPS: tuple[Step, ...] = (
    # --- Chrome ---
    _coverage(
        "CX.symbol-context",
        "overview",
        "pi/context/symbol",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_symbol_context chrome bar",
        "Markdown badge echoing the ticker (AAPL).",
    ),
    _coverage(
        "CX.book-context",
        "xray",
        "pi/context/book",
        {"account_id": "demo"},
        "notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        Persona.PM,
        "Coverage — pi_book_context chrome bar",
        "Markdown badge echoing the account (demo).",
    ),
    # --- F1 Overview extras ---
    _coverage(
        "CX.equity-financial-charts",
        "financials",
        "pi/equity/financials",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_equity_financial_charts",
        "Chart rows for 5-yr revenue + net income + margin.",
    ),
    _coverage(
        "CX.equity-technicals",
        "technicals",
        "pi/equity/technicals",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_equity_technicals",
        "Consensus + pivot matrix rows.",
    ),
    _coverage(
        "CX.equity-analyst-forecasts",
        "estimates",
        "pi/equity/analyst-forecasts",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_equity_analyst_forecasts",
        "Analyst rating distribution + surprise history rows.",
    ),
    _coverage(
        "CX.equity-complementary",
        "comparison",
        "pi/equity/complementary",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_equity_complementary",
        "Top ETFs holding the ticker + bond ladder rows.",
    ),
    _coverage(
        "CX.equity-competitors",
        "comparison",
        "pi/equity/competitors",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_equity_competitors",
        "Regional industry competitors with live price rows.",
    ),
    _coverage(
        "CX.equity-price-history",
        "overview",
        "pi/equity/price-history",
        {"symbol": "AAPL", "chart_type": "line"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_equity_price_history (line mode)",
        "OHLC rows with date+close in line-chart mode.",
    ),
    _coverage(
        "CX.charting",
        "technicals",
        "pi/equity/charting",
        {"symbol": "AAPL", "window": "3M"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_charting (3M window)",
        "OHLC + SMA20/SMA50/RSI14 overlays.",
    ),
    # --- F5 Ownership ---
    _coverage(
        "CX.institutional-ownership",
        "ownership",
        "pi/equity/institutional-ownership",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.PM,
        "Coverage — pi_institutional_ownership (13F holders)",
        "Top holder rows with shares and pct_owned.",
    ),
    _coverage(
        "CX.stock-ownership",
        "ownership",
        "pi/equity/stock-ownership",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.PM,
        "Coverage — pi_stock_ownership (bucket pie)",
        "Ownership bucket rows (Institutions/Retail/ETFs/Insiders).",
    ),
    _coverage(
        "CX.insider-trading",
        "ownership",
        "pi/equity/insider-trading",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.PM,
        "Coverage — pi_insider_trading",
        "Recent insider Form 4 transaction rows.",
    ),
    # --- F6 Calendar ---
    _coverage(
        "CX.earnings-history",
        "calendar",
        "pi/equity/earnings-history",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.ANALYST,
        "Coverage — pi_earnings_history",
        "Historical EPS actual vs. estimate rows with surprise%.",
    ),
    _coverage(
        "CX.stock-splits",
        "calendar",
        "pi/equity/stock-splits",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.ANALYST,
        "Coverage — pi_stock_splits",
        "Historical stock-split event rows.",
    ),
    _coverage(
        "CX.dividend-payment",
        "calendar",
        "pi/equity/dividend-payment",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.ANALYST,
        "Coverage — pi_dividend_payment",
        "Recent dividend rows: ex-date, payment date, amount.",
    ),
    _coverage(
        "CX.company-filings",
        "calendar",
        "pi/equity/company-filings",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.ANALYST,
        "Coverage — pi_company_filings",
        "Recent 10-K/10-Q/8-K filing rows.",
    ),
    _coverage(
        "CX.earnings-transcripts",
        "calendar",
        "pi/equity/earnings-transcripts",
        {"symbol": "AAPL"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.ANALYST,
        "Coverage — pi_earnings_transcripts",
        "Markdown preview of latest earnings call transcript.",
    ),
    # --- F1B builds ---
    _coverage(
        "CX.management-team",
        "overview",
        "pi/equity/management-team",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_management_team",
        "Key executives: name/title/pay/tenure rows.",
    ),
    _coverage(
        "CX.revenue-geography",
        "overview",
        "pi/equity/revenue-geography",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_revenue_geography (pie)",
        "Region/revenue rows totaling ~total revenue.",
    ),
    _coverage(
        "CX.revenue-business-line",
        "overview",
        "pi/equity/revenue-business-line",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_revenue_business_line (pie)",
        "Segment/revenue rows totaling ~total revenue.",
    ),
    _coverage(
        "CX.price-performance",
        "overview",
        "pi/equity/price-performance",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_price_performance",
        "9 horizon return rows (1D/1W/1M/3M/6M/YTD/1Y/3Y/5Y).",
    ),
    _coverage(
        "CX.peer-multiples",
        "comparison",
        "pi/equity/peer-multiples",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_peer_multiples",
        "Symbol + peers with P/E TTM, forward P/E, EV/EBITDA, P/S.",
    ),
    _coverage(
        "CX.price-target-history",
        "estimates",
        "pi/equity/price-target-history",
        {"symbol": "AAPL"},
        "notebooks/portfolio/02-single-name-deep-dive.ipynb",
        Persona.ANALYST,
        "Coverage — pi_price_target_history",
        "Target-vs-close time series rows.",
    ),
    # --- F8 X-Ray extras ---
    _coverage(
        "CX.lookthrough-top25",
        "xray",
        "pi/lookthrough/top25",
        {"account_id": "demo"},
        "notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        Persona.PM,
        "Coverage — pi_lookthrough_top25",
        "Top-25 effective holdings after ETF look-through.",
    ),
    # --- F9 Risk extras ---
    _coverage(
        "CX.risk-vol-chart",
        "risk",
        "pi/risk/vol",
        {"account_id": "demo"},
        "notebooks/portfolio/03-basket-xray-and-risk.ipynb",
        Persona.PM,
        "Coverage — pi_risk_vol_chart",
        "20d/60d rolling realized volatility rows.",
    ),
    _coverage(
        "CX.whatif-card",
        "risk",
        "pi/whatif/card",
        {"symbol": "AAPL", "delta_shares": "100"},
        "notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        Persona.PM,
        "Coverage — pi_whatif_card (structured diff)",
        "Structured before/after exposure diff rows.",
    ),
    # --- F10 Paper Trading ---
    _coverage(
        "CX.paper-ticket",
        "paper",
        "pi/paper/ticket",
        {
            "account_id": "demo",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": "100",
            "confirm": "false",
        },
        "notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        Persona.PM,
        "Coverage — pi_paper_ticket (preview)",
        "Markdown ticket preview (confirm=false).",
    ),
    _coverage(
        "CX.paper-blotter",
        "paper",
        "pi/paper/blotter",
        {"account_id": "demo"},
        "notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        Persona.PM,
        "Coverage — pi_paper_blotter",
        "Recent paper order rows with status.",
    ),
    _coverage(
        "CX.paper-performance",
        "paper",
        "pi/paper/performance",
        {"account_id": "demo"},
        "notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
        Persona.PM,
        "Coverage — pi_paper_performance",
        "Paper account equity-curve rows.",
    ),
    _coverage(
        "CX.backtest-button",
        "paper",
        "pi/backtest/oneclick",
        {"account_id": "demo"},
        "notebooks/portfolio/06-backtest-and-validation.ipynb",
        Persona.PM,
        "Coverage — pi_backtest_button",
        "Markdown widget kicking off one-click backtest.",
    ),
    # --- F11 Alerts extras ---
    _coverage(
        "CX.smart-money-ribbon",
        "alerts",
        "pi/smart-money/ribbon",
        {"account_id": "demo"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.PM,
        "Coverage — pi_smart_money_ribbon",
        "Insider + institutional move rows for held names.",
    ),
    _coverage(
        "CX.news-ribbon",
        "alerts",
        "pi/news",
        {"account_id": "demo", "horizon_days": "7"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.PM,
        "Coverage — pi_news_ribbon",
        "Recent material news rows for held symbols.",
    ),
    _coverage(
        "CX.sentiment-gauge",
        "alerts",
        "pi/sentiment",
        {"account_id": "demo"},
        "notebooks/portfolio/04-events-and-smart-money.ipynb",
        Persona.PM,
        "Coverage — pi_sentiment_gauge",
        "Aggregate sentiment metric value.",
    ),
)

# Merged story steps: narrative spine + widget-completeness coverage.
_NARRATIVE_STEPS: tuple[Step, ...] = _STEPS + _COVERAGE_STEPS


# ==================================================================
# B9 #1734 — Deep invariant sweep
#
# Each step ASSERTs a load-bearing safety invariant of the backend:
#   * XSS-reject       — symbol / basket params reject shell/HTML metachars
#   * Enum-reject      — side / verdict params reject values outside the
#                        allowed set
#   * Range-reject     — horizon_days is bounded 1..365 (news 1..90)
#   * Type-reject      — quantity / delta_shares / horizon must be ints
#   * Loud-empty guard — basket_id != "demo" is a 422 (spec §5.6 — the
#                        gate that prevents silent all-zero what-if
#                        payloads reaching downstream widgets)
#
# The load-bearing test is `expected_status=400` (or 422). A mutation that
# removed the guard would return 200 with a bogus body, and every step
# below would fail the harness — this is R7.11 reverse verification at
# the harness layer.
# ==================================================================


def _reject(
    step_id: str,
    tab_id: str,
    endpoint: str,
    params: dict,
    invariant_tag: str,
    what: str,
    persona: Persona = Persona.ANALYST,
    notebook_ref: str = (
        "notebooks/portfolio/01-getting-started-and-providers.ipynb"
    ),
    expected_status: int = 400,
) -> Step:
    """Build an ASSERT step that expects a rejection status code."""
    return Step(
        id=step_id,
        story="portfolio",
        notebook_ref=notebook_ref,
        persona=persona,
        tab_id=tab_id,
        action=ActionKind.ASSERT,
        human_title=f"Invariant — {what}",
        human_description=(
            f"Deep invariant sweep (B9 #1734). {what}. If the guard is "
            "removed by a future change, the harness fails at PR time."
        ),
        human_expected=f"HTTP {expected_status} rejection.",
        endpoint=endpoint,
        params=params,
        expected_status=expected_status,
        tags=("safety", f"checker:{invariant_tag}"),
    )


_INVARIANT_STEPS: tuple[Step, ...] = (
    # -------------------------------------------------------------------
    # XSS-reject: symbol regex is ^[A-Z0-9.\-]{1,10}$
    # (widget_backend/_shared.py:54 _SYMBOL_RE)
    # -------------------------------------------------------------------
    _reject(
        "IV.symbol-xss-script-tag",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "<script>alert(1)</script>"},
        invariant_tag="symbol-rejects-html-tags",
        what="symbol param rejects <script> tag",
    ),
    _reject(
        "IV.symbol-xss-sql-injection",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "'; DROP TABLE users;--"},
        invariant_tag="symbol-rejects-sql-metachars",
        what="symbol param rejects SQL metacharacters",
    ),
    _reject(
        "IV.symbol-xss-shell-metachars",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "AAPL|rm -rf /"},
        invariant_tag="symbol-rejects-shell-pipe",
        what="symbol param rejects shell pipe metacharacter",
    ),
    _reject(
        "IV.symbol-xss-null-byte",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "AAPL\x00.evil"},
        invariant_tag="symbol-rejects-null-byte",
        what="symbol param rejects NUL byte",
    ),
    _reject(
        "IV.symbol-xss-path-traversal",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "../../etc/passwd"},
        invariant_tag="symbol-rejects-path-traversal",
        what="symbol param rejects path-traversal sequence",
    ),
    _reject(
        "IV.symbol-xss-lowercase-not-normalized-through-attack",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "aapl<img src=x onerror=1>"},
        invariant_tag="symbol-rejects-html-after-lowercase-mixed",
        what="mixed-case with HTML injection still rejected",
    ),
    _reject(
        "IV.symbol-too-long",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": "A" * 11},  # regex caps at 10
        invariant_tag="symbol-rejects-oversize",
        what="symbol >10 chars rejected (prevents runaway lookups)",
    ),
    _reject(
        "IV.symbol-empty",
        tab_id="overview",
        endpoint="pi/equity/header",
        params={"symbol": ""},
        invariant_tag="symbol-rejects-empty",
        what="symbol='' rejected",
    ),
    # -------------------------------------------------------------------
    # Paper ticket: side must be buy|sell, quantity must be positive int
    # -------------------------------------------------------------------
    _reject(
        "IV.paper-ticket-side-invalid",
        tab_id="paper-trading",
        endpoint="pi/paper/ticket",
        params={"symbol": "AAPL", "side": "long", "quantity": "10"},
        invariant_tag="paper-side-enum",
        what="paper ticket side must be 'buy' or 'sell'",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    _reject(
        "IV.paper-ticket-side-xss",
        tab_id="paper-trading",
        endpoint="pi/paper/ticket",
        params={"symbol": "AAPL", "side": "<script>", "quantity": "10"},
        invariant_tag="paper-side-rejects-html",
        what="paper ticket side rejects HTML tag",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    _reject(
        "IV.paper-ticket-quantity-not-int",
        tab_id="paper-trading",
        endpoint="pi/paper/ticket",
        params={"symbol": "AAPL", "side": "buy", "quantity": "3.14"},
        invariant_tag="paper-qty-int",
        what="paper ticket quantity must be int",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    _reject(
        "IV.paper-ticket-quantity-negative",
        tab_id="paper-trading",
        endpoint="pi/paper/ticket",
        params={"symbol": "AAPL", "side": "buy", "quantity": "-5"},
        invariant_tag="paper-qty-positive",
        what="paper ticket quantity must be positive",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    _reject(
        "IV.paper-ticket-quantity-zero",
        tab_id="paper-trading",
        endpoint="pi/paper/ticket",
        params={"symbol": "AAPL", "side": "buy", "quantity": "0"},
        invariant_tag="paper-qty-nonzero",
        what="paper ticket quantity=0 rejected",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    _reject(
        "IV.paper-ticket-quantity-symbol-xss",
        tab_id="paper-trading",
        endpoint="pi/paper/ticket",
        params={"symbol": "<b>AAPL</b>", "side": "buy", "quantity": "10"},
        invariant_tag="paper-symbol-rejects-html",
        what="paper ticket symbol rejects HTML tags",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    # -------------------------------------------------------------------
    # What-if: delta_shares must be int, symbol regex enforced
    # -------------------------------------------------------------------
    _reject(
        "IV.whatif-delta-not-int",
        tab_id="whatif",
        endpoint="pi/whatif",
        params={"symbol": "AAPL", "delta_shares": "1.5"},
        invariant_tag="whatif-delta-int",
        what=(
            "what-if returns a graceful markdown 'invalid input' body when "
            "delta_shares is not an int (widget-friendly, no raw 400)"
        ),
        expected_status=200,
        notebook_ref="notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
    ),
    _reject(
        "IV.whatif-symbol-xss",
        tab_id="whatif",
        endpoint="pi/whatif",
        params={"symbol": "<script>", "delta_shares": "10"},
        invariant_tag="whatif-symbol-rejects-html",
        what="what-if symbol rejects HTML",
        notebook_ref="notebooks/portfolio/05-whatif-attribution-and-paper.ipynb",
    ),
    # -------------------------------------------------------------------
    # Horizon params: 1..365 for events, 1..90 for news (widgets_endpoints.py
    # :170-176, :502-508)
    # -------------------------------------------------------------------
    _reject(
        "IV.events-horizon-zero",
        tab_id="calendar",
        endpoint="pi/events/calendar",
        params={"horizon_days": "0"},
        invariant_tag="events-horizon-min",
        what="events horizon_days=0 rejected",
        notebook_ref="notebooks/portfolio/06-events-and-smart-money.ipynb",
    ),
    _reject(
        "IV.events-horizon-too-big",
        tab_id="calendar",
        endpoint="pi/events/calendar",
        params={"horizon_days": "366"},
        invariant_tag="events-horizon-max",
        what="events horizon_days>365 rejected",
        notebook_ref="notebooks/portfolio/06-events-and-smart-money.ipynb",
    ),
    _reject(
        "IV.events-horizon-not-int",
        tab_id="calendar",
        endpoint="pi/events/calendar",
        params={"horizon_days": "abc"},
        invariant_tag="events-horizon-int",
        what="events horizon_days must parse as int",
        notebook_ref="notebooks/portfolio/06-events-and-smart-money.ipynb",
    ),
    _reject(
        "IV.events-horizon-xss",
        tab_id="calendar",
        endpoint="pi/events/calendar",
        params={"horizon_days": "<script>alert(1)</script>"},
        invariant_tag="events-horizon-rejects-html",
        what="events horizon_days rejects HTML string",
        notebook_ref="notebooks/portfolio/06-events-and-smart-money.ipynb",
    ),
    _reject(
        "IV.news-horizon-too-big",
        tab_id="alerts",
        endpoint="pi/news",
        params={"horizon_days": "91"},
        invariant_tag="news-horizon-max",
        what="news horizon_days>90 rejected",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    _reject(
        "IV.news-horizon-zero",
        tab_id="alerts",
        endpoint="pi/news",
        params={"horizon_days": "0"},
        invariant_tag="news-horizon-min",
        what="news horizon_days=0 rejected",
        notebook_ref="notebooks/portfolio/07-paper-and-alerts.ipynb",
    ),
    # -------------------------------------------------------------------
    # basket-analyst-consensus: only "demo" basket returns data;
    # everything else is 422 (widgets_endpoints.py:1758-1761)
    # This is the anti-silent-empty gate: the widget MUST NOT return an
    # empty consensus for an unknown basket — it must loudly 422.
    # -------------------------------------------------------------------
    _reject(
        "IV.basket-consensus-non-demo-loud-422",
        tab_id="basket",
        endpoint="pi/equity/basket-analyst-consensus",
        params={"basket_id": "my_book"},
        invariant_tag="basket-non-demo-is-422",
        what=(
            "basket-analyst-consensus returns 422 for non-demo basket "
            "(loud-empty gate, not silent all-zero)"
        ),
        expected_status=422,
        notebook_ref="notebooks/portfolio/04-basket-analyst-consensus.ipynb",
    ),
    _reject(
        "IV.basket-consensus-xss",
        tab_id="basket",
        endpoint="pi/equity/basket-analyst-consensus",
        params={"basket_id": "<script>alert(1)</script>"},
        invariant_tag="basket-rejects-html",
        what="basket-analyst-consensus rejects HTML basket_id",
        expected_status=400,
        notebook_ref="notebooks/portfolio/04-basket-analyst-consensus.ipynb",
    ),
    # -------------------------------------------------------------------
    # Cross-endpoint XSS sample — spot-check a handful of the other
    # symbol-taking endpoints so a change to one route can't accidentally
    # sidestep the symbol guard.
    # -------------------------------------------------------------------
    _reject(
        "IV.charting-symbol-xss",
        tab_id="chart",
        endpoint="pi/equity/charting",
        params={"symbol": "<img src=x>"},
        invariant_tag="charting-rejects-html",
        what="charting symbol rejects HTML img tag",
        notebook_ref="notebooks/portfolio/02-single-name-deep-dive.ipynb",
    ),
    _reject(
        "IV.competitors-symbol-xss",
        tab_id="comparison",
        endpoint="pi/equity/competitors",
        params={"symbol": "javascript:alert(1)"},
        invariant_tag="competitors-rejects-javascript-uri",
        what="competitors symbol rejects javascript: URI",
        notebook_ref="notebooks/portfolio/02-single-name-deep-dive.ipynb",
    ),
    _reject(
        "IV.insider-trading-symbol-xss",
        tab_id="ownership",
        endpoint="pi/equity/insider-trading",
        params={"symbol": "A\"'>onload=1"},
        invariant_tag="insider-trading-rejects-attr-inject",
        what="insider-trading symbol rejects attribute-injection payload",
        notebook_ref="notebooks/portfolio/06-events-and-smart-money.ipynb",
    ),
    _reject(
        "IV.symbol-context-xss",
        tab_id="chrome",
        endpoint="pi/context/symbol",
        params={"symbol": "AAPL\r\nX-Injected: yes"},
        invariant_tag="context-symbol-rejects-crlf",
        what="context symbol rejects CRLF header-injection payload",
    ),
)


_ALL_STEPS: tuple[Step, ...] = _NARRATIVE_STEPS + _INVARIANT_STEPS


STORY = Story(
    id="portfolio",
    title="Portfolio Intelligence Terminal (W0-W9 + widget-completeness + invariants)",
    notebook_series_root="notebooks/portfolio/",
    steps=_ALL_STEPS,
)
