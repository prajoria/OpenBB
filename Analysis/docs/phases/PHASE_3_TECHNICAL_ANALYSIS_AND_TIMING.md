# Phase 3: Technical Analysis & Trade Timing

**Version:** 1.1 — Updated 2026-03-22 (added institutional-grade timing signals: VWAP, Ichimoku, ROC, 52-week high, CMF, earnings guard, gap analysis, multi-timeframe confluence, Fibonacci)

## Implementation Status (vs Notebook `00. single_stock_analysis_playbook_template.ipynb`)

| Item | Plan | Notebook Status |
|------|------|-----------------|
| Historical prices (1yr daily) | `obb.equity.price.historical` | Implemented (Cell 17) |
| RSI(14) | Momentum | Implemented, used in scoring (Cell 17, 36) |
| ADX(14) | Trend strength | Implemented, used in scoring (Cell 17, 36) |
| ATR(14) | Volatility sizing | Implemented, displayed but **not in scoring** (Cell 17) |
| OBV | Volume confirmation | Implemented, sign used in scoring (Cell 17, 36) |
| MACD (12,26,9) | Momentum acceleration | **Computed but not used in scoring or display** (Cell 17) |
| Bollinger Bands (20,2) | Volatility context | **Plotted but not in scoring** (Cell 17) |
| SMA 50 vs SMA 200 | Trend regime | **Not implemented** |
| Price vs SMA 200 | Long-term trend | **Not implemented** |
| Stochastic (14,3,3) | Short-cycle momentum | **Not implemented** |
| Bollinger Band Width | Squeeze detection | **Not implemented** (bands plotted, width not computed) |
| OBV slope (20D) | Volume trend direction | **Not implemented** (only OBV sign check) |
| Breakout Volume Ratio | Breakout validation | **Not implemented** |
| Multi-timeframe (weekly/4h) | Regime+execution frames | **Not implemented** (daily only) |
| Trade setup checklist (6 conditions) | Entry rules | **Not implemented** |
| Phase gate (>= 4/6 bullish) | Exit criteria | **Not implemented** |
| Provider | FinanceToolkit `ft_ta.technicals` | Computed manually with pandas/numpy |
| **VWAP + Anchored VWAP** | Institutional execution benchmark | **Not implemented** |
| **Ichimoku Cloud (9,26,52)** | Multi-signal trend system | **Not implemented** |
| **Rate of Change ROC(20/60/120)** | Absolute price momentum | **Not implemented** |
| **52-Week High Proximity** | Breakout resistance / momentum signal | **Not implemented** |
| **Chaikin Money Flow CMF(21)** | Volume-weighted money flow oscillator | **Not implemented** |
| **Earnings Date Proximity guard** | Event risk hard override | **Not implemented** |
| **Price Gap Analysis** | Unfilled gap support/resistance levels | **Not implemented** |
| **Multi-Timeframe Confluence (Weekly)** | Weekly trend must confirm daily entry | **Not implemented** |
| **Fibonacci Retracement Levels** | Pullback entry zones | **Not implemented** |
| **Phase gate revised (>= 6/11 bullish)** | Expanded exit criteria | **Not implemented** |

**Current notebook scoring inputs:** RSI(14), ADX(14), OBV sign (3 inputs).
**Original plan indicators not feeding scoring:** MACD, Bollinger Bands, SMA 50/200, Stochastic, BB Width, OBV slope, Breakout Volume.
**v1.1 additions not yet in notebook:** VWAP, Ichimoku, ROC, 52-week high, CMF, earnings guard, gap analysis, weekly confluence, Fibonacci levels.
**Key difference v1.1:** Gate expands from ≥ 4 of 6 to ≥ 6 of 11 bullish conditions. Two hard overrides added (earnings proximity, weekly trend disagreement). Entry Quality label ("High Conviction" / "Standard" / "Cautious") introduced.

---

## Objective
Use technicals to time entries and exits after the business has passed the fundamental screen. The goal is not to predict market direction but to identify *when* price action, volume, and market structure align in favour of the thesis — maximising entry quality and reducing the probability of entering into adverse price structure.

## Analysis Frames
- **Regime frame:** Weekly chart (trend context) — must be bullish before proceeding
- **Execution frame:** Daily chart (entry timing) — primary signal source
- **Optional refinement:** 4-hour chart for swing entries on high-conviction setups

---

## Indicator Stack

### A) Trend KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| SMA 50 vs SMA 200 | Shows medium vs long-term trend direction | SMA50 > SMA200 = bullish regime (golden cross) | "Golden cross" supports buying pullbacks; not a signal to chase breakouts blindly. |
| Price vs SMA 200 | Is the stock in a long-term uptrend? | Price above 200DMA preferred for new longs | Price below 200DMA: reduce position size by 50% minimum. |
| ADX(14) | Measures trend *strength*, not direction | > 25 strong trend; < 20 = range-bound | ADX 30 and rising = trend-following strategies outperform. |
| **VWAP (cumulative + anchored)** | Volume-weighted average price since a structural anchor — institutional execution benchmark | Price above VWAP = avg institutional buyer in profit (accumulation); below = distribution | Stock trading above VWAP from post-earnings gap = institutions who bought the move are winning. |
| **Ichimoku Cloud (9,26,52)** | Five-component system giving trend direction, momentum, support/resistance simultaneously | Price above cloud + Tenkan > Kijun + Chikou above = three-confirmation bullish | Three-confirmation Ichimoku entry is one of the lowest false-signal-rate setups available from a single system. |
| **Multi-Timeframe Confluence (Weekly)** | Weekly trend must confirm daily entry signal | Weekly price > 20-week SMA AND weekly ADX > 20 = regime confirmed | Daily MACD cross in a weekly downtrend has ~55% failure rate vs ~35% in a weekly uptrend. |

### B) Momentum KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| RSI(14) | Detects overbought/oversold | In uptrends, buy RSI pullback to 40–55 | RSI 78 is not auto-sell if trend and volume are confirming. |
| MACD(12,26,9) line vs signal | Momentum acceleration / deceleration | Bullish cross above zero is strongest setup | Cross below zero in weak breadth typically warns of a deeper pullback. |
| Stochastic(14,3,3) | Short-cycle momentum turns | %K cross above %D below 20 = potential rebound | Useful for timing entries in range-bound phases; combine with RSI. |
| **Rate of Change ROC(20/60/120)** | Absolute price momentum over defined lookbacks | Both ROC-60 and ROC-120 > 0 = medium and long-term momentum positive | ROC-120 positive but ROC-20 slightly negative = healthy pullback within uptrend (entry opportunity). ROC-120 negative = trend reversal risk. |
| **52-Week High Proximity** | Distance from the 52-week high level — psychological and mechanical resistance/breakout | Within 3–5% of 52-week high + high volume = breakout candidate | Stock at 98% of 52-week high with volume ratio > 1.5× is a high-probability continuation setup. |
| **Fibonacci Retracement Levels** | Proportional pullback zones (38.2%, 50%, 61.8%) where buyers typically re-engage | Price pulling back to 38.2–61.8% of the prior swing range = entry zone | A pullback to the 50% Fibonacci level on declining volume confirms retracement is consolidation, not distribution. |

### C) Volatility & Risk KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| ATR(14) | Typical daily move size — calibrates stop distance | Initial stop = entry − 2×ATR | ATR $3.50 means a $7 stop from entry baseline. |
| Bollinger Band Width (20,2) | Volatility compression (squeeze) preceding expansion | Narrowest band in 6 months then upside break = expansion setup | Bollinger squeeze + breakout on 2× average volume = high-probability trend initiation. |

### D) Volume Confirmation KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| OBV slope (20D) | Confirms if net volume is supporting the price trend | Rising OBV with rising price = healthy accumulation | Price up but OBV flat = weak participation; be cautious. |
| Breakout Volume Ratio | Validates breakout quality on the specific day | Breakout day volume > 1.5× 20D average = confirmed | Low-volume breakout has high failure rate; wait for volume to confirm. |
| **Chaikin Money Flow CMF(21)** | Normalised measure of current buying/selling pressure intensity within daily range | CMF > 0 = net buying pressure over 21 days | CMF negative while OBV positive = recent distribution even in a longer-term accumulation trend — near-term yellow flag. |

### E) Event Risk & Structural KPIs (New category — v1.1)
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| **Earnings Date Proximity** | Technical setups are statistically unreliable within 5 days of earnings | > 5 days to earnings = safe to enter technically | Within 5 days: cap position size at 25% of normal; any stop can be gapped through overnight. |
| **Price Gap Analysis** | Unfilled upward gaps act as structural support; unfilled downward gaps act as resistance | Nearest unfilled upward gap < 8% below current price = stop anchor | Post-earnings gap up that has never been filled = high-quality support zone for new long entry. |

---

## Trader Rationale and References for v1.1 Additions

### VWAP + Anchored VWAP
**Why it was added:** VWAP is the universal institutional execution benchmark. Large funds, ETF rebalancers, and algorithmic trading systems all size orders relative to VWAP to minimise market impact. When price is above cumulative VWAP from a significant structural anchor (earnings, breakout, 52-week low), the average institutional buyer since that date is in profit — the market "structure" is favourable. This is not theoretical; it is a mechanical reality of how large orders flow through markets.
**Formula:** `VWAP = Σ(typical_price × volume) / Σ(volume)` where `typical_price = (H + L + C) / 3` (cumulative from the start of the technicals window or a user-defined anchor date)
**Anchored variant:** Same formula but reset to a specific date — e.g., the date of the last earnings gap up.
**Reference:** Harris, L. (2003). *Trading and Exchanges: Market Microstructure for Practitioners*. Oxford University Press, Ch. 19. Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio Transactions." *Journal of Risk*, 3(2), 5–39. Shannon, B. (2008). *Technical Analysis Using Multiple Timeframes*. LifeVest Publishing.
**Signal:** `above_vwap = close[-1] > vwap[-1]`

### Ichimoku Cloud
**Why it was added:** Ichimoku is the most information-dense single indicator system available from price alone. Where RSI gives one reading and MACD gives one reading, Ichimoku simultaneously provides: trend direction (price vs cloud), momentum crossover (Tenkan vs Kijun), forward support/resistance (cloud), and lagging confirmation (Chikou). The "three-confirmation" setup — all three bullish simultaneously — has substantially lower false-signal rates than any single-indicator cross.
**Formula:**
- `Tenkan-sen (9)  = (max_high_9 + min_low_9) / 2`
- `Kijun-sen (26)  = (max_high_26 + min_low_26) / 2`
- `Senkou Span A   = (Tenkan + Kijun) / 2` (shifted 26 bars forward)
- `Senkou Span B   = (max_high_52 + min_low_52) / 2` (shifted 26 bars forward)
- `Chikou Span     = close` (shifted 26 bars backward)
**Reference:** Hosoda, G. (1969). *Ichimoku Kinko Hyo* (original Japanese publication). Péloille, N. (2017). *Trading with Ichimoku Clouds: The Essential Guide to Ichimoku Kinko Hyo Technical Analysis*. Wiley. Murphy, J.J. & Izzeldin, M. (2017). "Forecasting Returns with Ichimoku Cloud Indicators." EFMA Conference Paper — documents positive out-of-sample return predictability for Ichimoku trend signals.
**Signals:** `above_cloud`, `tenkan_kijun_bull`, `chikou_clear`

### Rate of Change (ROC)
**Why it was added:** RSI is an internal momentum oscillator — it measures the speed of recent price moves relative to each other. ROC measures *absolute* price change over a defined window, which is exactly what the academic momentum literature has documented as a return predictor. Using three lookbacks (20D, 60D, 120D) allows distinction between: (1) healthy pullback within an uptrend (ROC-120 positive, ROC-20 slightly negative) and (2) genuine trend failure (all ROC negative).
**Formula:** `ROC(n) = (close / close.shift(n) − 1) × 100`
**Reference:** Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*, 48(1), 65–91 — foundational momentum paper, 10% annualised return from top-decile 6-month momentum. Carhart, M. (1997). "On Persistence in Mutual Fund Performance." *Journal of Finance*, 52(1), 57–82 — added momentum as the 4th factor to Fama-French. Asness, C., Moskowitz, T. & Pedersen, L. (2013). "Value and Momentum Everywhere." *Journal of Finance*, 68(3), 929–985.
**Signal:** `momentum_positive = (roc_60[-1] > 0) and (roc_120[-1] > 0)`

### 52-Week High Proximity
**Why it was added:** The 52-week high level is a demonstrated return predictor in its own right — stronger than raw 6-month price momentum in some specifications. It captures the anchoring dynamics at psychological round-number resistance levels that raw price change measures miss. When price breaks above the 52-week high on strong volume, algorithmic momentum strategies trigger simultaneously, creating a self-reinforcing flow burst.
**Formula:** `dist_from_52wk_high = (close.rolling(252).max() − close) / close.rolling(252).max()`
**Reference:** George, T.J. & Hwang, C. (2004). "The 52-Week High and Momentum Investing." *Journal of Finance*, 59(5), 2145–2176 — proximity to the 52-week high predicts returns more powerfully than Jegadeesh-Titman 6-month momentum because it captures investor anchoring behaviour and resistance-release dynamics.
**Signals:** `near_52wk_high = dist_from_52wk_high[-1] < 0.05`, `52wk_breakout = close[-1] >= close.rolling(252).max()[-2]`

### Chaikin Money Flow (CMF)
**Why it was added:** OBV measures the *cumulative direction* of volume over time — a good trend-health indicator. CMF measures the *current intensity* of buying or selling pressure in the recent 21 days, weighted by where each day's close falls within its high-low range. These are complementary: OBV can be rising (long-term accumulation intact) while CMF turns negative (near-term distribution). This divergence is a yellow flag worth surfacing on its own rather than relying solely on OBV.
**Formula:** `MFM = ((C − L) − (H − C)) / (H − L)` (Money Flow Multiplier); `CMF = Σ(MFM × Vol, 21) / Σ(Vol, 21)`
**Reference:** Chaikin, M. (1980s, proprietary). Documented in: Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. New York Institute of Finance, Ch. 7. Achelis, S.B. (2001). *Technical Analysis from A to Z*. McGraw-Hill, 2nd ed.
**Signal:** `cmf_positive = cmf_21[-1] > 0`

### Earnings Date Proximity
**Why it was added:** This is not a return-forecasting signal — it is a risk management hard stop. Technical setups lose their validity within 5 days of an earnings announcement because: (1) options implied volatility expansion creates price pressure that has nothing to do with the chart setup; (2) delta-hedging flows from options market makers distort intraday price/volume signals; (3) any ATR-based stop is irrelevant if the stock can gap 15% overnight. The professional rule is unambiguous: do not enter a new technical position into binary event risk.
**Formula:** `days_to_earnings = (next_earnings_date − today).days`; uses `obb.equity.calendar.earnings(provider="fmp_cached")`
**Reference:** Ball, R. & Brown, P. (1968). "An Empirical Evaluation of Accounting Income Numbers." *Journal of Accounting Research*, 6(2), 159–178 — foundational paper on post-earnings drift and pre-earnings price uncertainty. Natenberg, S. (1994). *Option Volatility and Pricing*. McGraw-Hill, Ch. 16 — covers IV expansion into earnings and its distortion of price-based signals. O'Neil, W.J. (2009). *How to Make Money in Stocks*. McGraw-Hill, 4th ed.: rule against entering in the week before earnings.
**Signal:** `earnings_safe_window = days_to_earnings > 5`
**Hard override:** If `earnings_safe_window == False` → cap Phase 7 technical score at 2.5/5.

### Price Gap Analysis
**Why it was added:** Unfilled price gaps are not random noise — they represent price levels where a significant portion of the day's participants did not trade (demand exceeded supply so fast that no prints occurred in the gap range). Algorithms explicitly target gap fill levels as mean-reversion trades, and institutional order flow that caused the gap tends to reinforce price support if the fundamental catalyst remains intact. An unfilled upward gap within 8% below current price provides a high-quality structural stop anchor for new entries — better than an arbitrary ATR multiple in many cases.
**Formula:** `gap_pct = (open_t / close_{t-1}) − 1`; significant gap if `|gap_pct| > 1%`; unfilled if subsequent lows have not re-entered the gap range.
**Reference:** Bulkowski, T.N. (2005). *Encyclopedia of Chart Patterns*. Wiley, 2nd ed. — documented empirically that "runaway gaps" in trending stocks are filled < 40% of the time within 3 months, validating them as structural support zones. Elder, A. (1993). *Trading for a Living*. Wiley.
**Signal:** `gap_support_nearby = nearest_unfilled_up_gap_pct_below < 0.08`

### Multi-Timeframe Confluence
**Why it was added:** The single largest cause of failed technical setups is entering a valid daily chart signal that is counter-directional to the prevailing weekly trend. A daily MACD cross, rising RSI, and strong volume are all irrelevant if the weekly chart shows the stock in a confirmed Stage 3 (distribution) or Stage 4 (downtrend) phase — the daily setup will fail at the next weekly resistance level. Requiring weekly trend confirmation filters out the majority of counter-trend traps.
**Formula:** Weekly data resampled from daily OHLCV (no new API call). `weekly_trend_bull = close_weekly[-1] > sma20_weekly[-1] AND adx_weekly[-1] > 20`
**Reference:** Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. New York Institute of Finance, Ch. 8: "The Case for Multiple Time-Frame Analysis." Elder, A. (2002). *Come Into My Trading Room*. Wiley — "Triple Screen" method: filter by weekly, time by daily, trigger by intraday. Weinstein, S. (1988). *Secrets for Profiting in Bull and Bear Markets*. McGraw-Hill — Stage Analysis built entirely on weekly chart primacy.
**Signal:** `weekly_trend_bullish`
**Hard override:** If `weekly_trend_bullish == False` → cap Phase 7 technical score at 2.0/5 regardless of daily signal count.

### Fibonacci Retracement Levels
**Why it was added:** The Fibonacci ratios (38.2%, 50%, 61.8%) derived from the Golden Ratio φ = 1.618 describe natural proportional retracements that appear consistently across financial markets. Their practical value is not mathematical determinism — it is that enough market participants watch and act on these levels simultaneously that they create self-fulfilling support zones. A 38.2–61.8% pullback from a prior swing high, on decreasing volume, with RSI in the 40–50 zone, is one of the highest-probability entry setups in systematic technical trading.
**Formula:** `fib_38 = swing_high − 0.382 × range`; `fib_50 = swing_high − 0.50 × range`; `fib_62 = swing_high − 0.618 × range`; where `range = swing_high − swing_low` over the 1-year lookback window.
**Reference:** Carney, S. (2010). *Harmonic Trading, Volume 1: Profiting from the Natural Order of the Financial Markets*. FT Press. Osler, C.L. (2000). "Support for Resistance: Technical Analysis and Intraday Exchange Rates." *Economic Policy Review*, Federal Reserve Bank of New York, 6(2), 53–68 — provides empirical evidence that technical levels including Fibonacci-derived zones act as statistically significant support and resistance in FX markets. Murphy (1999), Ch. 9.
**Signal:** `at_fibonacci_support = fib_62 × 0.99 ≤ close[-1] ≤ fib_38 × 1.01`

---

## Programmatic Pull

### Currently implemented in notebook (Cell 17)
```python
symbol_hist_obj, symbol_hist_provider = call_obb(
    obb.equity.price.historical,
    symbol=SYMBOL,
    start_date=START_DATE_TECHNICALS,
    end_date=END_DATE,
    interval="1d",
)
# RSI(14), MACD(12,26,9), ATR(14), OBV, ADX(14), Bollinger Bands(20,2) — computed manually
# MACD computed but not used in scoring
```

### Planned module implementation (`phase3_technicals` in `stock_analysis.py`)
```python
# Single API call — all v1.1 indicators derived from this data, no new calls needed
price_df = obb.equity.price.historical(
    symbol=cfg.symbol,
    start_date=cfg.start_technicals,
    end_date=cfg.end_date,
    interval="1d",
    provider=cfg.provider,
).to_df()

# Earnings date proximity — one additional call using confirmed fmp_cached model
earnings_df  = obb.equity.calendar.earnings(symbol=cfg.symbol, provider=cfg.provider).to_df()
next_earnings = pd.Timestamp(earnings_df["date"].iloc[0]) if not earnings_df.empty else None
days_to_earnings = (next_earnings - pd.Timestamp.today()).days if next_earnings else 999

# All indicators via _compute_technicals(price_df) — returns price_df with added columns:
# Original: RSI, MACD, ADX, ATR, OBV, SMA50, SMA200, Stochastic %K/%D, BB Width, Vol Ratio
# v1.1 new: VWAP, Ichimoku (Tenkan/Kijun/SpanA/SpanB), ROC_20/60/120, CMF_21, Gap flags, Fib levels
# Weekly indicators: derived via price_df.resample("W").agg(...)
```

### v1.1 indicator computation sketches
```python
# VWAP
typical_price = (price_df["high"] + price_df["low"] + price_df["close"]) / 3
vwap = (typical_price * price_df["volume"]).cumsum() / price_df["volume"].cumsum()

# Ichimoku
tenkan = (price_df["high"].rolling(9).max()  + price_df["low"].rolling(9).min())  / 2
kijun  = (price_df["high"].rolling(26).max() + price_df["low"].rolling(26).min()) / 2
span_a = ((tenkan + kijun) / 2).shift(26)
span_b = ((price_df["high"].rolling(52).max() + price_df["low"].rolling(52).min()) / 2).shift(26)

# ROC
roc_20  = price_df["close"].pct_change(20)  * 100
roc_60  = price_df["close"].pct_change(60)  * 100
roc_120 = price_df["close"].pct_change(120) * 100

# CMF(21)
mf_mult = ((price_df["close"] - price_df["low"]) - (price_df["high"] - price_df["close"])) \
          / (price_df["high"] - price_df["low"] + 1e-10)
cmf_21  = (mf_mult * price_df["volume"]).rolling(21).sum() \
          / price_df["volume"].rolling(21).sum()

# Fibonacci
swing_high = price_df["close"].rolling(252).max().iloc[-1]
swing_low  = price_df["close"].rolling(252).min().iloc[-1]
fib_range  = swing_high - swing_low
fib_levels = {
    "23.6%": swing_high - 0.236 * fib_range,
    "38.2%": swing_high - 0.382 * fib_range,
    "50.0%": swing_high - 0.500 * fib_range,
    "61.8%": swing_high - 0.618 * fib_range,
    "78.6%": swing_high - 0.786 * fib_range,
}

# Weekly confluence
weekly_df   = price_df.resample("W").agg({"open":"first","high":"max",
                                           "low":"min","close":"last","volume":"sum"})
weekly_sma20 = weekly_df["close"].rolling(20).mean()
# weekly ADX reuses _compute_adx() helper on weekly_df
```

---

## Trade Setup Checklist (updated — v1.1)

**11 conditions evaluated; gate = ≥ 6 bullish**

| # | Signal | Indicator | Bullish Condition |
|---|---|---|---|
| 1 | `sma_golden_cross` | SMA50 vs SMA200 | SMA50 > SMA200 |
| 2 | `adx_trending` | ADX(14) | ADX ≥ 20 |
| 3 | `rsi_pullback` | RSI(14) | RSI between 40–60 |
| 4 | `macd_bullish` | MACD(12,26,9) | MACD line > signal line |
| 5 | `obv_rising` | OBV slope (20D) | OBV slope positive |
| 6 | `volume_ratio_normal` | Breakout Volume Ratio | Ratio ≤ 2.5 (not parabolic) |
| 7 | `above_vwap` | VWAP | Close > cumulative VWAP |
| 8 | `above_cloud` | Ichimoku | Close > cloud top |
| 9 | `momentum_positive` | ROC(60), ROC(120) | Both > 0 |
| 10 | `cmf_positive` | CMF(21) | CMF > 0 |
| 11 | `weekly_trend_bullish` | Weekly SMA20 + ADX | Weekly close > SMA20 AND weekly ADX > 20 |

**Hard overrides (caps the technical score regardless of condition count):**
- `earnings_safe_window == False` → technical block capped at **2.5 / 5.0** in Phase 7
- `weekly_trend_bullish == False` → technical block capped at **2.0 / 5.0** in Phase 7

**High-Conviction Entry label:** Awarded only when conditions 7, 8, 9, and 11 are ALL True (VWAP, Ichimoku, ROC momentum, and weekly trend all aligned).

**Stop logic:** Initial stop = `entry − 2 × ATR(14)`. If an unfilled upward gap exists within 8% below entry, that gap close level is an alternative stop anchor.
**First target:** `entry + 2 × (entry − stop)` = 2R

---

## Exit Criteria (updated — v1.1)
- Technical score ≥ **6 of 11** bullish conditions (up from 4/6)
- No hard override triggered
- No bearish divergence on momentum + volume near entry
- Weekly trend bullish (hard requirement for full-size entry)
- At least 5 trading days before next earnings announcement

---

*Phase 3 spec version 1.1 | Updated 2026-03-22 | Cross-reference: `PHASED_ANALYSIS_MASTER_PLAN.md` Appendix D*
