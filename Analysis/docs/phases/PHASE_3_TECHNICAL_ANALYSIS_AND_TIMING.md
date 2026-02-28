# Phase 3: Technical Analysis & Trade Timing

## Objective
Use technicals to time entries/exits after the business passes fundamentals.

## Analysis Frames
- Regime frame: weekly chart (trend context)
- Execution frame: daily chart (entry timing)
- Optional refinement: 4-hour chart for swing setups

## Indicator Stack (exact)

### A) Trend KPIs
| KPI | Why it matters (simple) | Actionable interpretation | Example |
|---|---|---|---|
| SMA 50 vs SMA 200 | Shows medium vs long trend direction | 50 above 200 = bullish regime | “Golden cross” supports buying pullbacks, not breakouts blindly. |
| Price vs SMA 200 | Tells if stock is in long-term uptrend | Price above 200DMA preferred | If price is below 200DMA, position size should be smaller. |
| ADX (14) | Measures trend strength, not direction | > 25 strong trend, < 20 range | ADX 30 + rising = trend-following works better. |

### B) Momentum KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| RSI (14) | Detects overbought/oversold state | In uptrends, buy RSI pullback to 40–50 | RSI at 78 is not auto-sell if trend/volume are strong. |
| MACD line vs signal | Momentum acceleration/deceleration | Bullish cross above zero is strongest | Cross below zero in weak breadth often warns of deeper pullback. |
| Stochastic (14,3,3) | Short-cycle momentum turns | Cross up below 20 suggests rebound potential | Useful for timing entries in range-bound periods. |

### C) Volatility & Risk KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| ATR (14) | Typical move size; helps stops | Initial stop = entry - 2×ATR | ATR $2 means a $4 stop from entry baseline. |
| Bollinger Band Width | Volatility compression/expansion | Squeeze + breakout can start trend leg | Narrowest band in 6 months then upside break = expansion setup. |

### D) Volume Confirmation KPIs
| KPI | Why it matters | Actionable interpretation | Example |
|---|---|---|---|
| OBV slope (20D) | Confirms if volume supports trend | Rising OBV with rising price = healthy | Price up but OBV flat warns weak participation. |
| Breakout Volume Ratio | Validates breakout quality | Breakout day volume > 1.5× 20D avg | Low-volume breakout has higher failure chance. |

## Programmatic Pull

```python
ft_ta = Toolkit([SYMBOL], api_key=API_KEY, start_date="2024-01-01", end_date=END_DATE)
tech = ft_ta.technicals

rsi = tech.get_relative_strength_index()
macd = tech.get_moving_average_convergence_divergence()
adx = tech.get_average_directional_index()
bb = tech.get_bollinger_bands()
atr = tech.get_average_true_range()
obv = tech.get_on_balance_volume()
all_indicators = tech.collect_all_indicators()
```

## Trade Setup Checklist
- Trend regime bullish (`SMA50 > SMA200`)
- ADX ≥ 20 and rising
- Entry on pullback (RSI 40–55) or confirmed breakout (volume ratio > 1.5x)
- Initial stop at `2 × ATR`
- First take-profit at `2R` (reward twice risk)

## Exit Criteria
- Technical score ≥ 4/6 bullish factors
- No bearish divergence on momentum + volume near entry
