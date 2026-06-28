# 01 — Scaffolding & Package Layout

**GitHub:** [#38](https://github.com/prajoria/OpenBB/issues/38) · **Depends on:** — (foundation)
**Beads:** OpenBB-4ys, OpenBB-g1m, OpenBB-lpy, OpenBB-ufl

Defines the on-disk skeleton, packaging, router registration, config plumbing, and build
workflow that every other component plugs into.

---

## 1. Package directory tree

```
openbb_platform/extensions/backtest/
├── openbb_backtest/
│   ├── __init__.py               # version, public re-exports
│   ├── backtest_router.py        # top-level Router; includes sub-routers
│   ├── models.py                 # Pydantic Data models (component 02)
│   ├── interfaces.py             # Protocols: Strategy/Engine/Broker/DataFeed (02)
│   ├── helpers.py                # df<->Data plumbing, alignment, returns
│   ├── settings.py               # BacktestSettings (config plumbing, §4)
│   ├── registry.py               # strategy + engine registries
│   ├── py.typed
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── base.py               # Engine ABC implementing interfaces.Engine
│   │   ├── vectorized.py         # in-house NumPy/Numba engine (04)
│   │   ├── event_driven.py       # zipline-reloaded sim wrapper (05)
│   │   ├── reconcile.py          # cross-engine agreement gate
│   │   └── execution.py          # slippage/commission/fill/borrow (06)
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── factor.py             # Factor node base
│   │   └── engine.py             # cross-sectional compute
│   ├── data/
│   │   ├── __init__.py
│   │   ├── bundle.py             # fmp_cached bundle ingest (03)
│   │   └── calendars.py          # exchange_calendars wrapper
│   ├── analytics/                # empyrical/pyfolio/quantstats wrappers (07)
│   ├── validation/               # WFO / CPCV / PBO / DSR (08)
│   ├── adapters/                 # OPTIONAL engines (11): vectorbt, backtrader, spectre
│   │   ├── __init__.py
│   │   ├── _optional.py          # import-guard helper
│   │   ├── vectorbt_adapter.py
│   │   ├── backtrader_adapter.py
│   │   └── spectre_adapter.py
│   └── strategies/               # curated reference library (10)
├── tests/
│   ├── unit/                     # no DB, no network
│   ├── integration/              # FMP_CACHE_TEST_MODE=true
│   └── golden/                   # golden-file fixtures + expected results
├── README.md
└── pyproject.toml
```

**Module-boundary rules**

- `interfaces.py` and `models.py` have **no intra-package imports** (leaf modules) so every
  other module can depend on them without cycles.
- `engine/`, `data/`, `analytics/`, `validation/`, `pipeline/` depend only on
  `models`, `interfaces`, `helpers`, `settings`.
- `adapters/` may import optional third-party engines **only** behind the import-guard in
  `adapters/_optional.py`; nothing in core imports `adapters/` at module load time.
- `backtest_router.py` is the only module that wires sub-routers together.

---

## 2. pyproject entry point + extras matrix

```toml
[tool.poetry]
name = "openbb-backtest"
packages = [{ include = "openbb_backtest" }]

[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-core = "*"
numpy = "*"
numba = "*"
pandas = "*"
exchange-calendars = "*"          # Apache-2.0 (core)
empyrical-reloaded = "*"          # Apache-2.0 (core)
pyfolio-reloaded = "*"            # Apache-2.0 (core)
alphalens-reloaded = "*"          # Apache-2.0 (core)
quantstats = "*"                  # Apache-2.0 (core)
zipline-reloaded = "*"            # Apache-2.0 (core, event-driven)
bt = "*"                          # MIT (allocation tests)
ffn = "*"                         # MIT (util)

[tool.poetry.extras]
vectorbt = ["vectorbt"]           # Commons Clause — opt-in, MUST stay non-vendored
backtrader = ["backtrader"]       # GPL-3.0 — AGPL-OK; opt-in for dependency weight
gpu = ["cupy", "spectre"]         # MIT/Apache — opt-in GPU backend + factor engine (component 13)

[tool.poetry.plugins."openbb_core_extension"]
backtest = "openbb_backtest.backtest_router:router"
```

**License guard (enforced in CI, see component 11/12):** a test asserts that no module under
`openbb_backtest/` (excluding `adapters/`) imports `vectorbt` or `pybroker`, and that their
source is never present in the tree.

---

## 3. Router registration + lazy-import pattern

```python
# backtest_router.py
from openbb_core.app.router import Router

router = Router(prefix="", description="Backtesting engine")

# Sub-routers are imported lazily inside register() to keep heavy deps
# (zipline) out of `import openbb` time.
def _include_subrouters() -> None:
    from openbb_backtest.routers.run_router import router as run_router
    from openbb_backtest.routers.factor_router import router as factor_router
    from openbb_backtest.routers.validate_router import router as validate_router
    from openbb_backtest.routers.bundle_router import router as bundle_router
    router.include_router(run_router)
    router.include_router(factor_router)
    router.include_router(validate_router)
    router.include_router(bundle_router)

_include_subrouters()
```

- Command functions import their engine **inside the function body**, not at module top, so
  `import openbb` never triggers a zipline/numba import.
- Optional adapters are resolved through `adapters/_optional.py` only when an engine is
  explicitly selected (`engine="vectorbt"`).

---

## 4. Config plumbing

```python
# settings.py
from pydantic_settings import BaseSettings

class BacktestSettings(BaseSettings):
    default_calendar: str = "XNYS"
    default_engine: str = "auto"
    reconcile_tolerance: float = 1e-6
    seed: int = 0
    export_dir: str = "Analysis/exports"
    class Config:
        env_prefix = "OPENBB_BACKTEST_"
```

- **Database access reuses** `openbb_fmp_cached/utils/database.py::DatabaseConfig` — no new
  secrets, honors `FMP_CACHE_TEST_MODE`. The bundle (component 03) receives a `DatabaseConfig`
  instance; the extension never constructs its own connection string.
- API credentials continue to resolve from `~/.openbb_platform/user_settings.json` / env.

---

## 5. Build / rebuild workflow

```powershell
# one-time, from repo root, inside .venv_win
cd openbb_platform; python dev_install.py -e          # editable install incl. new extension
python -c "import openbb; openbb.build()"             # regenerate obb.backtest.* surface
# verify
python -c "from openbb import obb; print(hasattr(obb, 'backtest'))"   # -> True
```

Optional engines are installed on demand:

```powershell
pip install -e ".[vectorbt]"     # non-vendored Commons-Clause accelerator
pip install -e ".[backtrader]"   # GPL adapter
pip install -e ".[gpu]"          # cupy + spectre — GPU backend (component 13)
```

---

## Acceptance mapping (#38)

| Acceptance criterion | Satisfied by |
|---|---|
| Documented package tree | §1 |
| Entry-point registration spec | §2 (`openbb_core_extension`), §3 |
| Extras groups (core, zipline, adapters) defined | §2 extras matrix |
| Build/rebuild steps (dev_install -e + openbb.build) | §5 |
| Module-boundary / no-cycle rules | §1 module-boundary rules |
| License guard (no vendored Commons-Clause) | §2 license guard |
