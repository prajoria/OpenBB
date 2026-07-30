"""Shared HTML rendering toolkit for the Portfolio Intelligence Engine notebooks.

One consistent look for EVERY section's *output* (not just its markdown).
The goal: running any notebook top-to-bottom produces a fully readable,
self-explaining report whose result panels cross-link to authoritative
external references.

Design rule for links: we link ONLY to STABLE external sources — Investopedia
term pages, canonical docs — and NEVER to sibling notebooks or in-notebook
cell anchors. Cell anchors and notebook filenames drift every time the code
is reorganized; an Investopedia term URL is stable for years. So the output
stays correct even after a notebook is refactored.

This module is the shared home of the rendering conventions first developed
inline in ``02-single-name-deep-dive.ipynb`` (NB02). The other notebooks
import from here instead of duplicating ~270 lines each:

    import sys; sys.path.insert(0, ".")
    from _nb_render import nb_pill, nb_table, nb_panel, nb_render_phase, NB_LINKS

Public API:
    nb_pill(text, tone)                 — small coloured status badge
    nb_table(headers, rows)             — header + rows table (cells may hold HTML)
    nb_panel(title, body_html, ...)     — the single titled-panel look
    nb_render_phase(obj, num, name, ...) — render a PhaseNResult as a panel
    NB_LINKS                            — curated {slug: (label, url)} references

Colour language (tone=):
    good    PASS / Buy      (green)
    bad     FAIL / Avoid    (red)
    warn    caution         (amber)
    neutral                 (gray)
    accent                  (blue)
"""

import html as _html
import math as _math

from IPython.display import HTML, display

# --- shared palette (matches the 7-phase card grid) ----------------------
_NB_ACCENT = "#7aa2f7"
_NB_GREEN = ("#16a34a", "rgba(34,197,94,.16)")
_NB_RED = ("#dc2626", "rgba(239,68,68,.16)")
_NB_AMBER = ("#d97706", "rgba(245,158,11,.18)")
_NB_GRAY = ("#6b7280", "rgba(127,127,127,.16)")
_NB_BLUE = (_NB_ACCENT, "rgba(122,162,247,.16)")
_NB_TONES = {"good": _NB_GREEN, "bad": _NB_RED, "warn": _NB_AMBER,
             "neutral": _NB_GRAY, "accent": _NB_BLUE}

# --- curated, STABLE external references (Investopedia term pages) --------
# Keyed by short slug; each is (label, url). Reused across every section so
# the same concept always links to the same authoritative page.
NB_LINKS = {
    # NB02 single-name deep-dive vocabulary
    "fundamental":  ("Fundamental analysis", "https://www.investopedia.com/terms/f/fundamentalanalysis.asp"),
    "technical":    ("Technical analysis", "https://www.investopedia.com/terms/t/technicalanalysis.asp"),
    "market_cap":   ("Market capitalization", "https://www.investopedia.com/terms/m/marketcapitalization.asp"),
    "shares_out":   ("Shares outstanding", "https://www.investopedia.com/terms/o/outstandingshares.asp"),
    "inst_own":     ("Institutional ownership", "https://www.investopedia.com/terms/i/institutionalownership.asp"),
    "peer_group":   ("Peer group", "https://www.investopedia.com/terms/p/peer-group.asp"),
    "owner_earn":   ("Owner's earnings", "https://www.investopedia.com/terms/o/ownersearnings.asp"),
    "roic":         ("ROIC", "https://www.investopedia.com/terms/r/returnoninvestmentcapital.asp"),
    "roe":          ("ROE", "https://www.investopedia.com/terms/r/returnonequity.asp"),
    "gross_profit": ("Gross profitability", "https://www.investopedia.com/terms/g/gross_profit_margin.asp"),
    "accruals":     ("Accruals / earnings quality", "https://www.investopedia.com/terms/a/accrualaccounting.asp"),
    "piotroski":    ("Piotroski F-score", "https://www.investopedia.com/terms/p/piotroski-score.asp"),
    "altman":       ("Altman Z-score", "https://www.investopedia.com/terms/a/altman.asp"),
    "atr":          ("Average True Range (ATR)", "https://www.investopedia.com/terms/a/atr.asp"),
    "stop_loss":    ("Stop-loss order", "https://www.investopedia.com/terms/s/stop-lossorder.asp"),
    "trailing_stop": ("Trailing stop", "https://www.investopedia.com/terms/t/trailingstop.asp"),
    "dcf":          ("Discounted cash flow (DCF)", "https://www.investopedia.com/terms/d/dcf.asp"),
    "margin_safety": ("Margin of safety", "https://www.investopedia.com/terms/m/marginofsafety.asp"),
    "ev_ebitda":    ("EV / EBITDA", "https://www.investopedia.com/terms/e/ev-ebitda.asp"),
    "price_target": ("Analyst price target", "https://www.investopedia.com/terms/p/pricetarget.asp"),
    "sharpe":       ("Sharpe ratio", "https://www.investopedia.com/terms/s/sharperatio.asp"),
    "max_dd":       ("Maximum drawdown", "https://www.investopedia.com/terms/m/maximum-drawdown-mdd.asp"),
    "beta":         ("Beta", "https://www.investopedia.com/terms/b/beta.asp"),
    "cvar":         ("Conditional VaR (CVaR)", "https://www.investopedia.com/terms/c/conditional_value_at_risk.asp"),
    "kelly":        ("Position sizing / Kelly", "https://www.investopedia.com/terms/p/positionsizing.asp"),
    "info_ratio":   ("Information ratio", "https://www.investopedia.com/terms/i/informationratio.asp"),
    "rel_strength": ("Relative strength", "https://www.investopedia.com/terms/r/relativestrength.asp"),
    "sector_rot":   ("Sector rotation", "https://www.investopedia.com/terms/s/sector-rotation.asp"),
    "composite":    ("Weighted (composite) score", "https://www.investopedia.com/terms/w/weightedaverage.asp"),
    "trade_plan":   ("Trading plan", "https://www.investopedia.com/terms/t/trading-plan.asp"),
    "staged_entry": ("Scaling into a position", "https://www.investopedia.com/terms/s/scaling.asp"),
    "regime":       ("Risk-on / risk-off regime", "https://www.investopedia.com/terms/r/risk-on-risk-off.asp"),
    "pickle":       ("Python object serialization (pickle)", "https://docs.python.org/3/library/pickle.html"),
    "regression_test": ("Regression testing", "https://en.wikipedia.org/wiki/Regression_testing"),
    # NB03 basket x-ray + risk vocabulary
    "portfolio":    ("Portfolio", "https://www.investopedia.com/terms/p/portfolio.asp"),
    "position":     ("Position", "https://www.investopedia.com/terms/p/position.asp"),
    "weight":       ("Weighted average", "https://www.investopedia.com/terms/w/weighted.asp"),
    "diversification": ("Diversification", "https://www.investopedia.com/terms/d/diversification.asp"),
    "sector_breakdown": ("Sector breakdown", "https://www.investopedia.com/terms/s/sectorbreakdown.asp"),
    "look_through": ("Look-through", "https://www.investopedia.com/terms/l/look-through-earnings.asp"),
    "hhi":          ("Herfindahl-Hirschman Index", "https://www.investopedia.com/terms/h/hhi.asp"),
    "volatility":   ("Volatility", "https://www.investopedia.com/terms/v/volatility.asp"),
    "tracking_error": ("Tracking error", "https://www.investopedia.com/terms/t/trackingerror.asp"),
    "benchmark":    ("Benchmark", "https://www.investopedia.com/terms/b/benchmark.asp"),
    "risk_free":    ("Risk-free rate", "https://www.investopedia.com/terms/r/risk-freerate.asp"),
    "correlation":  ("Correlation", "https://www.investopedia.com/terms/c/correlation.asp"),
    # NB01 platform / provider vocabulary
    "market_data":  ("Market data", "https://www.investopedia.com/terms/m/marketdata.asp"),
    "cboe":         ("CBOE", "https://www.investopedia.com/terms/c/cboe.asp"),
    "edgar":        ("SEC EDGAR", "https://www.investopedia.com/terms/e/edgar.asp"),
    "basket":       ("Basket trade", "https://www.investopedia.com/terms/b/baskettrade.asp"),
    "api":          ("API", "https://en.wikipedia.org/wiki/API"),
    # NB04 events + smart-money vocabulary
    "earnings":     ("Earnings announcement", "https://www.investopedia.com/terms/e/earnings-announcement.asp"),
    "earnings_surprise": ("Earnings surprise", "https://www.investopedia.com/terms/e/earningssurprise.asp"),
    "ex_dividend":  ("Ex-dividend date", "https://www.investopedia.com/terms/e/ex-dividend.asp"),
    "reverse_split": ("Reverse split", "https://www.investopedia.com/terms/r/reversesplit.asp"),
    "form_13f":     ("Form 13F", "https://www.investopedia.com/terms/f/form-13f.asp"),
    "form_4":       ("Form 4", "https://www.investopedia.com/terms/f/form-4.asp"),
    "insider_trading": ("Insider trading", "https://www.investopedia.com/terms/i/insidertrading.asp"),
    "stock_act":    ("STOCK Act", "https://www.investopedia.com/terms/s/stock-act.asp"),
    "market_sentiment": ("Market sentiment", "https://www.investopedia.com/terms/m/marketsentiment.asp"),
    "event_driven": ("Event-driven", "https://www.investopedia.com/terms/e/eventdriven.asp"),
    "news":         ("Financial news", "https://www.investopedia.com/terms/n/news-trader.asp"),
    # NB05 what-if / attribution / paper-trading vocabulary
    "position_sizing": ("Position sizing", "https://www.investopedia.com/terms/p/positionsizing.asp"),
    "kelly_criterion": ("Kelly criterion", "https://www.investopedia.com/terms/k/kellycriterion.asp"),
    "risk_management": ("Risk management", "https://www.investopedia.com/terms/r/riskmanagement.asp"),
    "whatif":       ("What-if analysis", "https://www.investopedia.com/terms/w/what-if-calculation.asp"),
    "brinson":      ("Brinson attribution", "https://en.wikipedia.org/wiki/Performance_attribution"),
    "attribution":  ("Performance attribution", "https://www.investopedia.com/terms/a/attribution-analysis.asp"),
    "paper_trade":  ("Paper trade", "https://www.investopedia.com/terms/p/papertrade.asp"),
    "market_order": ("Market order", "https://www.investopedia.com/terms/m/marketorder.asp"),
    "limit_order":  ("Limit order", "https://www.investopedia.com/terms/l/limitorder.asp"),
    "tif":          ("Time in force (TIF)", "https://www.investopedia.com/terms/t/timeinforce.asp"),
    "gtc":          ("Good-'til-canceled (GTC)", "https://www.investopedia.com/terms/g/gtc.asp"),
    "realized_pnl": ("Realized P&L", "https://www.investopedia.com/terms/r/realizedprofit.asp"),
    "unrealized_pnl": ("Unrealized P&L", "https://www.investopedia.com/terms/u/unrealizedgain.asp"),
    "buying_power": ("Buying power", "https://www.investopedia.com/terms/b/buyingpower.asp"),
    "margin":       ("Margin", "https://www.investopedia.com/terms/m/margin.asp"),
    # NB06 backtest + validation vocabulary
    "backtest":     ("Backtesting", "https://www.investopedia.com/terms/b/backtesting.asp"),
    "buy_and_hold": ("Buy and hold", "https://www.investopedia.com/terms/b/buyandhold.asp"),
    "cagr":         ("CAGR", "https://www.investopedia.com/terms/c/cagr.asp"),
    "sortino":      ("Sortino ratio", "https://www.investopedia.com/terms/s/sortinoratio.asp"),
    "calmar":       ("Calmar ratio", "https://www.investopedia.com/terms/c/calmarratio.asp"),
    "equity_curve": ("Equity curve", "https://www.investopedia.com/terms/e/equity-curve.asp"),
    "walk_forward": ("Walk-forward analysis", "https://en.wikipedia.org/wiki/Walk_forward_optimization"),
    "pbo":          ("Probability of backtest overfitting", "https://en.wikipedia.org/wiki/Probability_of_backtest_overfitting"),
    "deflated_sharpe": ("Deflated Sharpe ratio", "https://en.wikipedia.org/wiki/Sharpe_ratio"),
    "overfitting":  ("Overfitting", "https://en.wikipedia.org/wiki/Overfitting"),
    "momentum":     ("Momentum investing", "https://www.investopedia.com/terms/m/momentum_investing.asp"),
    "factor_investing": ("Factor investing", "https://www.investopedia.com/terms/f/factor-investing.asp"),
    "information_coefficient": ("Information coefficient (IC)", "https://www.investopedia.com/terms/i/information-coefficient-ic.asp"),
    "quantile":     ("Quantile", "https://www.investopedia.com/terms/q/quantile.asp"),
    "tearsheet":    ("Performance tear sheet", "https://www.investopedia.com/terms/t/tearsheet.asp"),
    "slippage":     ("Slippage", "https://www.investopedia.com/terms/s/slippage.asp"),
    "commission":   ("Commission", "https://www.investopedia.com/terms/c/commission.asp"),
    "parameter_sweep": ("Parameter optimization", "https://en.wikipedia.org/wiki/Hyperparameter_optimization"),
    # NB07 offline-recording + end-to-end vocabulary
    "snapshot":     ("Snapshot / golden-master testing", "https://en.wikipedia.org/wiki/Characterization_test"),
    "reproducibility": ("Reproducibility", "https://en.wikipedia.org/wiki/Reproducibility"),
    "profiling":    ("Performance profiling", "https://en.wikipedia.org/wiki/Profiling_(computer_programming)"),
    "determinism":  ("Deterministic system", "https://en.wikipedia.org/wiki/Deterministic_system"),
    "provenance":   ("Data provenance", "https://en.wikipedia.org/wiki/Data_lineage"),
    # NB08 analyst-recommendations / ETF-basket vocabulary
    "etf":          ("Exchange-traded fund (ETF)", "https://www.investopedia.com/terms/e/etf.asp"),
    "asset_allocation": ("Asset allocation", "https://www.investopedia.com/terms/a/assetallocation.asp"),
    "three_fund":   ("Three-fund portfolio", "https://www.bogleheads.org/wiki/Three-fund_portfolio"),
    "all_weather":  ("All-weather / risk parity", "https://en.wikipedia.org/wiki/Risk_parity"),
    "sector_rotation": ("Sector rotation", "https://www.investopedia.com/terms/s/sectorrotation.asp"),
    "analyst_rating": ("Analyst ratings", "https://www.investopedia.com/terms/u/upgrade.asp"),
    "nport":        ("SEC Form N-PORT", "https://www.sec.gov/files/formn-port.pdf"),
    "effective_n":  ("Effective number of holdings", "https://en.wikipedia.org/wiki/Effective_number_of_parties"),
}


def _nb_esc(x):
    return _html.escape("" if x is None else str(x))


def _nb_fmt(v):
    """Human-format a scalar for a value cell. No '$' prefix (values may be
    counts, ratios, or dollars — we stay unit-neutral and just abbreviate
    large magnitudes with T/B/M)."""
    if v is None:
        return "<span style='opacity:.45'>n/a</span>"
    if hasattr(v, "item") and not isinstance(v, (list, tuple, dict, str)):
        try:
            v = v.item()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        if _math.isnan(v):
            return "<span style='opacity:.45'>n/a</span>"
        a = abs(v)
        if a >= 1e12:
            return f"{v / 1e12:.2f}T"
        if a >= 1e9:
            return f"{v / 1e9:.2f}B"
        if a >= 1e6:
            return f"{v / 1e6:.2f}M"
        return f"{v:,.4g}"
    if isinstance(v, int):
        return f"{v:,}"
    s = str(v)
    return _nb_esc(s if len(s) <= 240 else s[:240] + "…")


def nb_pill(text, tone="neutral"):
    """A small coloured status badge."""
    fg, bg = _NB_TONES.get(tone, _NB_GRAY)
    return (
        f"<span style='display:inline-block;margin:2px 4px 2px 0;padding:2px 10px;"
        f"border-radius:10px;font:700 11px ui-sans-serif,system-ui;color:{fg};"
        f"background:{bg};white-space:nowrap'>{_nb_esc(text)}</span>"
    )


def _nb_links_footer(keys):
    chips = []
    for k in keys:
        pair = NB_LINKS.get(k)
        if not pair:
            continue
        label, url = pair
        chips.append(
            f"<a href='{url}' target='_blank' rel='noopener' "
            f"style='display:inline-block;margin:4px 6px 0 0;padding:3px 10px;"
            f"border-radius:12px;background:rgba(122,162,247,.12);color:{_NB_ACCENT};"
            f"font:12px/1.5 ui-sans-serif,system-ui;text-decoration:none'>"
            f"📖 {_nb_esc(label)}</a>"
        )
    if not chips:
        return ""
    return (
        "<div style='margin-top:10px;padding-top:8px;"
        "border-top:1px solid rgba(127,127,127,.18)'>"
        "<span style='font:600 11px ui-sans-serif,system-ui;opacity:.6;"
        "text-transform:uppercase;letter-spacing:.04em'>Learn more →</span><br>"
        + "".join(chips) + "</div>"
    )


def _nb_wrap(inner, tone=_NB_GRAY, max_height=460):
    fg = tone[0]
    return (
        f"<div style='max-height:{max_height}px;overflow:auto;padding:12px 14px;"
        f"margin:2px 0;border:1px solid rgba(127,127,127,.25);"
        f"border-left:4px solid {fg};border-radius:8px'>{inner}</div>"
    )


def nb_table(headers, rows):
    """Render a header + rows table. Cells may contain HTML (pills/links);
    callers are responsible for escaping their own text."""
    th = "".join(
        f"<th style='text-align:left;padding:4px 14px 5px 0;"
        f"font:600 11px ui-sans-serif,system-ui;opacity:.7;"
        f"text-transform:uppercase;letter-spacing:.03em;"
        f"border-bottom:1px solid rgba(127,127,127,.28)'>{_nb_esc(h)}</th>"
        for h in headers
    )
    body = ""
    for r in rows:
        tds = "".join(
            f"<td style='padding:3px 14px 3px 0;font:12px/1.5 ui-monospace,monospace;"
            f"border-bottom:1px solid rgba(127,127,127,.10)'>{c}</td>"
            for c in r
        )
        body += f"<tr>{tds}</tr>"
    return (
        "<table style='border-collapse:collapse;width:100%'>"
        f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
    )


def nb_panel(title, body_html, subtitle="", links=(), tone="neutral",
             badge=None, max_height=460):
    """Generic titled panel — the single look every section renders through."""
    fg, bg = _NB_TONES.get(tone, _NB_GRAY)
    pill = (
        f"<span style='margin-left:auto;padding:3px 12px;border-radius:12px;"
        f"font:700 11px ui-sans-serif,system-ui;letter-spacing:.03em;color:{fg};"
        f"background:{bg}'>{_nb_esc(badge)}</span>" if badge else ""
    )
    head = (
        "<div style='display:flex;align-items:center;gap:10px'>"
        f"<span style='font:700 15px ui-sans-serif,system-ui'>{_nb_esc(title)}</span>"
        f"{pill}</div>"
    )
    sub = (
        f"<div style='margin:3px 0 9px;font:13px/1.45 ui-sans-serif,system-ui;"
        f"opacity:.74'>{_nb_esc(subtitle)}</div>" if subtitle else ""
    )
    display(HTML(_nb_wrap(
        head + sub + body_html + _nb_links_footer(links),
        tone=(fg, bg), max_height=max_height,
    )))


def _nb_field_rows(obj, skip=("gate_passed", "gate_notes")):
    """Extract scalar-ish fields from a Phase result into (label, html) rows.
    DataFrames / dicts / long lists are summarized, not dumped."""
    rows = []
    for name in sorted(dir(obj)):
        if name.startswith("_") or name in skip:
            continue
        try:
            val = getattr(obj, name)
        except Exception:  # noqa: BLE001
            continue
        if callable(val):
            continue
        tname = type(val).__name__
        if tname == "DataFrame":
            disp = f"<span style='opacity:.6'>table · {val.shape[0]}×{val.shape[1]}</span>"
        elif isinstance(val, dict):
            disp = f"<span style='opacity:.6'>dict · {len(val)} keys</span>"
        elif isinstance(val, (list, tuple)) and len(val) > 6:
            disp = f"<span style='opacity:.6'>{tname} · {len(val)} items</span>"
        else:
            disp = _nb_fmt(val)
        rows.append((name, disp))
    return rows


def nb_render_phase(obj, num, name, blurb="", links=(), highlight=()):
    """Render one PhaseNResult as a consistent, cross-linked panel."""
    if obj is None:
        nb_panel(f"Phase {num} · {name}",
                 "<span style='opacity:.6'><i>no result (upstream failure)</i></span>",
                 tone="neutral", badge="—")
        return

    gate = getattr(obj, "gate_passed", None)
    tone = "good" if gate is True else "bad" if gate is False else "neutral"
    badge = "PASS" if gate is True else "FAIL" if gate is False else None

    chip_html = ""
    if highlight:
        chips = []
        for label, attr in highlight:
            chips.append(nb_pill(f"{label}: {_nb_fmt(getattr(obj, attr, None))}", "accent"))
        chip_html = f"<div style='margin:2px 0 8px'>{''.join(chips)}</div>"

    rows = _nb_field_rows(obj)
    table = nb_table(
        ["field", "value"],
        [(f"<span style='color:{_NB_ACCENT}'>{_nb_esc(k)}</span>", v) for k, v in rows],
    )

    notes = getattr(obj, "gate_notes", "") or ""
    note_html = ""
    if isinstance(notes, str) and notes.strip():
        trimmed = notes if len(notes) <= 600 else notes[:600] + "…"
        note_html = (
            "<div style='margin-top:9px;padding:7px 11px;border-radius:6px;"
            "background:rgba(127,127,127,.08);border-left:3px solid #7aa2f7;"
            "font:12px/1.5 ui-sans-serif,system-ui'>"
            f"<b>gate notes</b> — {_nb_esc(trimmed)}</div>"
        )

    body = f"<div style='margin-bottom:9px'>{_nb_esc(name)}</div>{chip_html}{table}{note_html}"
    nb_panel(f"Phase {num}", body, subtitle=blurb,
             links=links, tone=tone, badge=badge)


def nb_toolkit_legend():
    """Render the 'rendering toolkit ready' colour-language legend.

    Call once near the top of a notebook after importing the toolkit so the
    reader learns the colour language up front.
    """
    display(HTML(_nb_wrap(
        "<b style='font:600 14px ui-sans-serif,system-ui'>Rendering toolkit ready</b>"
        "<div style='margin-top:7px;font:12px/1.7 ui-sans-serif,system-ui'>"
        "Every section below renders through one shared style. Colour language: "
        + nb_pill("PASS / Buy", "good") + nb_pill("FAIL / Avoid", "bad")
        + nb_pill("caution", "warn") + nb_pill("neutral", "neutral")
        + "<br>The <b>📖 Learn more</b> chips under each panel link to stable "
        "external references (Investopedia term pages, canonical docs) — never to "
        "sibling notebooks or cell anchors, which drift as the code is refactored."
        "</div>",
        tone=_NB_BLUE,
    )))
