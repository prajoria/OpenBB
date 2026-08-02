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

STORY = Story(
    id="portfolio",
    title="Portfolio Intelligence Terminal (W0-W9)",
    notebook_series_root="notebooks/portfolio/",
    steps=_STEPS,
)
