# Pine conformance corpus

Per **PRD section 7**, every Pine builtin / language feature ships with one
paired conformance fixture:

```
tests/conformance/
├── _smoke.pine              # harness self-test, NOT a builtin
├── _smoke.csv
├── ta/
│   ├── sma.pine             # one .pine per builtin
│   ├── sma.csv              # one .csv reference output per builtin
│   ├── ema.pine
│   ├── ema.csv
│   └── ...
├── math/
│   ├── abs.pine
│   ├── abs.csv
│   └── ...
└── ...
```

## Adding a new builtin

1. Add `<dotted_name>.pine` (replace `.` with `/` for nested namespaces:
   `ta.sma` → `ta/sma.pine`).
2. Run the script in TradingView (or against a known-good local
   reference) to obtain the expected output series.
3. Save that series as `<dotted_name>.csv` next to the `.pine`.
4. **No test code change needed.** The `conformance_pair` fixture
   auto-discovers the new pair.

## File format

### `.pine`

A minimal Pine v6 (or v5) source that exercises **exactly one builtin**.
Keep scripts small — fewer than 20 lines is the norm. Comments explain
intent so a maintainer scanning a failure understands what the script
asserts before reading the CSV.

```pine
//@version=6
indicator("sma 14", overlay=true)
plot(ta.sma(close, 14), title="sma14")
```

### `.csv`

The reference output of running the `.pine` against a known bar grid.
First column is `date`; subsequent columns are the named series the
script plots (the `title=` argument of `plot()`). One row per bar.

```csv
date,close,sma14
2024-01-02,100.00,
2024-01-03,101.50,
...
2024-01-22,118.20,109.4
```

Empty cells encode `NaN` (Pine often emits NaN during the
moving-average warm-up window).

## Tolerance

`np.isclose(reference, produced, atol=1e-9, rtol=0)` per PRD section 7.
The reference is the source of truth; the compiler's output must
agree to within absolute 1e-9 on every cell. Failures point at the
first diverging `(row, col, expected, actual)` so the script's
divergence is localised.

## Reference-data provenance (PRD section 7.3)

The reference CSVs are **author-derivative-of-author-script** outputs:
the maintainer authored the `.pine` themselves, ran it against a public
bar series in TradingView (or another Pine runtime) themselves, and
copied the resulting plot series into the `.csv`. We do **not**
redistribute TradingView chart data, vendor-licensed price series, or
copy outputs from third-party Pine scripts. The bar grid embedded in
each `.csv` is a fixture authored to exercise the script — it is not
"market data" any more than a unit-test array of `[100, 101, 102]` is.

This posture lets us pin numerical correctness without litigating
data-licensing concerns. If a `.pine` ever requires non-trivial input
that cannot be embedded in the same `.csv` (e.g. multi-symbol
`request.security` examples), the convention is to ship a sibling
`<name>.input.csv` and adjust the harness — but no current builtin
needs this.

## Phase-1 status

The compiler entry point (`openbb_pine.compiler.compile_pine_source`)
does not yet exist (C1–C8 beads in flight). The harness consequently
SKIPs every per-pair test today; once the compiler lands, the SAME
fixtures start asserting numerical equality without any test code
change. This is the whole design intent of the harness — adding a
builtin = adding two files, never editing test code.

The `_smoke` pair is included so the discovery glob itself is exercised
on every CI run: `test_harness_discovers_at_least_smoke_pair` catches
regressions in `_discover_pairs` even when no real compile is happening.

## How CI uses this

`tests/conformance/test_conformance_corpus.py::test_conformance_pair_matches_reference[ta/sma]`
appears as ONE test per pair in CI output. Failures name the pair
in the test id so the build log points at the exact divergent
builtin without a maintainer having to dig through tracebacks.

A new builtin lands → two new files → N+1 conformance tests next CI
run → if any pair fails, the build goes red. No drift, no
maintenance, no test code edits.
