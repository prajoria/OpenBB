# OpenBB Pine — Alpha Quickstart

OpenBB Pine is a **Pine v6 → Python compiler + runtime** that lets you
execute TradingView-style Pine strategies inside OpenBB against your own
records (BYO) or via the FMP data provider. This alpha release ships
end-to-end strategy execution — see
[`PINE_SUPPORTED_FEATURES.md`](./PINE_SUPPORTED_FEATURES.md) for
coverage and known gaps.

## Install / build

```bash
git clone https://github.com/prajoria/OpenBB.git OpenBB-Pine
cd OpenBB-Pine
git switch openbb_pine_support

# Activate the project venv (Windows PowerShell)
.\.venv_win\Scripts\Activate.ps1

# Editable install of platform + all extensions
cd openbb_platform && python dev_install.py -e
```

(See the project `CLAUDE.md` for full environment setup.)

## Run your first strategy — BYO records

Copy-paste-runnable:

```python
from openbb import obb
from datetime import datetime, timezone, timedelta

# 1. Author a Pine v6 strategy
pine_source = """//@version=6
strategy("SMA Crossover", overlay=true, initial_capital=100000)
fast = ta.sma(close, 10)
slow = ta.sma(close, 30)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
plot(fast, "Fast", color=color.blue)
plot(slow, "Slow", color=color.orange)
"""

# 2. Supply OHLCV records (list of dicts with a 'date' key)
records = [
    {
        "date": datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
        "open": 100.0 + i * 0.5,
        "high": 101.0 + i * 0.5,
        "low": 99.0 + i * 0.5,
        "close": 100.5 + i * 0.5,
        "volume": 1000.0,
    }
    for i in range(500)  # 500 bars
]

# 3. Run it
result = obb.pine.strategies.run_byo(
    source=pine_source,
    records=records,
    symbol="BYO_DEMO",
)

# 4. Inspect the results
print("Script type:", result.extra["script_type"])           # 'strategy'
print("Net profit:", result.extra["stats"]["net_profit"])
print("Closed trades:", result.extra["stats"]["closed_trades"])
print("Equity curve length:", len(result.extra["equity_curve"]))
print("First order:", result.extra["orders"][0] if result.extra["orders"] else "none")
```

## Or use FMP-provided data — provider mode

Same source, just swap the entry-point:

```python
result = obb.pine.strategies.run(
    source=pine_source,
    provider="fmp_cached",
    symbol="AAPL",
    interval="1d",
    start="2024-01-01",
    end="2024-12-31",
)
```

`fmp_cached` credentials are auto-loaded from
`~/.openbb_platform/user_settings.json`.

## What's in `result.extra`

| Key | Type | What |
|-----|------|------|
| `script_type` | `str` | `'strategy'` or `'indicator'` |
| `stats` | `dict` | Pine strategy KPIs: `net_profit`, `gross_profit`, `sharpe_ratio`, `max_drawdown`, `closed_trades`, … |
| `equity_curve` | `list` | Per-bar equity snapshots: `[{bar_index, equity, drawdown}, …]` |
| `orders` | `list` | `TradeSummary` per completed trade (`id`, `direction`, `qty`, `pnl`, …) |
| `alerts` | `list` | `alert()` calls fired by the script |
| `attribution` | `str` | Upstream attribution string (PyneSys) |

There is also a sibling `obb.pine.indicators.run` / `run_byo` for
indicator-only scripts; the strategy endpoints are the alpha's headline.

## Known limitations

See [`PINE_SUPPORTED_FEATURES.md`](./PINE_SUPPORTED_FEATURES.md) for the
authoritative supported-features list and current gaps.

## Reporting bugs / questions

File a bd issue:

```bash
bd create --title="<short description>" --type=bug --priority=2
```

…or open a GitHub issue on the openbb-fork with the `pine-alpha` label.
Please include: the Pine source, a minimal sample of records (if using
BYO), the actual OBBject output, and what you expected.
