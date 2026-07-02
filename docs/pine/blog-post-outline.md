# openbb-extension-pine 0.1.0 — launch post outline

**Status**: draft outline only. Whoever writes the final post fills in prose + screenshots + benchmarks. This is the skeleton with locked claims + code snippets.

**Target audience**: OpenBB users who currently use TradingView for indicators; quant developers who've built ad-hoc Python for Pine-shaped calculations; MCP-tool builders who want a large indicator library exposed to LLMs.

## Suggested title candidates

1. **"Run any Pine Script inside OpenBB — no TradingView account, no SaaS, no vendor lock-in"**
2. **"OpenBB just got 1 million indicators — via the world's first open-source Pine Script compiler"**
3. **"Meet openbb-extension-pine: compile TradingView Pine → Python → your dashboard in one command"**

(Preference: #1 — it's the least hype-y and most information-dense.)

## Section 1 — The problem (1 short paragraph)

- TradingView's Pine Script is the most-used indicator DSL in retail finance
- Currently: Pine scripts are locked to TradingView's platform + charting
- If you want to run a Pine indicator against your own OHLCV data, or through OpenBB Workspace, or expose it to an LLM via MCP, you either (a) copy-translate to Python by hand (slow, error-prone) or (b) pay for the PyneSys SaaS compiler (adds a vendor dependency for what should be a local operation)

## Section 2 — What we built (2 paragraphs + a diagram)

- **openbb-extension-pine 0.1.0**: a first-class OpenBB Platform extension that compiles Pine v5/v6 source to Python and runs it against OHLCV from FMP or your own DataFrame
- Runtime is PyneCore (Apache-2.0, vendored) — proven Pine-semantics execution engine
- Compiler is **clean-room** — written from Pine's public reference manual, never saw PyneComp source, never saw TradingView source
- **Zero third-party SaaS calls** at runtime; **zero API keys beyond what you already have** for OpenBB

Insert a Mermaid diagram showing: Pine source → openbb-pine compiler → @pyne Python → PyneCore runtime → OpenBB OBBject → Workspace/MCP/REST

## Section 3 — Try it in 60 seconds (code)

```bash
pip install openbb-extension-pine
openbb-pine doctor    # health check
```

```python
from openbb import obb

result = obb.pine.run_byo(
    source="//@version=6\nindicator(\"BB\")\nplot(ta.sma(close, 20))",
    records=my_ohlcv_records,
    symbol="AAPL",
)
print(result.results.tail())
```

That's it. `.results` is a pandas.DataFrame; `.extra` carries alerts, cache-hit status, exec time.

## Section 4 — What ships in M1 (bullet-list)

- 36 Pine builtins (list them: ta.sma, ta.rsi, ta.bb, ta.atr, ta.macd, ta.stoch, ta.adx, …)
- Pine v5 scripts run unedited via C7 auto-migration shim
- BYO OHLCV records mode (no FMP needed)
- FMP + fmp_cached provider modes
- Bollinger Bands widget in the Workspace marketplace
- MCP tool registration — LLMs can call Pine indicators as tools
- Compile cache (BLAKE2b, on-disk, ~50ms warm)
- 5-layer security sandbox (T1 codegen allowlist, T2 timeout, T3 restricted exec, T4 cache key, T5 pinned deps)
- `openbb-pine doctor` CLI for install verification

## Section 5 — What's next (M2, brief)

- Pine strategies (`strategy(...)` decls, orders, fills, equity curves, wire into openbb-backtest)
- `request.security` for cross-symbol / cross-timeframe references
- Long-tail builtins driven by wild-corpus usage telemetry
- More providers (yfinance, polygon, tiingo) once v1.x hits its coverage + install-success bars

## Section 6 — The AGPL-3.0 posture (1 short paragraph)

- openbb-extension-pine is AGPL-3.0. PyneCore stays Apache-2.0 (vendored). This means: SaaS deployers who modify the extension must offer the modified source to network users. That's the point.
- If you're a private-deployment user, this is invisible — AGPL §13 only fires on modification+network-service combinations.

## Section 7 — Attribution (required by PyneCore §4(d))

Every one of these surfaces carries the string `"Powered by PyneSys (https://pynesys.io)"`:

- `obb.pine.about().results.powered_by`
- `openbb-pine --version` first line
- `/api/v1/pine/health` JSON `powered_by` field
- Every bundled `pine.*` Workspace widget footer

Not marketing — literal Apache 2.0 §4(d) compliance. See the [PyneCore NOTICE](https://github.com/PyneSys/pynecore/blob/main/NOTICE).

## Section 8 — Get involved

- **Missing a Pine builtin?** File at [github.com/prajoria/OpenBB/issues](https://github.com/prajoria/OpenBB/issues) with label `pine-builtin`. One builtin = one bead = one small PR.
- **v5 script that doesn't migrate?** Label `pine-v5-migration` + minimal repro.
- **Non-FMP provider?** Label `pine-multi-provider`. v2.0 unlocks when v1.x hits (a) wild-corpus coverage ≥ 90 %, (b) install-success ≥ 95 %, (c) ≥ 3 issues requesting a specific provider.

## Section 9 — Credits

- **PyneCore** (Apache-2.0) — © PYNESYS LLC. Powered by PyneSys.
- **openbb-core / openbb-platform** — © OpenBB, Inc. Distributed under AGPL-3.0.
- **openbb-extension-pine** — © prajoria + contributors. Distributed under AGPL-3.0-only.

*Pine Script™ is a trademark of TradingView, Inc. This project is not affiliated with, endorsed by, or sponsored by TradingView.*
