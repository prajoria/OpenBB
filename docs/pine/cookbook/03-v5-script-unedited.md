# Recipe 03 — Pine v5 script running unmodified

**Goal**: Take a real-world Pine v5 script (the language version most TradingView community scripts still use as of 2026) and run it unchanged through openbb-extension-pine. The C7 auto-migration shim rewrites the v5→v6 differences at source-load time.

**Prerequisites**: `pip install openbb-extension-pine`.

## The Pine v5 source (unchanged)

```pine
//@version=5
study("v5 study — momentum flip", overlay=true)
fast = ta.sma(close, 10)
slow = ta.sma(close, 30)
signal = iff(fast > slow, 1, iff(fast < slow, -1, 0))
plot(fast, "fast", color=color.blue)
plot(slow, "slow", color=color.orange)
```

Three v5-isms this script uses that don't compile in v6:

1. `study(...)` — renamed to `indicator(...)` in v6
2. `iff(cond, a, b)` — replaced by the ternary `cond ? a : b`
3. Nested `iff` — same

## The Python (same call — v5 or v6, doesn't matter)

```python
from openbb import obb

src = open("v5_momentum.pine").read()

records = [
    {"date": f"2024-01-{d:02d}T00:00:00Z",
     "open": 100 + i, "high": 101 + i, "low": 99 + i,
     "close": 100.5 + i, "volume": 1_000_000}
    for i, d in enumerate(range(2, 40))
]

result = obb.pine.run_byo(source=src, records=records, symbol="AAPL")

print(result.results.tail(5))
print("Compiled Pine version:",
      "5 (migrated to 6 via C7 shim)" if "//@version=5" in src else "6")
```

## What happens under the hood

1. `compile_pine()` reads the `//@version=5` pragma.
2. C7 migration shim applies rewrites:
   - `study("v5 study — momentum flip", overlay=true)` → `indicator("v5 study — momentum flip", overlay=true)`
   - `iff(fast > slow, 1, iff(fast < slow, -1, 0))` → `(fast > slow ? 1 : (fast < slow ? -1 : 0))`
3. Rewritten source parses with the v6 grammar; codegen emits `@pyne` Python; PyneCore runs it.
4. Output shape identical to a hand-migrated v6 version.

## Rewrites C7 handles today

| v5 | v6 |
|---|---|
| `study(...)` | `indicator(...)` |
| `iff(cond, a, b)` (3-arg simple-expr form) | `(cond ? a : b)` |
| `tickerid(...)` | `ticker.new(...)` |
| `security(...)` (top-level) | `request.security(...)` |
| `plot(..., transp=N, ...)` | `plot(...)` (transp stripped; opacity flows through `color.new()`) |
| `//@version=5` pragma | `//@version=6` |

Unsupported v5 constructs raise `PineUnsupportedFeatureError` with code `PF003` and a tracking-URL for filing new rewrites.

## Notes

- The migration is source-level, not IR-level. If you want to see the migrated source, use `obb.pine.compile()` (which returns the emitted Python after the full lex+parse+typecheck+codegen pipeline).
- The **cache key** includes the raw source (pre-migration), so v5 and v6 forms of the same script get distinct cache slots. Cross-version cache aliasing was a deliberate no-op — v5 and v6 emit slightly different Python.

Powered by PyneSys (https://pynesys.io)
