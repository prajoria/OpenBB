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
& ".venv_win\Scripts\python.exe" -m pytest openbb_platform/extensions/backtest/tests/unit -v
```

## Build (when ready)

```powershell
cd openbb_platform; python dev_install.py -e
python -c "import openbb; openbb.build()"
python -c "from openbb import obb; print(hasattr(obb, 'backtest'))"
```
