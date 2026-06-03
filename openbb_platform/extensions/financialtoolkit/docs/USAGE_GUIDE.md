# FinancialToolkit Extension Usage Guide

## Overview

The FinancialToolkit extension exposes FinanceToolkit analytics through OpenBB-native commands under:

- `obb.financialtoolkit.models.*`
- `obb.financialtoolkit.options.*`
- `obb.financialtoolkit.risk.*`
- `obb.financialtoolkit.performance.*`
- `obb.financialtoolkit.discovery.*`

## Prerequisites

- OpenBB Platform environment available.
- FinancialToolkit dependency installed (configured as extension dependency).
- For most model/risk/performance/discovery methods: valid FMP API key.

## Maintenance Checklist

- Keep examples aligned with currently implemented commands in `docs/COMMAND_COVERAGE_MATRIX.md`.
- Use the matrix jump table: [Quick Start Links](COMMAND_COVERAGE_MATRIX.md#quick-start-links).
- When adding a command, add at least one runnable snippet in the matching domain section.
- If a parameter contract changes, update both this guide and `examples/financialtoolkit_usage_example.ipynb` in the same PR.
- Prefer minimal, copy-paste-safe examples that return an `OBBject` and (when useful) show `.to_df()` conversion.

## Quick Health Check

<a id="health-check"></a>

```python
from openbb import obb

about = obb.financialtoolkit.about()
about
```

Expected fields:
- `extension_name`
- `extension_version`
- `toolkit_installed`
- `toolkit_version`

## Core Usage Patterns

### 1) Models

<a id="models-examples"></a>

```python
from openbb import obb

symbols = ["AAPL", "MSFT"]
api_key = "YOUR_FMP_KEY"

altman = obb.financialtoolkit.models.altman_z_score(
    symbols=symbols,
    api_key=api_key,
    period="yearly" if False else None,
)

piotroski = obb.financialtoolkit.models.piotroski_score(
    symbols=symbols,
    api_key=api_key,
)

dupont = obb.financialtoolkit.models.dupont(
    symbols=symbols,
    api_key=api_key,
)

wacc = obb.financialtoolkit.models.wacc(
    symbols=symbols,
    api_key=api_key,
)

intrinsic = obb.financialtoolkit.models.intrinsic_value(
    symbols=["AAPL"],
    growth_rate=0.05,
    perpetual_growth_rate=0.025,
    weighted_average_cost_of_capital=0.09,
    api_key=api_key,
)
```

### 2) Options (Greeks)

<a id="options-examples"></a>

```python
greeks = obb.financialtoolkit.options.greeks(
    symbols=["AAPL"],
    api_key=api_key,
    strike_price_range=0.25,
    strike_step_size=5,
    expiration_time_range=30,
)
```

### 3) Risk

<a id="risk-examples"></a>

```python
var_data = obb.financialtoolkit.risk.var(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
    alpha=0.05,
)

cvar_data = obb.financialtoolkit.risk.cvar(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
    alpha=0.05,
)

evar_data = obb.financialtoolkit.risk.evar(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
    alpha=0.05,
)

garch_data = obb.financialtoolkit.risk.garch(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
)
```

### 4) Performance

<a id="performance-examples"></a>

```python
sharpe = obb.financialtoolkit.performance.sharpe_ratio(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
)

sortino = obb.financialtoolkit.performance.sortino_ratio(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
)

info_ratio = obb.financialtoolkit.performance.information_ratio(
    symbols=symbols,
    api_key=api_key,
    period="yearly",
)
```

### 5) Discovery

<a id="discovery-examples"></a>

```python
screened = obb.financialtoolkit.discovery.screen(
    api_key=api_key,
    market_cap_higher=5_000_000_000,
    price_higher=5,
    is_etf=False,
)

search = obb.financialtoolkit.discovery.search(
    api_key=api_key,
    query="META",
    search_method="name",
)
```

## Working With Results

All commands return an OpenBB `OBBject`.

```python
df = obb.financialtoolkit.models.altman_z_score(
    symbols=["AAPL"],
    api_key=api_key,
).to_df()

df.head()
```

## Troubleshooting

- **`toolkit_installed=False`** in `about()`:
  - Ensure FinancialToolkit dependency is installed in the active environment.
- **API-related failures**:
  - Verify `api_key` value and plan limitations.
- **No intraday support for some risk periods**:
  - Use supported periods (`weekly`, `monthly`, `quarterly`, `yearly`) unless intraday data is available.

## Related Files

- Coverage matrix: `docs/COMMAND_COVERAGE_MATRIX.md`
- Design and implementation plan: `docs/IMPLEMENTATION_PLAN.md`
- Example notebook: `examples/financialtoolkit_usage_example.ipynb`
