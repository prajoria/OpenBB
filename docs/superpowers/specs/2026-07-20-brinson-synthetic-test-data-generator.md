# Spec — Brinson-Fachler Synthetic Test-Data Generator & Fixture Oracle

- **Date:** 2026-07-20
- **Type:** Testing framework / mock-data generation (P2, Lane B, area:portfolio-intel)
- **Enables:** #559 `[portfolio] [P2][Analytics] Brinson-Fachler attribution (allocation vs selection)`
- **Parent epic:** #491 (Portfolio Intelligence Engine)
- **PRD reference:** `docs/Specs/Portfolio-Intelligence-Engine-PRD.md` §14.3 (Brinson-Fachler attribution)
- **Project:** Portfolio Intelligence Engine (#4)
- **Status:** Draft — spec only, **no implementation in this issue**

---

## 1. Purpose

Ship a **deterministic synthetic test-data generator** and a **trusted reference
oracle** for single-period Brinson-Fachler (BF) attribution, so that the
attribution implementation delivered by #559 can be verified to the PRD's
required tolerance (*"MUST match Brinson reference fixtures to ±1bp"*).

The generator produces *valid* random portfolio/benchmark books (weights that
sum to 1 by construction) plus targeted edge cases; the oracle produces the
known-correct allocation / selection / interaction effects for each book. The
implementation under test is then asserted **per-effect** against the oracle,
not merely against the sum invariant.

This issue is the **testing-enablement** counterpart to #559: #559 builds the
attribution engine; this issue builds the data + oracle that prove it correct.

## 2. Background — the math being tested

Single-period BF decomposes active return $R_p - R_b$ into three additive
effects per group (sector, country, factor, …):

| Effect | Formula | Isolates |
|---|---|---|
| Allocation | $(w_p - w_b)\,(r_b - R_b)$ | over/under-weighting a group |
| Selection | $w_b\,(r_p - r_b)$ | stock picking *within* a group |
| Interaction | $(w_p - w_b)\,(r_p - r_b)$ | the cross-term |

where per group: `w_p`/`w_b` are portfolio/benchmark weights, `r_p`/`r_b` are
portfolio/benchmark returns, and $R_p = \sum w_p r_p$, $R_b = \sum w_b r_b$.

**Invariant:** $\sum(\text{alloc} + \text{select} + \text{interaction}) \equiv R_p - R_b$.

This is the **Brinson-Fachler** variant (allocation uses the benchmark-relative
$r_b - R_b$), distinct from **Brinson-Hood-Beebour** (plain $r_b$). #559 must
implement BF; the oracle here is BF.

## 3. Why the sum invariant alone is not enough

The naive self-check `sum(effects) == active_return` is **necessary but not
sufficient**: an implementation can split the total *wrongly between the three
buckets* (e.g. mislabel allocation as selection) and still pass the sum check.
The oracle therefore asserts **each effect individually**, and the sum invariant
is kept as an additional guard. Testing only the sum is testing arithmetic, not
attribution.

## 4. Generator design

### 4.1 Valid random inputs

- **Weights:** drawn from a **Dirichlet** distribution so each of `w_p`, `w_b`
  sums to exactly 1 by construction (uniform random numbers do not).
- **Returns:** normal draws with realistic per-group volatility (portfolio ~8%,
  benchmark ~6%); returns are unconstrained in sign.
- **Determinism:** every case is a pure function of `(n_groups, seed, flags)` via
  `np.random.default_rng(seed)` — reproducible across machines and CI runs.

### 4.2 Edge cases (where BF implementations actually break)

1. **Zero portfolio weight in a group** (`w_p = 0`) — "I own none of Energy."
2. **Off-benchmark holding** (`w_b = 0`) — group present in portfolio, absent
   from benchmark; selection term $w_b(r_p - r_b)$ vanishes, so **all** active
   return there must land in allocation. Classic bug surface.
3. **Single group** (`n = 1`) — degenerate; active return is pure selection.
4. **Many groups** (`n = 11+`) — GICS-sector-sized books.
5. **All-negative returns** — bear-market sign handling.
6. **Identical portfolio == benchmark** — all three effects must be exactly 0.

### 4.3 Fixture format (the ±1bp reference set #559 must match)

Persist a small set of golden fixtures as JSON (inputs + expected effects) so
#559's CI can assert against them without importing the generator at test time:

```json
{
  "case_id": "bf-baseline-3sector-seed1",
  "inputs": {
    "sector":  ["Tech", "Energy", "Retail"],
    "w_p":     [0.50, 0.30, 0.20],
    "w_b":     [0.30, 0.40, 0.30],
    "r_p":     [0.15, -0.05, 0.02],
    "r_b":     [0.10, -0.02, 0.01]
  },
  "expected": {
    "active_return": 0.03900,
    "allocation":    0.00000,
    "selection":     0.00000,
    "interaction":   0.00000,
    "tolerance_bps": 1.0
  }
}
```

(Expected values above are placeholders — the generator computes them.)

## 5. Suggested code (reference — not the deliverable)

### 5.1 Oracle + generator

```python
import numpy as np
import pandas as pd


def brinson_reference(df: pd.DataFrame) -> dict:
    """Trusted single-period Brinson-Fachler oracle."""
    R_p = (df["w_p"] * df["r_p"]).sum()
    R_b = (df["w_b"] * df["r_b"]).sum()
    alloc = ((df["w_p"] - df["w_b"]) * (df["r_b"] - R_b)).sum()
    selc  = (df["w_b"] * (df["r_p"] - df["r_b"])).sum()
    inter = ((df["w_p"] - df["w_b"]) * (df["r_p"] - df["r_b"])).sum()
    return {
        "active_return": float(R_p - R_b),
        "allocation": float(alloc),
        "selection": float(selc),
        "interaction": float(inter),
    }


def make_case(n_groups: int, seed: int, *, zero_wp=False, zero_wb=False):
    """One deterministic, valid BF test case (weights sum to 1)."""
    rng = np.random.default_rng(seed)
    w_p = rng.dirichlet(np.ones(n_groups))
    w_b = rng.dirichlet(np.ones(n_groups))
    r_p = rng.normal(0.0, 0.08, n_groups)
    r_b = rng.normal(0.0, 0.06, n_groups)

    if zero_wp:                 # own nothing in group 0, renormalize
        w_p[0] = 0.0
        w_p /= w_p.sum()
    if zero_wb:                 # off-benchmark holding in group 0
        w_b[0] = 0.0
        w_b /= w_b.sum()

    return pd.DataFrame({
        "sector": [f"S{i}" for i in range(n_groups)],
        "w_p": w_p, "w_b": w_b, "r_p": r_p, "r_b": r_b,
    })
```

### 5.2 Parametrized test against the implementation

```python
import numpy as np
import pytest

CASES = [
    (3,  1, False, False),   # baseline
    (11, 2, False, False),   # many groups (GICS-sized)
    (1,  3, False, False),   # degenerate single group
    (5,  4, True,  False),   # zero portfolio weight
    (5,  5, False, True),    # off-benchmark holding
]

@pytest.mark.parametrize("n,seed,zwp,zwb", CASES)
def test_attribution_matches_oracle(n, seed, zwp, zwb):
    df = make_case(n, seed, zero_wp=zwp, zero_wb=zwb)
    expected = brinson_reference(df)

    got = my_attribution_impl(df)          # <-- code delivered by #559

    ONE_BP = 1e-4
    for k in ("allocation", "selection", "interaction"):
        assert np.isclose(got[k], expected[k], atol=ONE_BP)   # per-effect, ±1bp

    assert np.isclose(                                          # invariant guard
        got["allocation"] + got["selection"] + got["interaction"],
        expected["active_return"], atol=1e-9,
    )
```

### 5.3 Optional property-based layer (`hypothesis`)

Draw `n_groups`, Dirichlet weights, and bounded returns to check the invariant +
per-effect oracle across hundreds of generated books, beyond the hand-picked
seeds:

```python
from hypothesis import given, strategies as st

@given(n=st.integers(min_value=1, max_value=15), seed=st.integers(0, 10_000))
def test_invariant_property(n, seed):
    df = make_case(n, seed)
    ref = brinson_reference(df)
    assert np.isclose(
        ref["allocation"] + ref["selection"] + ref["interaction"],
        ref["active_return"], atol=1e-9,
    )
```

## 6. Deliverables (when this issue is implemented — separate from #559)

- `generator.py` — `make_case()` + edge-case flags, deterministic by seed.
- `oracle.py` — `brinson_reference()` single-period BF oracle.
- `fixtures/*.json` — a committed golden set (baseline + all §4.2 edge cases)
  for #559 to assert against without importing the generator.
- `test_generator.py` — self-tests proving the oracle satisfies the invariant
  and that generated weights sum to 1.
- Optional `hypothesis` property test.

## 7. Scope

**In scope:** single-period BF synthetic data + oracle + golden fixtures +
property test.

**Out of scope (this issue is spec-only; no implementation now):**

- The attribution engine itself — that is #559.
- **Multi-period linking** (Carino / Menchero / GRAP) — effects add per period
  but returns compound; cross-period smoothing is its own issue.
- Country/factor grouping beyond the generic `group` column (generator stays
  grouping-agnostic; naming a column "sector" is cosmetic).
- Real benchmark-constituent data wiring (`indexes/historical-constituents`) —
  the fixtures are synthetic on purpose.

## 8. Acceptance criteria

1. Generator emits weight vectors summing to `1.0` within `1e-12` for both book
   and benchmark, for all `n_groups ≥ 1`.
2. Oracle satisfies the sum invariant to `1e-9` on every generated case.
3. Golden fixture set covers all six §4.2 edge cases, each with pre-computed
   expected effects and a `tolerance_bps` field.
4. Same `(n_groups, seed, flags)` → byte-stable inputs and tolerance-stable
   expected effects across machines.
5. The `identical portfolio == benchmark` case yields all three effects == 0.

## 9. Notes for the implementer

- Keep the generator **pure and dependency-light** (numpy + pandas only;
  `hypothesis` optional and test-only).
- The oracle is the *trusted* side — keep it a literal transcription of the BF
  formulas, never "optimized," so it stays obviously correct by inspection.
- Do **not** couple this to #559's internal API; the coupling point is the
  JSON fixture schema (§4.3), so either side can be rewritten independently.
