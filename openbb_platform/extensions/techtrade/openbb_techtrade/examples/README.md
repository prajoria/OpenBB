# techtrade examples

Three runnable end-to-end scripts that exercise the user-facing `obb.techtrade.*`
surface. Each is small (~50 lines) and corresponds 1:1 to a section in the parent
extension `README.md`. The smoke test at
`tests/unit/test_examples_smoke.py` imports each script's `main()` and exercises
it against the same offline fakes the unit suite already ships, so the examples
are guaranteed not to drift from the code.

## Scripts

| Script | What it does | Soft-dep | Run |
|---|---|---|---|
| `scan_to_excel.py` | Scan all 11 GICS sectors -> export the top plans to a 6-sheet workbook. The headline end-to-end. | — | `python -m openbb_techtrade.examples.scan_to_excel` |
| `plan_one_symbol.py` | Single-symbol path: build a `plan`, materialize its `orders`, paper-fill them forward via `simulate`. | — | `python -m openbb_techtrade.examples.plan_one_symbol` |
| `validate_a_plan.py` | Build a plan, then call `validate` to get a PBO / DSR / verdict back. Skips with a clear notice when `[validation]` is absent. | `[validation]` | `python -m openbb_techtrade.examples.validate_a_plan` |

## Conventions

Each script:

- Has a top-level docstring stating purpose, soft-deps required, and expected output.
- Defines a `main(*, ..., out=None, ..._fetcher=None) -> <return shape>` function.
  The `*_fetcher` parameters are test seams; the live path uses `fmp_cached`.
- Has an `if __name__ == "__main__": main()` guard that runs the live path.
- Imports only from `openbb` and `openbb_techtrade.*` (the public surface) — never
  from `engine.*` internals.

Every running script writes its output through Python's `logging` (not `print`)
so a smoke-test runner can capture / silence noise.

See the parent `README.md` for the full command surface, install matrix, and
Quickstart.
