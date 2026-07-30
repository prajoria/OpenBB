# mortgage_amortization.py — Spec

| | |
|---|---|
| **Category** | Analysis (library) |
| **Path** | `Tools/mortgage_amortization.py` |
| **Writes** | CSV (optional, via `to_csv`) |

## Purpose

A self-contained fixed-rate mortgage amortization calculator. Importable
library class (no DB, no network) returning pandas DataFrames / dicts for
analysis and plotting.

## Formula

Monthly payment `M = P * [r(1+r)^n] / [(1+r)^n - 1]`, where `P` = principal,
`r` = monthly rate (`annual_rate / 12`), `n` = `years * 12`. Each month:
`interest = balance * r`, `principal = M - interest`, `balance -= principal`.

## API — `MortgageCalculator`

```python
calc = MortgageCalculator(loan_amount=400_000, annual_rate_pct=6.5, term_years=30, extra_monthly=0.0)
df   = calc.schedule()           # full amortization DataFrame
info = calc.summary()            # dict of summary stats
calc.print_schedule(every_n=12)  # annual view
calc.to_csv("amort.csv")         # save schedule
```

| Param | Meaning |
|-------|---------|
| `loan_amount` | original principal |
| `annual_rate_pct` | annual rate as a percent (e.g. `6.5`) |
| `term_years` | loan term in years |
| `extra_monthly` | optional extra principal per month |

## Notes

- Schedule is built lazily and cached on first `schedule()` call.
- `extra_monthly` shortens the term — the schedule stops when the balance hits
  zero.
- No CLI / `__main__` runner — used as a library or from notebooks.
