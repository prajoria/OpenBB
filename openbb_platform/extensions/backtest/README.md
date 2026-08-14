# OpenBB Backtest Extension

Backtesting engine for the OpenBB Platform. Implements the design documented in
[`docs/designs/backtest-design/`](../../../docs/designs/backtest-design/).

## Status

Foundation implemented (pure-Python, no heavy dependencies):

- Package scaffolding & router registration (component 01)
- Core data models & interface protocols (component 02)
- Execution realism model — commission / slippage / fills / constraints (component 06)

Engines (vectorized, event-driven), data bundle, analytics, validation, strategy
library, adapters and the GPU compute backend are tracked as separate
implementation issues and require their respective heavy dependencies.

## Layout

```
openbb_backtest/
  backtest_router.py   # top-level Router
  models.py            # Pydantic Data models
  interfaces.py        # Strategy / Engine / Broker / DataFeed protocols
  helpers.py           # df <-> Data plumbing
  settings.py          # BacktestSettings
  registry.py          # strategy + engine registries
  engine/execution.py  # commission / slippage / fills / constraints
  engine/ data/ pipeline/ analytics/ validation/ adapters/ strategies/
tests/
  unit/                # no DB, no network
  integration/         # FMP_CACHE_TEST_MODE=true
  golden/              # golden-file fixtures
```

## Testing (pre-install)

Until the extension is installed editable (`dev_install.py -e`), unit tests run
against the source tree via the `conftest.py` sys.path shim:

```powershell
& ".venv_portfolio\Scripts\python.exe" -m pytest openbb_platform/extensions/backtest/tests/unit -v
```

## Top-50 Intraday Drift Study

Measure how often the top-50 S&P 500 constituents by index weight close higher
at the 16:00 ET session close than they opened at 12:00 ET (09:00 PT → 13:00 PT):

```powershell
& ".venv_portfolio\Scripts\python.exe" openbb_platform/extensions/backtest/examples/top50_intraday_drift.py
```

> **Data-availability warning.** The study uses Yahoo Finance **30-minute** bars
> (`interval="30m"`), because Yahoo anchors intraday bars to the 09:30 ET open —
> its 60-minute grid is `09:30, 10:30, 11:30, 12:30, ...` and contains **no
> 12:00 bar**. Yahoo retains only **~60 calendar days** of 30-minute history, so
> the default `--months 6` run **fails loudly** with an `INCOMPLETE WINDOW`
> error instead of silently reporting a two-month sample as a six-month answer.
> Pass `--allow-partial-window` to accept a clearly labelled best-effort result
> covering only the dates the provider actually served.

Optional arguments:

```
--top N                  Number of top-weighted S&P 500 symbols (default: 50)
--months M               Requested look-back in calendar months (default: 6)
--allow-partial-window   Accept a shorter window than requested; the report is
                         labelled PARTIAL WINDOW and must not be quoted as a
                         full-window result
--csv PATH               Write observation rows (not raw bars) to a CSV file
```

Example:

```powershell
& ".venv_portfolio\Scripts\python.exe" `
    openbb_platform/extensions/backtest/examples/top50_intraday_drift.py `
    --top 50 --months 6 --allow-partial-window --csv drift_observations.csv
```

**Warnings:**
- *Partial window* — with Yahoo as the source, any multi-month request is served
  from ~60 days of data. Always read the actual first/last session printed in
  the report; never quote a `PARTIAL WINDOW` run as a six-month result.
- *Survivorship bias* — constituents are the current S&P 500 list (fetched
  at run-time from Slickcharts). Companies that **left** the index during the
  study window are excluded; companies that **joined** after the window started
  are included.
- *No transaction costs* — entry price is the adjusted open of the **12:00 ET**
  30-minute bar (09:00 PT); exit price is the adjusted close of the **15:30 ET**
  30-minute bar (the 16:00 ET session close, 13:00 PT). Bid-ask spread,
  commission, and market-impact are not modelled.
- *No currently-forming bars* — a session is only counted once its 15:30-16:00
  ET exit interval has finished.

## Build (when ready)

```powershell
cd openbb_platform; python dev_install.py -e
python -c "import openbb; openbb.build()"
python -c "from openbb import obb; print(hasattr(obb, 'backtest'))"
```
