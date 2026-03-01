# FinancialToolkit Command Coverage Matrix

## How to Use This Matrix

- Start with the `Coverage` column to see whether a command is already implemented.
- Use `Notes` to identify the exact FinanceToolkit method wrapped by the extension.
- Use the **Quick Start Links** section to jump directly to runnable examples in the usage guide and notebook.
- When adding a new command, update this table and append its row in **Quick Start Links** in the same PR.

| Domain | Command | Coverage | Notes |
|---|---|---|---|
| models | altman_z_score | implemented | Wrapped to FinanceToolkit `models.get_altman_z_score` |
| models | piotroski_score | implemented | Wrapped to FinanceToolkit `models.get_piotroski_score` |
| models | dupont | implemented | Wrapped to FinanceToolkit `models.get_dupont_analysis` |
| models | wacc | implemented | Wrapped to FinanceToolkit `models.get_weighted_average_cost_of_capital` |
| models | intrinsic_value | implemented | Wrapped to FinanceToolkit `models.get_intrinsic_valuation` |
| options | greeks | implemented | Wrapped to FinanceToolkit `options.collect_all_greeks` |
| risk | var | implemented | Wrapped to FinanceToolkit `risk.get_value_at_risk` |
| risk | cvar | implemented | Wrapped to FinanceToolkit `risk.get_conditional_value_at_risk` |
| risk | evar | implemented | Wrapped to FinanceToolkit `risk.get_entropic_value_at_risk` |
| risk | garch | implemented | Wrapped to FinanceToolkit `risk.get_garch` |
| performance | risk_adjusted_return | implemented | Implemented via sharpe/sortino/information ratio wrappers |
| performance | sharpe_ratio | implemented | Wrapped to FinanceToolkit `performance.get_sharpe_ratio` |
| performance | sortino_ratio | implemented | Wrapped to FinanceToolkit `performance.get_sortino_ratio` |
| performance | information_ratio | implemented | Wrapped to FinanceToolkit `performance.get_information_ratio` |
| discovery | screen | implemented | Wrapped to FinanceToolkit `Discovery.get_stock_screener` |
| discovery | search | implemented | Wrapped to FinanceToolkit `Discovery.search_instruments` |

## Quick Start Links

Use this map to jump from a command to a runnable example.

| Domain | Command | Usage Guide Example | Notebook Example |
|---|---|---|---|
| models | `altman_z_score` | [USAGE_GUIDE.md#models-examples](USAGE_GUIDE.md#models-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| models | `piotroski_score` | [USAGE_GUIDE.md#models-examples](USAGE_GUIDE.md#models-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| models | `dupont` | [USAGE_GUIDE.md#models-examples](USAGE_GUIDE.md#models-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| models | `wacc` | [USAGE_GUIDE.md#models-examples](USAGE_GUIDE.md#models-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| models | `intrinsic_value` | [USAGE_GUIDE.md#models-examples](USAGE_GUIDE.md#models-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| options | `greeks` | [USAGE_GUIDE.md#options-examples](USAGE_GUIDE.md#options-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| risk | `var` | [USAGE_GUIDE.md#risk-examples](USAGE_GUIDE.md#risk-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| risk | `cvar` | [USAGE_GUIDE.md#risk-examples](USAGE_GUIDE.md#risk-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| risk | `evar` | [USAGE_GUIDE.md#risk-examples](USAGE_GUIDE.md#risk-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| risk | `garch` | [USAGE_GUIDE.md#risk-examples](USAGE_GUIDE.md#risk-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| performance | `sharpe_ratio` | [USAGE_GUIDE.md#performance-examples](USAGE_GUIDE.md#performance-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| performance | `sortino_ratio` | [USAGE_GUIDE.md#performance-examples](USAGE_GUIDE.md#performance-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| performance | `information_ratio` | [USAGE_GUIDE.md#performance-examples](USAGE_GUIDE.md#performance-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| discovery | `screen` | [USAGE_GUIDE.md#discovery-examples](USAGE_GUIDE.md#discovery-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
| discovery | `search` | [USAGE_GUIDE.md#discovery-examples](USAGE_GUIDE.md#discovery-examples) | [../examples/financialtoolkit_usage_example.ipynb](../examples/financialtoolkit_usage_example.ipynb) |
