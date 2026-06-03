# OpenBB FinancialToolkit Extension

This extension exposes [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit)
functionality through OpenBB-native commands (ratios, performance, risk,
technicals, discovery, models, options, ...).

## Installation

> **Important — this extension is not published to PyPI and is not registered
> in the root `openbb_platform` `pyproject.toml`, so it does NOT auto-load.**
> You must install it standalone from a source checkout. The
> `financetoolkit` dependency is declared as a **local `path` dependency**
> (`develop = true`), which only resolves for an editable install from a repo
> checkout that includes the `FinanceToolkit` submodule — `pip install
> openbb-financialtoolkit` from a built wheel/sdist will **not** work because the
> `../../../FinanceToolkit` tree is not shipped in the artifact.

```bash
# 1. Clone OpenBB and initialize submodules (pulls FinanceToolkit)
git clone https://github.com/OpenBB-finance/OpenBB.git
cd OpenBB
git submodule update --init --recursive

# 2. Editable install of the extension (resolves the local path dependency)
pip install -e openbb_platform/extensions/financialtoolkit

# 3. Rebuild the static package so the new commands are picked up
python -c "import openbb; openbb.build()"
```

### FinanceToolkit dependency / fork status

The pinned `FinanceToolkit` submodule currently tracks a personal fork
(`prajoria/FinanceToolkit`) rather than upstream `JerBouma/FinanceToolkit` or a
published PyPI `financetoolkit` release. This is a **known short-term coupling**
and a release blocker — the plan is to upstream the required changes (or pin a
published `financetoolkit` version constraint) and repoint the submodule at the
canonical source. See the tracking issue for the convergence plan.

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
