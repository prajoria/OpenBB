# Recipe 01 — Bollinger Bands on BYO OHLCV

**Goal**: Render a Bollinger Bands indicator over your own OHLCV bars, no FMP key required. This is the simplest possible end-to-end use of `obb.pine.run_byo()`.

**Prerequisites**: `pip install openbb-extension-pine`. Run `openbb-pine doctor` to verify the install.

## The Pine source

Paste this into `bb.pine` (or hold it inline as a string):

```pine
//@version=6
indicator("BB", overlay=true)
length = input.int(20)
mult   = input.float(2.0)
basis  = ta.sma(close, length)
dev    = mult * ta.stdev(close, length)
plot(basis, title="basis")
plot(basis + dev, title="upper")
plot(basis - dev, title="lower")
```

## The Python

```python
from openbb import obb

src = open("bb.pine").read()

records = [
    {"date": "2024-01-02T00:00:00Z", "open": 184.1, "high": 186.4,
     "low": 183.9, "close": 185.6, "volume": 52341900},
    {"date": "2024-01-03T00:00:00Z", "open": 185.6, "high": 187.0,
     "low": 184.2, "close": 186.8, "volume": 48200100},
    # ... at least `length` (20) bars for the SMA to warm up
]

result = obb.pine.run_byo(
    source=src,
    records=records,
    symbol="AAPL",
)

print(result.results.tail(5))
```

## Expected output

```
                           basis   upper   lower
date
2024-01-24 00:00:00+00:00  188.5   194.7   182.3
2024-01-25 00:00:00+00:00  188.9   195.2   182.6
2024-01-26 00:00:00+00:00  189.3   195.7   182.9
2024-01-29 00:00:00+00:00  189.7   196.2   183.2
2024-01-30 00:00:00+00:00  190.1   196.7   183.5
```

Plus `.extra`:

```python
{'alerts': [], 'orders': [], 'attribution': 'Powered by PyneSys (https://pynesys.io)',
 'compile_cache_hit': False, 'exec_ms': 42, 'provider_used': 'byo', 'bars_consumed': 20}
```

## Notes

- The first call is a cache miss. The second call with the same source will show `compile_cache_hit: True` and `exec_ms` an order of magnitude smaller — the compile cache under `~/.openbb/pine_cache/` skips the entire compile pipeline.
- The `title=` argument on each `plot()` becomes the DataFrame column name. Untitled `plot()` calls get `plot_0`, `plot_1`, etc.
- To render this as an OpenBB Workspace widget instead of a Python script, use the bundled Bollinger Bands widget (see `obb.pine.indicators.list()` after install).

Powered by PyneSys (https://pynesys.io)
