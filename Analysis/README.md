# Single-Stock Analysis Pipeline

A standalone 7-phase single-stock investment analysis pipeline built on the
OpenBB Platform. Given a ticker, it produces a structured, scored
buy/hold/sell view by walking through company quality, fundamentals,
technicals, valuation, risk, peer-relative analysis, and a final decision.

## Layout

| Path | Purpose |
|---|---|
| `stock_analysis.py` | Main module — the 7 phase functions plus helpers. |
| `tests/test_stock_analysis.py` | pytest suite (unit + integration). |
| `docs/PHASED_ANALYSIS_MASTER_PLAN.md` | Master plan tying all phases together. |
| `docs/phases/PHASE_*.md` | Ground-truth spec for each of the 7 phases. |
| `docs/FINANCIAL_DOMAIN_GLOSSARY.md` | Beginner-friendly terminology reference. |
| `docs/SINGLE_STOCK_ANALYSIS_STRATEGY.md` | Strategy overview. |

## Provider

`fmp_cached` is the only provider used — no `fmp` fallback, no yfinance.
`PRIMARY_PROVIDER = "fmp_cached"` is enforced as a constant in
`stock_analysis.py`.

## Quick start

```python
from stock_analysis import AnalysisConfig, run_full_analysis

results = run_full_analysis(AnalysisConfig(symbol="MSFT"))
p7 = results["p7"]
print(p7.action_label, p7.composite_score)
```

Credentials are read from `~/.openbb_platform/user_settings.json`
automatically on import.

## Running the tests

```bash
# Unit tests (no API needed)
python -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v

# Integration tests (requires an fmp_cached API key)
python -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v
```

> **Note:** General OpenBB example notebooks/demos (Streamlit news app, Apache
> Beam pipeline, macro studies, etc.) are intentionally **not** part of this
> pipeline and are tracked for a separate `docs/examples` contribution.
