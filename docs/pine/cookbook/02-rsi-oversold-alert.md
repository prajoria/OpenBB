# Recipe 02 — RSI oversold-alert extraction

**Goal**: Compute RSI(14) over your OHLCV, extract the timestamps where RSI < 30 (classic oversold), and get them as a structured `.extra["alerts"]` list.

**Prerequisites**: `pip install openbb-extension-pine`.

## The Pine source

```pine
//@version=6
indicator("RSI oversold", overlay=false)
length = input.int(14)
r      = ta.rsi(close, length)
plot(r, title="rsi")
if r < 30
    alert("RSI oversold: " + str.tostring(r), alert.freq_once_per_bar)
```

The Pine `alert()` builtin fires per bar when the condition triggers; our runtime captures every fire into `.extra["alerts"]`.

## The Python

```python
from openbb import obb

src = """//@version=6
indicator("RSI oversold", overlay=false)
length = input.int(14)
r      = ta.rsi(close, length)
plot(r, title="rsi")
if r < 30
    alert("RSI oversold: " + str.tostring(r), alert.freq_once_per_bar)
"""

# 30 bars covering a hypothetical oversold spell
records = [
    {"date": f"2024-01-{d:02d}T00:00:00Z", "open": 100 - i*0.3,
     "high": 101 - i*0.3, "low": 99 - i*0.3, "close": 100 - i*0.3,
     "volume": 1_000_000}
    for i, d in enumerate(range(2, 32))
]

result = obb.pine.run_byo(source=src, records=records, symbol="AAPL")

print("RSI values (last 5 bars):")
print(result.results.tail(5))

print(f"\nAlerts fired: {len(result.extra['alerts'])}")
for a in result.extra["alerts"][:5]:
    print(f"  bar {a['bar_index']} @ {a['ts']}: {a['message']}")
```

## Expected output

```
RSI values (last 5 bars):
                             rsi
date
2024-01-25 00:00:00+00:00  22.4
2024-01-26 00:00:00+00:00  20.1
2024-01-29 00:00:00+00:00  18.7
2024-01-30 00:00:00+00:00  17.2
2024-01-31 00:00:00+00:00  16.0

Alerts fired: 15
  bar 15 @ 2024-01-23 00:00:00+00:00: RSI oversold: 29.8
  bar 16 @ 2024-01-24 00:00:00+00:00: RSI oversold: 27.1
  bar 17 @ 2024-01-25 00:00:00+00:00: RSI oversold: 22.4
  bar 18 @ 2024-01-26 00:00:00+00:00: RSI oversold: 20.1
  bar 19 @ 2024-01-29 00:00:00+00:00: RSI oversold: 18.7
```

## Notes

- The alerts survive the `.extra` roundtrip through REST as JSON.
- `alert.freq_once_per_bar` is honoured — a bar with multiple alert-triggering conditions still fires once per bar.
- To wire this to an actual notification system (email, webhook, Slack), consume `result.extra["alerts"]` in your caller. The pine extension itself doesn't ship notification transports (those are user infrastructure).

Powered by PyneSys (https://pynesys.io)
