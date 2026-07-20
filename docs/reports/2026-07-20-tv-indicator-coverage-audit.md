# TradingView 31-Indicator Coverage Audit

- **Generated:** 2026-07-20T01:03:43.152037Z
- **Basket size:** 21 symbols (representative)
- **Fetched:** 21/21 tickers
- **Provider:** `fmp_cached` (400 days, 1d interval)
- **Issue:** #780

## Coverage Matrix (Source)

| # | Indicator | Category | Source | Coverage (ok / total) |
|---|---|---|---|---|
| 1 | RSI(14) | oscillator | pandas_ta_classic | 21/21 |
| 2 | Stochastic %K(14,3,3) | oscillator | pandas_ta_classic | 21/21 |
| 3 | CCI(20) | oscillator | pandas_ta_classic | 21/21 |
| 4 | ADX(14) | oscillator | pandas_ta_classic | 21/21 |
| 5 | Awesome Oscillator | oscillator | pandas_ta_classic | 21/21 |
| 6 | Momentum(10) | oscillator | pandas_ta_classic | 21/21 |
| 7 | MACD(12,26) | oscillator | pandas_ta_classic | 21/21 |
| 8 | Stochastic RSI Fast(3,3,14,14) | oscillator | pandas_ta_classic | 21/21 |
| 9 | Williams %R(14) | oscillator | pandas_ta_classic | 21/21 |
| 10 | Bull Bear Power | oscillator | custom (EMA + high/low delta) | 21/21 |
| 11 | Ultimate Oscillator(7,14,28) | oscillator | pandas_ta_classic | 21/21 |
| 12 | EMA(10) | moving_average | pandas_ta_classic | 21/21 |
| 13 | EMA(20) | moving_average | pandas_ta_classic | 21/21 |
| 14 | EMA(30) | moving_average | pandas_ta_classic | 21/21 |
| 15 | EMA(50) | moving_average | pandas_ta_classic | 21/21 |
| 16 | EMA(100) | moving_average | pandas_ta_classic | 21/21 |
| 17 | EMA(200) | moving_average | pandas_ta_classic | 21/21 |
| 18 | SMA(10) | moving_average | pandas_ta_classic | 21/21 |
| 19 | SMA(20) | moving_average | pandas_ta_classic | 21/21 |
| 20 | SMA(30) | moving_average | pandas_ta_classic | 21/21 |
| 21 | SMA(50) | moving_average | pandas_ta_classic | 21/21 |
| 22 | SMA(100) | moving_average | pandas_ta_classic | 21/21 |
| 23 | SMA(200) | moving_average | pandas_ta_classic | 21/21 |
| 24 | Ichimoku Kijun-sen(9,26,52,26) | moving_average | pandas_ta_classic | 21/21 |
| 25 | VWMA(20) | moving_average | pandas_ta_classic | 21/21 |
| 26 | HMA(9) | moving_average | pandas_ta_classic | 21/21 |
| 27 | Pivot: Classic | pivot | custom (pandas math) | 21/21 |
| 28 | Pivot: Fibonacci | pivot | custom (pandas math) | 21/21 |
| 29 | Pivot: Camarilla | pivot | custom (pandas math) | 21/21 |
| 30 | Pivot: Woodie | pivot | custom (pandas math) | 21/21 |
| 31 | Pivot: DeMark | pivot | custom (pandas math) | 21/21 |

## Per-Ticker × Indicator Detail

| Indicator | SPY | DIA | XLK | XLF | XLE | XLV | XLI | XLP | XLY | XLB | XLU | XLRE | XLC | AAPL | MSFT | NVDA | JPM | XOM | JNJ | PG | HD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSI(14) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stochastic %K(14,3,3) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CCI(20) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ADX(14) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Awesome Oscillator | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Momentum(10) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| MACD(12,26) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stochastic RSI Fast(3,3,14,14) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Williams %R(14) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bull Bear Power | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ultimate Oscillator(7,14,28) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EMA(10) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EMA(20) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EMA(30) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EMA(50) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EMA(100) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EMA(200) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMA(10) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMA(20) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMA(30) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMA(50) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMA(100) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMA(200) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ichimoku Kijun-sen(9,26,52,26) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VWMA(20) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| HMA(9) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pivot: Classic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pivot: Fibonacci | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pivot: Camarilla | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pivot: Woodie | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pivot: DeMark | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Legend: ✅ ok · ⏳ insufficient history · ❌ no OHLCV · ⚠️ empty output · 🔥 exception

## Category Totals

| Category | Indicators | Fully-covered (all tickers ok) | Partial | None |
|---|---|---|---|---|
| oscillator | 11 | 11 | 0 | 0 |
| moving_average | 15 | 15 | 0 | 0 |
| pivot | 5 | 5 | 0 | 0 |

## Missing Indicators (0 tickers covered)

*None — every indicator has at least one successful ticker.*
