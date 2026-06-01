# Phase 4: Valuation & Fair Value Estimation

**Version:** 1.1 — Updated 2026-03-22 (added DCF implementation, MOS grid, ROIC–WACC spread, EV/EBIT, Price-to-Gross-Profit, reverse-DCF logic, and balanced fundamental-technical entry confirmation)

## Implementation Status (vs Notebook `00. single_stock_analysis_playbook_template.ipynb`)

| Item | Plan | Notebook Status |
|------|------|-----------------|
| P/E ratio | Relative multiple | Implemented with manual fallback (Cell 19) |
| EV/EBITDA | Relative multiple | Implemented (Cell 19) |
| P/FCF | Relative multiple | Implemented (Cell 19) |
| P/S | Relative multiple | Implemented (Cell 19) |
| Earnings Yield | Relative (1/PE) | Implemented with fallback (Cell 19) |
| WACC | Intrinsic input | Extracted from ratios (often NaN) (Cell 19) |
| Piotroski F-Score | Quality overlay | Extracted from ratios (Cell 19) |
| Altman Z-Score | Distress screen | Extracted from ratios (Cell 19) |
| DCF Fair Value | Intrinsic valuation | **Not implemented** (explicitly skipped) |
| Margin of Safety | Buy-zone signal | **Not implemented** |
| Terminal Growth | DCF sensitivity | **Not implemented** |
| ROIC − WACC spread | Value creation gap | **Not implemented** |
| Sensitivity table (3×3) | WACC/growth scenarios | **Not implemented** |
| Valuation Decision Grid | MOS-based rules | **Not implemented** |
| 5Y historical multiples trend | Trend context | **Not implemented** |
| **EV/EBIT** | Cleaner operating multiple | **Not implemented** |
| **Price-to-Gross-Profit** | Novy-Marx quality-value hybrid | **Not implemented** |
| **Reverse-DCF implied growth** | What growth does the market price assume? | **Not implemented** |
| **Valuation–Technical confirmation gate** | Entry only when both valuation + technicals align | **Not implemented** |
| Provider | OpenBB + FinanceToolkit models | OpenBB only (FinanceToolkit skipped) |

**Current notebook outputs:** 10 valuation metrics in `valuation_df` (Price, EPS, P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield, WACC, Piotroski, Altman Z).
**Biggest gaps:** DCF entirely absent; no MOS; no sensitivity table; no historical multiple trend; no reverse-DCF; no technical confirmation gate.

---

## Objective
Convert business quality into a price decision: cheap, fair, or expensive — and then confirm that the technical setup supports entering at the current price.

A balanced fundamental-technical analyst does not separate valuation from timing. A stock can be intrinsically cheap but technically broken; entering into a downtrend destroys the thesis even if the long-run fair value is correct. This phase therefore produces both a **valuation verdict** and a **confirmation check** against Phase 3 signals before outputting a gate decision.

## Valuation Approach: Four Lenses in Triangulation

Use four complementary lenses. Any single lens in isolation is unreliable — they must converge:

1. **Relative multiples** vs the company's own 5Y median and current peers
2. **Intrinsic DCF** — discounted free cash flows to a terminal value
3. **Reverse-DCF** — what growth rate does the current price imply?
4. **Quality overlays** — Piotroski, Altman, ROIC–WACC spread

**The balanced rule:** A Buy signal requires at least 3 of 4 lenses to agree on direction (cheap or fair), AND Phase 3 technical conditions ≥ 4 of 11 bullish.

---

## KPI Set and Interpretation

### A) Relative Multiples
| KPI | Layman explanation | Practical use | Preferred signal |
|---|---|---|---|
| P/E | Years of earnings you pay for today | Compare vs own 5Y median + sector median | P/E below own 5Y median by ≥ 15% = potentially undervalued |
| EV/EBITDA | Enterprise value per dollar of operating earnings — ignores capital structure | Best cross-company comparison (removes debt/tax differences) | EV/EBITDA below sector median + own 5Y median = value zone |
| **EV/EBIT** | Like EV/EBITDA but removes D&A manipulation — harder to game | Preferred for capital-light software / tech companies where D&A is artificial | EV/EBIT below own 5Y median = operational undervaluation signal |
| P/FCF | Price per dollar of real free cash | Better than P/E for cash-heavy businesses | P/FCF below 20× with stable FCF margin = attractive |
| P/S | Price per dollar of revenue | Useful when earnings are cyclical or negative | P/S expansion without gross margin improvement is a red flag |
| **Price-to-Gross-Profit** | Price per dollar of gross profit — Novy-Marx quality-value hybrid | Screens for undervalued *quality* names; works where P/E breaks down | P/GP below own 3Y average + sector peer = quality value opportunity |

**Why EV/EBIT was added:** D&A (Depreciation & Amortisation) is a non-cash charge that management can manipulate through accounting policy choices (useful life assumptions, asset impairments). EV/EBIT strips D&A out of the denominator, giving a cleaner view of operating profitability. For asset-light businesses, D&A is immaterial and EV/EBITDA works fine; for capital-intensive or acquisition-heavy companies, the D&A choices can make EV/EBITDA misleading. Using both gives a cross-check.
*Reference: Damodaran, A. (2012). Investment Valuation: Tools and Techniques for Determining the Value of Any Asset (3rd ed.). Wiley, Ch. 17.*

**Why Price-to-Gross-Profit was added:** Net income multiples (P/E, P/FCF) can be depressed by temporary items (restructuring, tax, write-offs) or inflated by unsustainable margins. Gross profit is the cleanest income line — the fewest accounting choices distort it. A company trading at a low Price-to-Gross-Profit ratio relative to history and peers is cheap on the metric that best reflects underlying business economics.
*Reference: Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." Journal of Financial Economics, 108(1), 1–28.*

### B) Intrinsic Value KPIs
| KPI | Layman explanation | Decision use | Threshold |
|---|---|---|---|
| DCF Fair Value | PV of all future free cash flows to equity | Primary intrinsic anchor | See §DCF section below |
| **Margin of Safety (MOS)** | How much cheaper is the stock vs fair value? | Buy zone typically ≥ 15–20% discount | MOS ≥ 20%: buy zone; MOS ±5%: fair value; MOS < −15%: overvalued |
| WACC | Required return hurdle — the discount rate for all future cash flows | Key DCF sensitivity driver | Higher WACC = lower fair value; must be calibrated to sector risk |
| Terminal Growth Rate | Long-run growth assumption after the explicit forecast period | Keep conservative: 2–3% for mature; ≤ 4% for high-growth | g > 5% in terminal year is heroic; stress-test it |
| **Reverse-DCF Implied Growth** | Solve DCF backwards: what FCF growth does the current price imply? | Sanity check on market expectations | Implied growth > 15% for a mature business = expensive; compare vs analyst consensus |
| **ROIC − WACC Spread** | Is the business earning more than its cost of capital? | Positive and stable spread = value-creating business | Spread > +3% over 5Y = economic moat; spread < 0 = value destruction |

**Why Reverse-DCF was added:** A forward DCF requires the analyst to choose growth rates — which introduces forecast error. Reverse-DCF eliminates the forecast: you start from the *current market price* and solve backwards to find what growth rate the market is pricing in. This immediately answers: "Is the market pricing in realistic or heroic assumptions?" If the implied growth rate is higher than the highest analyst estimate, the stock is priced for perfection. If implied growth is below consensus, the market may be underestimating the business.
*Reference: Mauboussin, M. & Johnson, P. (1997). "Competitive Advantage Period: The Neglected Value Driver." Financial Management, 26(2), 67–74. Also: Rappaport, A. & Mauboussin, M. (2001). Expectations Investing. Harvard Business School Press.*

**Why ROIC−WACC Spread was added:** This is the single cleanest test of whether a business creates value. If a company earns 18% on its invested capital but its cost of capital (WACC) is 9%, every dollar reinvested into the business creates 9 cents of value above the cost. A company with ROIC < WACC destroys value every time it reinvests. You can also use this to justify paying a premium: a business with a sustained ROIC-WACC spread of +10% *deserves* a high P/E because it compounding value at well above the required return.
*Reference: Koller, T., Goedhart, M. & Wessels, D. (2020). Valuation: Measuring and Managing the Value of Companies (7th ed.). Wiley/McKinsey, Ch. 4. This is the standard corporate finance valuation textbook used by investment banks worldwide.*

### C) Quality Overlay KPIs
| KPI | Layman explanation | Rule of thumb | Source |
|---|---|---|---|
| Piotroski F-Score | 9-point binary checklist testing profitability, leverage, efficiency | ≥ 7: strong; ≤ 3: weak — use as filter, not standalone | Piotroski (2000), *Journal of Accounting Research* |
| Altman Z-Score | Statistical distress predictor using 5 financial ratios | > 2.99: safe zone; 1.81–2.99: grey zone; < 1.81: distress zone | Altman (1968), *Journal of Finance* |
| ROIC − WACC Spread | See §B above | Positive sustained spread validates premium valuation | McKinsey Valuation (2020) |

---

## DCF Implementation

### Formula (5-year explicit + Gordon Growth terminal value)
```
# Year 1–5 explicit FCF projection
FCF_t = FCF_0 × (1 + g_short)^t   for t = 1..5

# Discount to present value
PV_explicit = Σ [ FCF_t / (1 + WACC)^t ]   for t = 1..5

# Terminal value (Gordon Growth Model, Year 5 base)
TV = FCF_5 × (1 + g_term) / (WACC − g_term)
PV_TV = TV / (1 + WACC)^5

# Equity value per share
DCF_fair_value = (PV_explicit + PV_TV) / shares_outstanding
```

**Guard:** if WACC ≤ g_term, clamp g_term = WACC − 0.01.

### Input sourcing
| Input | Source | Fallback |
|---|---|---|
| Latest FCF (FCF_0) | `cash_df["free_cash_flow"].iloc[-1]` | `operating_cash_flow − capex` |
| g_short | Revenue CAGR from `phase2_fundamentals` | 0.05 |
| g_term | Conservative default | 0.025 |
| WACC | `ratios_df["wacc"].iloc[-1]` | 0.09 if NaN |
| Shares | `metrics_df["shares_outstanding"]` | from `income_df` |
| Current price | `quote_df["last_price"]` | `metrics_df["price"]` |

### Sensitivity table (3×3 grid)
```python
# WACC rows: base−1%, base, base+1%
# g_term cols: base−0.5%, base, base+0.5%
sensitivity_df = _dcf_sensitivity(fcf=FCF_0, g_short=g_short, wacc_base=WACC,
                                   g_term_base=g_term, shares=shares)
```

### Reverse-DCF computation
```python
# Solve for g_short that makes DCF_fair_value == current_price
# Numerically: binary search g_short ∈ [−0.10, 0.30] to minimise |DCF(g) − price|
from scipy.optimize import brentq
implied_growth = brentq(
    lambda g: _dcf_single(FCF_0, g, g_term, WACC, shares) - current_price,
    -0.10, 0.30
)
```

---

## Valuation–Technical Confirmation Gate

A balanced fundamental-technical approach requires that **both** the valuation verdict and the technical setup align before entering a position. The logic:

| Valuation verdict | Technical Phase 3 bullish count | Recommendation |
|---|---|---|
| Undervalued (MOS ≥ 15%) | ≥ 6 of 11 | **Strong entry signal** — value + timing aligned |
| Undervalued (MOS ≥ 15%) | 3–5 of 11 | **Partial entry** — fundamental case strong but wait for technical improvement; initial size 50% |
| Undervalued (MOS ≥ 15%) | < 3 of 11 | **Wait** — cheap but technically broken; can enter pre-position but no full allocation |
| Fair value (MOS 0–15%) | ≥ 6 of 11 | **Opportunistic entry** — not a bargain but momentum supports the thesis |
| Fair value (MOS 0–15%) | < 6 of 11 | **Watchlist** — no asymmetric opportunity |
| Overvalued (MOS < 0%) | Any | **Avoid new longs** regardless of technical strength — paying too much erodes long-run returns |

**Rationale for the gate:** Ben Graham's value investing approach (buy cheap, hold) and technical momentum approaches are often treated as opposites. They are not — they are complementary time horizons. Value tells you *what to buy*; technicals tell you *when to buy*. Entering into a technically broken chart on a fundamentally cheap stock means capital is tied up potentially for years before the catalyst arrives. Waiting for technical confirmation — or at least partial confirmation — improves entry price and reduces time to thesis validation.
*Reference: Asness, C., Moskowitz, T. & Pedersen, L. (2013). "Value and Momentum Everywhere." Journal of Finance, 68(3), 929–985 — shows value and momentum are negatively correlated and work better in combination than either alone.*

---

## Valuation Decision Grid (updated v1.1)

| Condition | Interpretation | Action |
|---|---|---|
| MOS ≥ 20% + quality strong (Piotroski ≥ 7) + technical ≥ 6/11 | Optimal entry: cheap, quality, and timed | Full position, staged over 2–3 sessions |
| MOS ≥ 20% + quality strong + technical 3–5/11 | Value confirmed, wait for timing | 50% position; add when technicals improve |
| MOS 5–20% + tech ≥ 6/11 | Mildly attractive with good timing | Partial entry; tight stop |
| MOS within ±5% of fair value | At fair value — no asymmetry | Hold existing; no new entry |
| Overvalued > 15% with any technicals | Priced beyond fundamentals | Avoid; consider trim if held |
| Altman Z < 1.81 regardless of multiples | Distress risk — multiples unreliable | Hard pass; do not enter |

---

## Programmatic Pull

### Currently implemented in notebook (Cell 19)
```python
# Reuses ratios_df and quote_df from Phase 2 / Phase 1
price_now = safe_df_value(quote_df, ["last_price", "price"])
eps_now   = safe_df_value(income_df, ["basic_earnings_per_share", "eps", "eps_diluted"])
pe        = safe_ratio_value(["price_earnings_ratio", "pe_ratio", "pe"])
ev_ebitda = safe_ratio_value(["enterprise_value_multiple", "ev_to_ebitda"])
p_fcf     = safe_ratio_value(["price_to_free_cash_flow", "price_to_free_cash_flow_ratio"])
p_s       = safe_ratio_value(["price_to_sales", "price_to_sales_ratio"])
# No DCF, no MOS, no reverse-DCF
```

### Planned module implementation (`phase4_valuation` in `stock_analysis.py`)
```python
# Reuses data from phases 1 and 2 — no new API calls for core valuation
# New multiples require gross_profit from income_df (already fetched)
ev_ebit      = enterprise_value / income_df["operating_income"].iloc[-1]
p_gross      = current_price * shares / income_df["gross_profit"].iloc[-1]
roic_wacc    = ratios_df["roic"].iloc[-1] - wacc_used
dcf_value    = _dcf_single(FCF_0, g_short, g_term, wacc_used, shares)
mos          = (dcf_value - current_price) / dcf_value
sensitivity  = _dcf_sensitivity(FCF_0, g_short, wacc_used, g_term, shares)
implied_g    = _reverse_dcf(FCF_0, g_term, wacc_used, shares, current_price)
```

---

## Exit Criteria (updated v1.1)
- Fair value estimate from at least 2 of 4 lenses agrees on direction
- Margin of Safety explicitly computed and classified
- Sensitivity table (3×3 WACC × g_term) completed
- Reverse-DCF implied growth compared to analyst consensus
- Valuation–Technical confirmation gate checked and recorded
- Altman Z-Score confirms no distress risk

---

*Phase 4 spec version 1.1 | Updated 2026-03-22 | Cross-reference: `PHASED_ANALYSIS_MASTER_PLAN.md` §2b*
