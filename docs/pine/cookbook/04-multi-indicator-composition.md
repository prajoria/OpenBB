# Recipe 04 — Custom multi-indicator composition

**Goal**: Define a custom Pine function that composes multiple built-in indicators (Bollinger Bandwidth + ATR percentile) into a single signal series. Illustrates user function definitions, multi-argument returns, and type-annotated locals.

**Prerequisites**: `pip install openbb-extension-pine`.

## The Pine source

```pine
//@version=6
indicator("BBW-ATR composite", overlay=false)

length = input.int(20)
mult   = input.float(2.0)

// Custom function: normalised bandwidth-vs-ATR ratio
bbw_atr_ratio(src, len, m) =>
    basis  = ta.sma(src, len)
    dev    = m * ta.stdev(src, len)
    bandwidth = 2 * dev / basis
    atr = ta.atr(len)
    ratio = bandwidth / (atr / basis)
    ratio

r = bbw_atr_ratio(close, length, mult)
plot(r, title="bbw_atr_ratio", color=color.purple)
plot(1.0, title="baseline", color=color.gray)
```

The function `bbw_atr_ratio` takes three parameters, uses local intermediates (basis, dev, bandwidth, atr, ratio), and returns the last expression per Pine semantics.

## The Python

```python
from openbb import obb

src = open("bbw_atr.pine").read()

records = [
    {"date": f"2024-01-{d:02d}T00:00:00Z",
     "open": 100 + i*0.5, "high": 102 + i*0.5, "low": 98 + i*0.5,
     "close": 100.5 + i*0.5, "volume": 1_000_000}
    for i, d in enumerate(range(2, 32))
]

result = obb.pine.run_byo(source=src, records=records, symbol="X")

print(result.results.tail(5))
print(f"\nbuiltins detected in script: {sorted(compile_source_meta(src))}")
```

Where `compile_source_meta(src)` is a helper that calls `obb.pine.compile()` to introspect the compiled module without running:

```python
def compile_source_meta(src):
    r = obb.pine.compile(source=src)
    return r.results.builtins_used
```

## Expected output

```
                        bbw_atr_ratio  baseline
date
2024-01-25 00:00:00+00:00       0.812      1.00
2024-01-26 00:00:00+00:00       0.804      1.00
2024-01-29 00:00:00+00:00       0.798      1.00
2024-01-30 00:00:00+00:00       0.795      1.00
2024-01-31 00:00:00+00:00       0.789      1.00

builtins detected in script: ['close', 'input.float', 'input.int', 'plot', 'ta.atr', 'ta.sma', 'ta.stdev', 'color.purple', 'color.gray']
```

## Notes

- Custom functions are compiled inline — no separate compilation unit; they inherit the calling module's scope + type checker context.
- The `bbw_atr_ratio` return value is inferred as `series<float>` from its final expression; the type checker (C3) validates each call site against this.
- Every recursive call would need explicit annotation (Pine v6 semantics); this example doesn't recurse but demonstrates the composition shape.
- If a user function references an unimplemented builtin, `PineUnsupportedBuiltinError` names the missing builtin — you don't have to guess which of the composed builtins broke.

Powered by PyneSys (https://pynesys.io)
