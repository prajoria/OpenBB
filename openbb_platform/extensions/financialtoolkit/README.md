# OpenBB FinancialToolkit Extension

This extension exposes [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit)
functionality through OpenBB-native commands (ratios, performance, risk,
technicals, discovery, models, options, ...).

## Installation

> **Note — this extension is not published to PyPI and is not registered in
> the root `openbb_platform` `pyproject.toml`, so it does NOT auto-load.**
> You must install it standalone from a source checkout. The runtime
> `financetoolkit` dependency now resolves from PyPI (`^2.1.2`), so no
> submodule init is required.

```bash
# 1. Clone OpenBB
git clone https://github.com/OpenBB-finance/OpenBB.git
cd OpenBB

# 2. Editable install of the extension (pulls financetoolkit from PyPI)
pip install -e openbb_platform/extensions/financialtoolkit

# 3. Rebuild the static package so the new commands are picked up
python -c "import openbb; openbb.build()"
```

### FinanceToolkit dependency status

The runtime dependency is the published `financetoolkit` package (`^2.1.2`)
from PyPI. The previous coupling to a personal fork
(`prajoria/FinanceToolkit`) via git submodule was removed in #19 to make
the extension PyPI-installable. Disposition of the fork's 3-tier
historical-data fallback (FMP cached → FMP direct → CBOE) is tracked in a
separate follow-up issue.

## Credentials

All commands that hit FMP need an API key, resolved by a single shared contract
(`openbb_financialtoolkit.common.validators.resolve_api_key`):

1. an explicit `api_key="..."` argument (per-command override), else
2. the `FMP_API_KEY` environment variable / configured `fmp_api_key` credential.

If no key is available every command fails the same way with a clear
`FinancialToolkitConfigurationError`. API keys are never logged.

## Status

This extension is scaffolded and follows the OpenBB extension layout standards.
Progressive capability coverage is tracked in `docs/COMMAND_COVERAGE_MATRIX.md`.

## Usage

- Usage guide: `docs/USAGE_GUIDE.md`
- Example notebook: `examples/financialtoolkit_usage_example.ipynb`
