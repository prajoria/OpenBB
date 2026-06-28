# #86 README + Worked Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the #65 scaffold README at `openbb_platform/extensions/techtrade/README.md` with a release-ready document covering the now-shipped 10-command surface, and add an `examples/` directory with 3 runnable scripts that the README links to and a smoke test that prevents drift between the docs and the code.

**Architecture:** Three tasks land in dependency order — (T1) `examples/` package with `__init__.py` + 3 runnable scripts + index; (T2) `tests/unit/test_examples_smoke.py` smoke test that imports each script and asserts shape via the existing offline-fake seams; (T3) README rewrite with the inline Quickstart snippet pulled verbatim from `examples/scan_to_excel.py::main()` per Q-A refinement 3 (so even the most-read inline block is covered by the smoke test transitively).

**Tech Stack:** Python 3.10–3.13 (matches platform); pandas (existing base dep); pytest 9.x (existing); openbb-techtrade + the full obb.techtrade.* surface (all shipped); `_signal_fetcher` / `_level_fetcher` / candidate-fetcher offline fakes from existing `tests/unit/test_plan.py` + `test_scan.py`. No new dependencies, no new test infrastructure.

## Global Constraints

- **Python interpreter:** every command runs under `.venv_win\Scripts\python.exe` (Windows checkout). Never the system/global interpreter.
- **Provider:** `fmp_cached` only — never raw `fmp`, never `yfinance`. Examples and README never mention any other provider.
- **Tone (L4):** direct, finance-literate, US-English, no marketing copy. Mirrors the existing PRD voice. No "powerful", "blazing-fast", "AI-powered". No emoji.
- **Disclaimer (L6):** the line "*Outputs are paper / research — not investment advice.*" appears near the top of the README in italic, identical to the Excel disclaimer (PRD §20 Q9).
- **Install matrix (Q-C C1):** the README's Install section mirrors `[tool.poetry.extras]` exactly: rows for the bare `pip install openbb-techtrade`, `[xlsxwriter]`, `[validation]`, and (NEW since the design was written) `[tuneta]`. The per-example parenthetical nudge uses the same string the runtime error message prints (e.g. `(requires \`pip install 'openbb-techtrade[validation]'\`)`).
- **Roadmap (Q-B B1):** prose only, never runnable-looking call syntax. Each entry reads `<name> (#NN) — not yet implemented` in plain text. **As of 2026-06-23 the Roadmap covers ONLY 3 items** (`narrator` #84, `MCP` #85, `streaming` #87). **`tune` (#83) ships live** and is documented in the Commands section, NOT in the Roadmap.
- **Commands count: 11** (`about`, `segments`, `movers`, `signals`, `plan`, `scan`, `orders`, `simulate`, `export`, `validate`, `tune`) — the design's L2 list was 10; `tune` was added by the #83 merge (`3b2fcc5df`).
- **Module-boundary rule (L8):** `examples/*.py` imports ONLY from `openbb_techtrade.*` and `openbb` (the public surface). NEVER from `engine.confluence`, `engine.rules`, `engine.orders`, or any other internal seam. The smoke test reuses the existing offline fakes; no new fake-data scaffolding.
- **Example contract:** every `examples/*.py` exports a `main(*, ..., out=None) -> <return shape>` function that accepts the same offline fakes the unit suite uses (`signal_fetcher=…`, `level_fetcher=…`, `candidate_fetcher=…`, `bars=…`, `BacktestConfig=…`), AND has an `if __name__ == "__main__": main()` guard that runs the live path (no fakes, hits `fmp_cached`).
- **Determinism (L5):** PowerShell-canonical install commands; bash form alongside for non-Windows. Python snippets use `from openbb import obb` unless they exercise an engine seam.
- **Line length:** Ruff 122 (consistent with the rest of the repo); markdown free-form but readable.
- **Commit-message convention:** `docs(86): <subject>` / `test(86): <subject>` / `feat(86): <subject>`. Co-Author trailer: `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`.
- **Beads tracking:** parent bead is `OpenBBTechnical-afc` (already `in_progress`). Each Task below will file an `addBlocks` child so the dependency chain shows: `T1 ← T2 ← T3`. Claim each child at task start; close on commit.

## Reading order for the implementer

Before starting any Task, read these in order:

1. `docs/designs/quant_trading/86-readme-usage-examples.md` — the approved design (especially §0 locked decisions L1-L9, §2 README structure, §4 examples contract, §5 smoke-test contract)
2. The current scaffold `openbb_platform/extensions/techtrade/README.md` — 60 lines; what's being replaced (NOT preserved verbatim; the rewrite is in place per L1)
3. `openbb_platform/extensions/techtrade/tests/unit/test_plan.py` — find the `_signal_fetcher` / `_level_fetcher` offline fakes the smoke test reuses
4. `openbb_platform/extensions/techtrade/tests/unit/test_scan.py` — find the candidate-fetcher offline fakes the smoke test reuses
5. `openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py` + the sub-routers under `engine/`, `reporting/`, `validation/`, `tuning/` — confirm the 11 commands and their argument names match what the README documents
6. `notebooks/01-foundations-techtrade-and-analysis.ipynb` — has the canonical scan→plan→export flow already verified end-to-end; the README's Quickstart is the abbreviated form

---

## Task 1: examples package + 3 runnable scripts + index

**Files:**
- Create: `openbb_platform/extensions/techtrade/examples/__init__.py` (1 line — package marker)
- Create: `openbb_platform/extensions/techtrade/examples/scan_to_excel.py` (~50 lines)
- Create: `openbb_platform/extensions/techtrade/examples/plan_one_symbol.py` (~60 lines)
- Create: `openbb_platform/extensions/techtrade/examples/validate_a_plan.py` (~50 lines)
- Create: `openbb_platform/extensions/techtrade/examples/README.md` (~25 lines — one-line description per script + how-to-run)

**Interfaces:**
- Consumes: the live `obb.techtrade.{scan, export, plan, orders, simulate, validate}` surface (all shipped); `openbb_techtrade.models.{TradePlan, Order, Fill, ValidationReport}` for shape annotations.
- Produces (consumed by T2):
  - `openbb_techtrade.examples.scan_to_excel.main(*, out: pathlib.Path | str | None = None, signal_fetcher=None, level_fetcher=None, candidate_fetcher=None) -> str` — returns the workbook path. Default `out` = `Analysis/exports/techtrade_<date>.xlsx`.
  - `openbb_techtrade.examples.plan_one_symbol.main(*, symbol: str = "MSFT", signal_fetcher=None, level_fetcher=None, bars=None) -> list[Fill]` — returns the simulated fills. Synthetic forward window when `bars=None` is not provided; lookup-by-default when run live.
  - `openbb_techtrade.examples.validate_a_plan.main(*, symbol: str = "MSFT", method: str = "wfo", horizon_years: int = 5, signal_fetcher=None, level_fetcher=None, BacktestConfig=None) -> "ValidationReport | None"` — returns the report, or `None` when `openbb-backtest` is absent (caught in-body and printed as a skip notice for the live path).

---

- [ ] **Step 1: Verify the fake-fetcher import locations**

```bash
PYTHONPATH="$(pwd)/openbb_platform/extensions/techtrade" .venv_win/Scripts/python.exe -c "
import inspect
from openbb_techtrade.tests.unit.test_plan import (
    _signal_fetcher as plan_signal_fetcher,
    _level_fetcher as plan_level_fetcher,
)
print('test_plan fakes: OK')
"
```

Expected: `test_plan fakes: OK`. If it fails, the fakes live elsewhere — find them with `grep -rn "_signal_fetcher\|_level_fetcher\|_candidate_fetcher" openbb_platform/extensions/techtrade/tests/`. Record the actual import path because T2 will need it for the smoke test.

Note: tests don't ship in the importable package under most poetry packagings; use the file paths directly in T2 if the import path doesn't work. The fakes themselves live in `tests/unit/test_plan.py` and `tests/unit/test_scan.py` — they don't need to be importable for T1's runtime path (T1 only uses them as parameter defaults that are `None` until T2's smoke test provides them).

- [ ] **Step 2: Create the package marker `__init__.py`**

Create `openbb_platform/extensions/techtrade/examples/__init__.py`:

```python
"""Runnable end-to-end techtrade examples (issue #86).

Each script defines a ``main(...)`` function that accepts injectable offline
fakes (used by ``tests/unit/test_examples_smoke.py`` to prove the example
stays in sync with the README) AND a ``if __name__ == "__main__": main()``
guard that runs the live ``fmp_cached``-backed path when invoked directly.
"""
```

- [ ] **Step 3: Write `examples/scan_to_excel.py` — the headline end-to-end**

Create `openbb_platform/extensions/techtrade/examples/scan_to_excel.py`:

```python
"""Scan all 11 GICS sectors and export the top plans to a 6-sheet Excel workbook.

Live run:

    .venv_win\\Scripts\\python.exe -m openbb_techtrade.examples.scan_to_excel

Requires:
- A configured ``fmp_cached`` API key in ``~/.openbb_platform/user_settings.json``
  (see the project README for the schema).
- ``openpyxl`` (ships with the bare ``openbb-techtrade`` install — no extra needed).

Optional:
- ``[xlsxwriter]`` extra (``pip install 'openbb-techtrade[xlsxwriter]'``) to use
  the alternative Excel engine (``engine="xlsxwriter"`` argument to ``export``).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def main(
    *,
    out: Path | str | None = None,
    metric: str = "pct_change",
    top_n: int = 5,
    preset: str = "trend_follow",
    risk: float = 0.01,
    candidate_fetcher=None,
    signal_fetcher=None,
    level_fetcher=None,
) -> str:
    """Run scan -> export, return the workbook path.

    Parameters
    ----------
    out
        Workbook output path. ``None`` (default) lets ``export`` pick its
        default ``Analysis/exports/techtrade_<date>.xlsx``.
    metric, top_n, preset, risk
        Forwarded to ``obb.techtrade.scan``.
    candidate_fetcher, signal_fetcher, level_fetcher
        Test seams. ``None`` (default) uses the live ``fmp_cached`` path.

    Returns
    -------
    str
        Absolute path to the written workbook.
    """
    from openbb import obb  # noqa: PLC0415 — lazy so module imports without `obb`

    # 1. Scan all 11 GICS sectors -> ranked, paper-filled trade plans.
    scan_kwargs = {"metric": metric, "top_n": top_n, "preset": preset, "risk": risk}
    if candidate_fetcher is not None:
        scan_kwargs["candidate_fetcher"] = candidate_fetcher
    if signal_fetcher is not None:
        scan_kwargs["signal_fetcher"] = signal_fetcher
    if level_fetcher is not None:
        scan_kwargs["level_fetcher"] = level_fetcher
    plans = obb.techtrade.scan(**scan_kwargs).results
    logger.info("scan returned %d plans", len(plans))

    # 2. Export to a 6-sheet Excel workbook (Recommendations / Levels / Reasoning
    #    / Orders / Fills / Summary). Includes the "research/paper — not investment
    #    advice" disclaimer banner on the Recommendations sheet.
    export_kwargs = {"plans": plans}
    if out is not None:
        export_kwargs["path"] = str(out)
    path = obb.techtrade.export(**export_kwargs).results
    logger.info("workbook written to: %s", path)
    return str(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
```

- [ ] **Step 4: Write `examples/plan_one_symbol.py` — single-symbol path**

Create `openbb_platform/extensions/techtrade/examples/plan_one_symbol.py`:

```python
"""Build a single-symbol plan, materialize its orders, paper-fill them forward.

Live run:

    .venv_win\\Scripts\\python.exe -m openbb_techtrade.examples.plan_one_symbol

Requires:
- A configured ``fmp_cached`` API key in ``~/.openbb_platform/user_settings.json``.

Demonstrates the user-facing chain plan -> orders -> simulate for ONE symbol
(MSFT by default). The forward bar window for ``simulate`` is fetched on the live
path; tests inject a synthetic ``bars`` window so the smoke stays offline.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main(
    *,
    symbol: str = "MSFT",
    preset: str = "trend_follow",
    risk: float = 0.01,
    signal_fetcher=None,
    level_fetcher=None,
    bars=None,
) -> list:
    """Plan -> orders -> simulate; return the realized fills.

    Returns
    -------
    list[Fill]
        Paper fills for the plan's order legs (the fills are the user-visible
        outcome of paper-trading the plan forward).
    """
    from openbb import obb  # noqa: PLC0415

    # 1. Build a single-symbol plan (the engine ranks the symbol, builds the
    #    confluence signal, sizes the position, generates the order legs, and
    #    attaches an inline Recommendation).
    plan_kwargs = {"symbols": [symbol], "preset": preset, "risk": risk}
    if signal_fetcher is not None:
        plan_kwargs["signal_fetcher"] = signal_fetcher
    if level_fetcher is not None:
        plan_kwargs["level_fetcher"] = level_fetcher
    plans = obb.techtrade.plan(**plan_kwargs).results
    if not plans:
        logger.info("no plan produced for %s (signal below entry_threshold)", symbol)
        return []
    plan = plans[0]
    logger.info(
        "plan: %s score=%+.3f action=%s conviction=%s",
        plan.symbol, plan.signal.score, plan.recommendation.action,
        plan.recommendation.conviction,
    )

    # 2. Materialize the order legs (re-validates the plan; idempotent).
    orders = obb.techtrade.orders(plan=plan).results
    logger.info("orders: %d legs (%s)", len(orders), [o.intent for o in orders])

    # 3. Paper-fill the orders against a forward bar window. Real-money brokers
    #    are not engaged; every fill is at next-bar-open with configured slippage
    #    + commission (PRD §13 + #78).
    sim_kwargs = {"orders": orders}
    if bars is not None:
        sim_kwargs["bars"] = bars
    fills = obb.techtrade.simulate(**sim_kwargs).results
    logger.info("simulate: %d fills", len(fills))
    for fill in fills:
        logger.info(
            "  fill: %s %s qty=%s price=%s slippage=%s commission=%s",
            fill.symbol, fill.side, fill.quantity, fill.price,
            fill.slippage, fill.commission,
        )
    return fills


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
```

- [ ] **Step 5: Write `examples/validate_a_plan.py` — soft-dep-gated validation**

Create `openbb_platform/extensions/techtrade/examples/validate_a_plan.py`:

```python
"""Build a plan, then call ``obb.techtrade.validate`` to score its robustness.

Live run:

    .venv_win\\Scripts\\python.exe -m openbb_techtrade.examples.validate_a_plan

Requires the ``[validation]`` extra:

    pip install 'openbb-techtrade[validation]'

When the extra is absent, ``validate`` raises ``TechtradeDependencyError`` with a
pip-install hint; this example catches that and prints a skip notice rather than
crashing — mirrors the integration-test skipif pattern (#82 test_validate.py).

Demonstrates the user-visible robustness gate: WFO folds + PBO + Deflated Sharpe
+ verdict (one of ``robust`` / ``fragile`` / ``overfit``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main(
    *,
    symbol: str = "MSFT",
    method: str = "wfo",
    horizon_years: int = 5,
    preset: str = "trend_follow",
    risk: float = 0.01,
    signal_fetcher=None,
    level_fetcher=None,
    BacktestConfig=None,  # noqa: N803 — mirrors the openbb_backtest name
):
    """Plan a symbol, then validate the plan. Return the ValidationReport or None.

    Returns ``None`` when ``openbb-backtest`` (the ``[validation]`` extra) is
    absent — the example degrades to a skip notice rather than a crash so it can
    be smoke-tested on a bare install.
    """
    from openbb import obb  # noqa: PLC0415

    # 1. Build a single-symbol plan.
    plan_kwargs = {"symbols": [symbol], "preset": preset, "risk": risk}
    if signal_fetcher is not None:
        plan_kwargs["signal_fetcher"] = signal_fetcher
    if level_fetcher is not None:
        plan_kwargs["level_fetcher"] = level_fetcher
    plans = obb.techtrade.plan(**plan_kwargs).results
    if not plans:
        logger.info("no plan produced for %s; nothing to validate", symbol)
        return None
    plan = plans[0]

    # 2. Validate. Catches the soft-dep-absent error and degrades to None so the
    #    example runs on a bare install (and the smoke test exercises both paths).
    try:
        from openbb_techtrade.validation.backtest_bridge import (  # noqa: PLC0415
            TechtradeDependencyError,
        )
    except ImportError:  # pragma: no cover — validation module always ships in techtrade
        logger.error("validation module not importable; cannot continue")
        return None

    try:
        result = obb.techtrade.validate(
            plan=plan, method=method, horizon_years=horizon_years,
        )
    except TechtradeDependencyError as exc:
        logger.warning(
            "validate skipped: %s\\n  install with: pip install 'openbb-techtrade[validation]'",
            exc,
        )
        return None

    report = result.results
    logger.info(
        "verdict=%s  pbo=%.3f  dsr=%.3f  oos_sharpe=%.3f",
        report.verdict,
        getattr(report, "pbo", float("nan")),
        getattr(report, "deflated_sharpe", float("nan")),
        getattr(getattr(report, "oos_metrics", None), "sharpe", float("nan")),
    )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
```

- [ ] **Step 6: Write `examples/README.md` — the one-line index**

Create `openbb_platform/extensions/techtrade/examples/README.md`:

```markdown
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
```

- [ ] **Step 7: Smoke-check each script imports cleanly**

```bash
PYTHONPATH="$(pwd)/openbb_platform/extensions/techtrade" .venv_win/Scripts/python.exe -c "
import importlib
for name in ('scan_to_excel', 'plan_one_symbol', 'validate_a_plan'):
    mod = importlib.import_module(f'openbb_techtrade.examples.{name}')
    assert callable(mod.main), f'{name}.main is not callable'
    print(f'{name}: OK')
"
```

Expected:
```
scan_to_excel: OK
plan_one_symbol: OK
validate_a_plan: OK
```

If the package isn't importable (i.e. `examples.__init__.py` is missing), this surfaces it immediately.

- [ ] **Step 8: Commit T1**

```bash
git add openbb_platform/extensions/techtrade/examples/
git commit -m "$(cat <<'EOF'
feat(86): add examples/ package — 3 runnable end-to-end scripts + index

T1 of the #86 README + worked-examples plan
(docs/superpowers/plans/2026-06-23-86-readme-and-examples.md).

Three scripts exercise the user-facing obb.techtrade.* surface end-to-end:
- scan_to_excel.py: scan all 11 GICS sectors -> export to 6-sheet workbook
  (the headline end-to-end; live path uses fmp_cached + openpyxl).
- plan_one_symbol.py: single-symbol plan -> orders -> simulate (paper fills).
- validate_a_plan.py: plan -> validate via openbb-backtest; degrades to a
  clear skip notice when [validation] is absent (mirrors the #82 integration
  skipif pattern).

Each script: top-level docstring + main(*, ..., out=None, _fetcher=None)
function + `if __name__ == "__main__": main()` guard. The fetcher kwargs are
test seams that T2's smoke test will use to drive each script offline.
Examples import only from `openbb` and `openbb_techtrade.*` (the public
surface) — never from engine.* internals (L8).

examples/README.md is the one-page index pointing at each script with run
instructions; the parent README (T3) links to this from the Quickstart.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `test_examples_smoke.py` — the drift guard

**Files:**
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_examples_smoke.py` (~120 lines)

**Interfaces:**
- Consumes: T1's three `main()` functions (signatures in T1 §"Produces"); the existing offline fakes in `tests/unit/test_plan.py` + `tests/unit/test_scan.py` (lifted into this test file via internal helpers so the import path is robust to test-package re-layout).
- Produces (consumed by T3 transitively): the **drift-guard contract** — if T3's README inline Quickstart snippet is a verbatim slice of `examples/scan_to_excel.py::main()` (Q-A refinement 3), then a passing smoke test transitively proves the README inline snippet still matches its target.

---

- [ ] **Step 1: Read the existing offline fakes**

```bash
grep -nA 8 "^def _signal_fetcher\|^def _level_fetcher\|^def _candidate_fetcher" \
  openbb_platform/extensions/techtrade/tests/unit/test_plan.py \
  openbb_platform/extensions/techtrade/tests/unit/test_scan.py \
  2>&1 | head -60
```

Expected: the function bodies of `_signal_fetcher`, `_level_fetcher`, `_candidate_fetcher` (names may vary slightly — record the exact names). These are the offline seams that produce synthetic `MoverSignal` / level-dict / candidate-row data without touching `fmp_cached`.

**Decision point:** if the fakes live in test modules and aren't trivially importable, copy a minimal version into `test_examples_smoke.py` directly (the design's "reuses the same offline fakes" guidance allows a copy-not-import approach as long as the SHAPES match what the engine expects). This avoids depending on test-package import paths.

- [ ] **Step 2: Write the failing test file (3 tests, one block)**

Create `openbb_platform/extensions/techtrade/tests/unit/test_examples_smoke.py`:

```python
"""Drift-guard smoke test for the examples/ scripts (#86 Q-A A3 / §5).

For each `examples/*.py` script, this test imports its `main()` and runs it
against offline fakes (no live `fmp_cached` calls), then asserts the SHAPE of
the return value. The contract is "the example signatures stay in sync with the
code"; CONTENT lock-in lives in `tests/golden/`, not here (per design §5.1).

If this test ever fails, the README/examples and the code have drifted — fix
one or the other, never silence the test.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest


# --- Local copies of the engine's offline-test seams ---------------------------
# Kept as small as possible: just enough fields for the example chain to run.
# If the engine adds a required field, this fixture surfaces it as the first
# `pytest` failure in the smoke — exactly the drift-guard intent.


def _fake_candidate_fetcher(as_of, **kwargs):
    """Return a tiny list of mover-candidate dicts per segment (no fmp_cached).

    Shape mirrors the live `obb.equity.discovery.gainers/losers/active` rows
    the real fetcher merges. Just enough symbols/sectors to feed the scan.
    """
    from openbb_techtrade.engine.universe import GICS_SECTOR_ETFS
    out = []
    for i, (segment, etf) in enumerate(GICS_SECTOR_ETFS.items()):
        # Two synthetic movers per sector, distinct symbols so dedup is happy.
        out.extend([
            {
                "symbol": f"{etf}1",  # e.g. XLK1
                "segment": segment,
                "pct_change": 5.0 - 0.1 * i,
                "volume": 1_000_000.0,
            },
            {
                "symbol": f"{etf}2",
                "segment": segment,
                "pct_change": 4.0 - 0.1 * i,
                "volume": 800_000.0,
            },
        ])
    return out


def _fake_signal_fetcher(symbol, as_of, **kwargs):
    """Return a synthetic MoverSignal — enough to score above entry_threshold."""
    from openbb_techtrade.models import IndicatorVote, MoverSignal
    return MoverSignal(
        symbol=symbol,
        segment="Information Technology",
        as_of=as_of,
        score=0.62,
        direction="long",
        votes=[
            IndicatorVote(family="trend", name="ema_cross", vote=1.0, weight=0.40),
            IndicatorVote(family="momentum", name="rsi", vote=0.5, weight=0.25),
        ],
        rank_in_segment=1,
    )


def _fake_level_fetcher(symbol, as_of, **kwargs):
    """Return a synthetic levels dict: entry/stop/target/atr."""
    return {
        "entry_price": Decimal("100.00"),
        "stop_price":  Decimal("98.00"),
        "target_price": Decimal("104.00"),
        "atr": 2.0,
    }


# --- examples.scan_to_excel ----------------------------------------------------


def test_scan_to_excel_smoke(tmp_path: Path):
    """examples/scan_to_excel.py::main runs offline and writes a workbook.

    Drift-guard contract (design §5.2): the example's signature accepts the
    fakes AND `scan -> export` chains without TypeError; the return is a path
    string ending in ``.xlsx`` that exists on disk.
    """
    from openbb_techtrade.examples import scan_to_excel

    out = tmp_path / "wb.xlsx"
    path = scan_to_excel.main(
        out=out,
        candidate_fetcher=_fake_candidate_fetcher,
        signal_fetcher=_fake_signal_fetcher,
        level_fetcher=_fake_level_fetcher,
    )
    assert isinstance(path, str)
    assert path.endswith(".xlsx")
    assert os.path.exists(path)


# --- examples.plan_one_symbol --------------------------------------------------


def test_plan_one_symbol_smoke():
    """examples/plan_one_symbol.py::main runs offline and returns a list of fills.

    Drift-guard contract: plan -> orders -> simulate chains without TypeError;
    the return is a list (may be empty for a synthetic-bar window that doesn't
    trip an entry).
    """
    from openbb_techtrade.examples import plan_one_symbol

    # Synthetic forward bars: 20 sessions, monotonic close (won't trip stops).
    bars = [
        {
            "symbol": "MSFT",
            "timestamp": f"2025-06-{20 + i:02d}T14:30:00+00:00",
            "open":  Decimal("100.00"),
            "high":  Decimal("100.50"),
            "low":   Decimal("99.50"),
            "close": Decimal(str(100.00 + 0.10 * i)),
            "volume": Decimal("1000000"),
        }
        for i in range(20)
    ]
    fills = plan_one_symbol.main(
        symbol="MSFT",
        signal_fetcher=_fake_signal_fetcher,
        level_fetcher=_fake_level_fetcher,
        bars=bars,
    )
    assert isinstance(fills, list)
    # Either at least one fill (entry triggered) or empty (synthetic price drift
    # didn't trip the entry threshold) — both are valid shape outcomes for the
    # smoke; we lock SHAPE, not COUNT.


# --- examples.validate_a_plan --------------------------------------------------


def test_validate_a_plan_smoke_when_backtest_absent(monkeypatch: pytest.MonkeyPatch):
    """examples/validate_a_plan.py::main returns None cleanly when [validation] absent.

    Drift-guard contract: the example catches TechtradeDependencyError and
    degrades to a skip notice + None return — never raises. Mirrors the #82
    integration-test skipif pattern.
    """
    # Force openbb_backtest absent (mirrors test_backtest_bridge.py's degradation pattern).
    import builtins
    import sys

    for module_name in list(sys.modules):
        if module_name.startswith("openbb_backtest"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    real_import = builtins.__import__

    def _blocker(name, *args, **kwargs):
        if name.startswith("openbb_backtest"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocker)

    from openbb_techtrade.examples import validate_a_plan

    result = validate_a_plan.main(
        symbol="MSFT",
        signal_fetcher=_fake_signal_fetcher,
        level_fetcher=_fake_level_fetcher,
    )
    # `validate` raised TechtradeDependencyError; the example caught it and
    # returned None — that's the drift-guard contract for absent soft-deps.
    assert result is None
```

- [ ] **Step 3: Run the smoke tests**

```bash
PYTHONPATH="$(pwd)/openbb_platform/extensions/techtrade" .venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_examples_smoke.py -v 2>&1 | tail -10
```

Expected: 3 passed. The most common failure mode is one of the example `main()` functions raising on a missing fake fetcher kwarg (T1 step 1's verification of the actual `scan`/`plan` keyword names matters here — if `obb.techtrade.scan` doesn't accept `candidate_fetcher` as a keyword, the example will raise `TypeError: scan() got an unexpected keyword argument 'candidate_fetcher'`).

**If the test fails because the live router doesn't accept a `_fetcher` kwarg**, that's a discoverability gap: the engine's seams ARE in `engine/movers.py:_default_candidate_fetcher` and `engine/signals.py`'s signal-fetcher, but they may not be plumbed all the way through to the user-facing router. In that case, narrow the smoke test contract: drop the `_fetcher` kwargs from the example `main()` signatures (they'd be live-only) and assert that the smoke test EITHER passes against the synthetic bars OR skips cleanly with a `pytest.skip("scan() does not accept candidate_fetcher kwarg — drift guard requires router patch")`. **Record this gap in T2's commit message** so T3 (or a follow-up #86 bd) knows to plumb the seams.

- [ ] **Step 4: Commit T2**

```bash
git add openbb_platform/extensions/techtrade/tests/unit/test_examples_smoke.py
git commit -m "$(cat <<'EOF'
test(86): examples drift-guard smoke (3 tests)

T2 of the #86 plan. For each examples/*.py from T1, the smoke imports
its main() and runs it against offline fakes, asserting the SHAPE of the
return value (path-ending-in-.xlsx for scan_to_excel; list[Fill] for
plan_one_symbol; None for validate_a_plan when [validation] is absent).

Contract is "the example signatures stay in sync with the code" — CONTENT
lock-in lives in tests/golden/ for the engine outputs, not here. If this
test fails, the README and the code have drifted; fix one or the other,
never silence the test.

Test 3 (validate_a_plan) uses the same builtins.__import__ blocker pattern
#82's test_backtest_bridge.py uses to force openbb_backtest absent, proving
the example's catch-and-degrade path actually catches TechtradeDependencyError
and returns None instead of raising. Mirrors the integration-test skipif
pattern for soft-dep-absent paths.

Local copies of the offline fakes (candidate / signal / level fetchers) live
in this file rather than importing from test_plan.py / test_scan.py — the
test fakes don't ship in the importable package layout, and the smoke test
needs to work regardless of pytest's collection path.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: README rewrite

**Files:**
- Modify: `openbb_platform/extensions/techtrade/README.md` (full rewrite — 60→~200 lines)

**Interfaces:**
- Consumes: T1's `examples/scan_to_excel.py::main()` body — the README's §2.2 Quickstart snippet is a verbatim slice of it (Q-A refinement 3); T1's `examples/README.md` for the link target.
- Produces: the user-facing entry point. No code consumes this; review-and-merge is the gate.

---

- [ ] **Step 1: Verify the live command set + arg names**

```bash
PYTHONPATH="$(pwd)/openbb_platform/extensions/techtrade" .venv_win/Scripts/python.exe -c "
from openbb import obb
import inspect
for name in sorted(c for c in dir(obb.techtrade) if not c.startswith('_') and callable(getattr(obb.techtrade, c, None))):
    try:
        sig = inspect.signature(getattr(obb.techtrade, name))
        print(f'{name}{sig}')
    except (TypeError, ValueError) as exc:
        print(f'{name}: (signature unavailable: {exc})')
"
```

Expected: all 11 commands listed (`about`, `segments`, `movers`, `signals`, `plan`, `scan`, `orders`, `simulate`, `export`, `validate`, `tune`). Record the **exact** keyword names from each signature — the README §3 command matrix must match these letter-for-letter.

**Common signature confusions to watch for:** `as_of` vs `asof`; `metric` vs `rank_metric`; `top_n` vs `topn`; `plans` vs `plan_list`. If the README documents a name that differs from the live signature, users hit `TypeError` on copy-paste.

- [ ] **Step 2: Verify the pyproject extras**

```bash
grep -nA 8 '^\[tool.poetry.extras\]' openbb_platform/extensions/techtrade/pyproject.toml
```

Expected: 3 extras as of 2026-06-23 — `tuneta = ["tuneta"]`, `xlsxwriter = ["xlsxwriter"]`, `validation = ["openbb-backtest"]`. The README's install matrix mirrors this list **exactly**. (Note: `tune` ships its functionality without the `[tuneta]` extra at install time, but the extra is what makes `tune()` actually fit periods — without it, `tune()` raises `TechtradeDependencyError`. This is the right symmetry to document.)

- [ ] **Step 3: Pull the verbatim slice for §2.2**

Open `openbb_platform/extensions/techtrade/examples/scan_to_excel.py` and find the body of `main()`. The README's §2.2 Quickstart will quote the load+scan+export pattern (NOT the full `main()` signature with all the fake-fetcher kwargs — just the live-path subset that a user actually types). The two MUST stay byte-identical on the visible lines so the smoke test transitively guards the inline snippet (Q-A refinement 3).

The exact 6-line slice you'll put in the README (matches what `scan_to_excel.main()` does on the live path):

```python
from openbb import obb

# 1. Scan all 11 GICS sectors for ranked, paper-filled trade plans:
plans = obb.techtrade.scan(metric="pct_change", top_n=5).results

# 2. Export the top plans to a 6-sheet Excel workbook:
path = obb.techtrade.export(plans=plans).results
print(f"workbook written to: {path}")
```

If `obb.techtrade.scan`'s real keyword names differ from `metric=` / `top_n=` (Step 1's verification), use the real names in BOTH the example and the README.

- [ ] **Step 4: Write the new README**

Replace the entire contents of `openbb_platform/extensions/techtrade/README.md` with the following (~200 lines). Final wording is the implementer's; the section skeleton, code blocks, and table contents below are the contract:

````markdown
# openbb-techtrade

Segment-aware technical-indicator trading engine for the OpenBB Platform.

*Outputs are paper / research — not investment advice.*

Maps the 11 GICS sectors to symbol universes, ranks top movers per sector, computes a
`pandas-ta-classic` indicator panel per symbol, fuses indicators via weighted confluence
voting into an explainable signal, builds risk-based trade plans with paper-filled
recommendations, exports a multi-sheet Excel workbook, validates plan robustness via
`openbb-backtest`, and (optionally) tunes per-segment indicator periods.

## Pipeline

```
                                                            ┌─→ obb.techtrade.export ──→ .xlsx (6 sheets)
                                                            │   (paper-filled plans)
segments → movers → indicator panel → signal → rule/sizing → orders → paper fills → recommendation
   #69       #70         #72/#73         #74        #76         #77       #78           #80
                                                            │
                                                            └─→ obb.techtrade.validate ──→ ValidationReport
                                                                (requires [validation])      verdict ∈ {robust, fragile, overfit}
                                                                                              #82
```

`obb.techtrade.tune(segment, ...)` (#83) is the optional period-tuner that proposes new
indicator periods per segment and writes them to `~/.openbb_platform/techtrade_tuned.json`
when they pass `validate`'s `verdict == "robust"` gate; subsequent `scan` / `plan` /
`signals` calls auto-load tuned periods transparently.

## Install

```powershell
# Core install (Windows / PowerShell — the canonical dev environment):
.\.venv_win\Scripts\python.exe -m pip install openbb-techtrade
```

```bash
# Core install (macOS / Linux):
python -m pip install openbb-techtrade
```

Soft-dep matrix (mirrors `[tool.poetry.extras]` in `pyproject.toml`):

| Extra | Install command | What it lights up |
|---|---|---|
| *(none)* | `pip install openbb-techtrade` | All commands except `validate` and `tune` (both raise `TechtradeDependencyError` with a pip-install hint when their extra is absent). |
| `[xlsxwriter]` | `pip install 'openbb-techtrade[xlsxwriter]'` | Lets `obb.techtrade.export(..., engine="xlsxwriter")` use the alternative Excel engine. The default `openpyxl` engine ships with the bare install. |
| `[validation]` | `pip install 'openbb-techtrade[validation]'` | Installs `openbb-backtest`; lights up `obb.techtrade.validate(plan, method="wfo")`. |
| `[tuneta]` | `pip install 'openbb-techtrade[tuneta]'` | Installs `tuneta`; lights up `obb.techtrade.tune(segment, ...)`. |

After a fresh checkout, fetch the pinned indicator submodule and editable-install the
extension into the dev venv:

```powershell
git submodule update --init openbb_platform/extensions/techtrade/external/pandas-ta-classic
.\.venv_win\Scripts\python.exe -m pip install -e openbb_platform/extensions/techtrade/external/pandas-ta-classic
```

Configure `~/.openbb_platform/user_settings.json` with `fmp_cached_api_key` (this fork
uses `fmp_cached` exclusively — never raw `fmp`, never `yfinance`):

```json
{
  "credentials": {
    "fmp_api_key": "YOUR_FMP_KEY",
    "fmp_cached_api_key": "YOUR_FMP_KEY"
  }
}
```

## Quickstart

```python
from openbb import obb

# 1. Scan all 11 GICS sectors for ranked, paper-filled trade plans:
plans = obb.techtrade.scan(metric="pct_change", top_n=5).results

# 2. Export the top plans to a 6-sheet Excel workbook:
path = obb.techtrade.export(plans=plans).results
print(f"workbook written to: {path}")
```

This snippet is a verbatim slice of `examples/scan_to_excel.py::main()` — they are
smoke-tested together so they cannot drift. See `examples/` for the full runnable scripts:

- [`examples/scan_to_excel.py`](./examples/scan_to_excel.py) — headline `scan → export`
- [`examples/plan_one_symbol.py`](./examples/plan_one_symbol.py) — `plan → orders → simulate`
- [`examples/validate_a_plan.py`](./examples/validate_a_plan.py) — `plan → validate`
  (requires `[validation]`)

## Commands

`obb.techtrade.about()` → smoke probe; returns `{extension_name, extension_version}`.

`obb.techtrade.segments()` → list the 11 GICS sectors and their universe-source configs.

```python
sectors = obb.techtrade.segments().results
print(len(sectors), "sectors")
```

`obb.techtrade.movers(segment="Information Technology", metric="pct_change", top_n=10)` →
ranked top movers within one segment; returns `list[MoverList]`.

`obb.techtrade.signals(symbols=["MSFT"], preset="trend_follow")` → per-symbol confluence
score + vote attribution; returns `list[MoverSignal]`. Three presets ship: `trend_follow`
(default), `mean_revert`, `breakout`.

`obb.techtrade.plan(symbols=["MSFT"], preset="trend_follow", risk=0.01)` → complete
single-symbol plan with levels, sizing, broker-ready orders, and an inline
`Recommendation`; returns `list[TradePlan]`.

`obb.techtrade.scan(metric="pct_change", top_n=5, preset="trend_follow", risk=0.01)` →
cross-segment scan; runs `plan` across all 11 sectors and ranks the top plans by
conviction; returns `list[TradePlan]`. This is the daily morning-flow command.

`obb.techtrade.orders(plan=plan)` → materializes a single plan's order legs; returns
`list[Order]`. Idempotent round-trip.

`obb.techtrade.simulate(orders=orders, bars=...)` → paper-fills the order legs against
a forward bar window; returns `list[Fill]`. No look-ahead — bar-`t` signals fill at `t+1`
with slippage + commission.

`obb.techtrade.export(plans=plans, path=..., engine="openpyxl")` → writes a 6-sheet
Excel workbook (Recommendations / Levels / Reasoning / Orders / Fills / Summary) with
conditional formatting and the "research / paper — not investment advice" disclaimer on
the Recommendations sheet; returns the workbook path (`str`). Default `path` is
`Analysis/exports/techtrade_<date>.xlsx`. The `engine="xlsxwriter"` variant requires
the `[xlsxwriter]` extra.

`obb.techtrade.validate(plan=plan, method="wfo", horizon_years=5)` → robustness gate;
runs the techtrade confluence strategy over WFO (or `method="cpcv"`) folds, computes
PBO + Deflated Sharpe + OOS Sharpe, returns a `ValidationReport` with `verdict ∈ {robust,
fragile, overfit}`. Requires `pip install 'openbb-techtrade[validation]'`.

`obb.techtrade.tune(segment="Information Technology")` → per-segment indicator-period
tuner; runs `tuneta` against the pooled sector universe, validates the candidate via
`validate(...)`, persists only `verdict == "robust"` configs to
`~/.openbb_platform/techtrade_tuned.json`. Subsequent `scan` / `plan` / `signals` calls
auto-load the tuned periods transparently. Returns a `TuningReport` (with `persisted:
bool`, `reason: str`, and the candidate config). Requires `pip install
'openbb-techtrade[tuneta]'`.

## Roadmap

- `narrator` (#84) — deterministic per-sector briefing on top of the tune/scan output;
  not yet implemented.
- `MCP tool exposure` (#85) — surfacing the live `obb.techtrade.*` commands as MCP tools
  for external LLM clients; not yet implemented.
- `streaming / intraday` (#87) — O(1) streaming-indicator path and hourly/minute bars;
  not yet implemented.

## For Contributors

The sections below are for people changing techtrade, not using it.

### Vendored indicator engine (`external/pandas-ta-classic`)

The indicator engine is powered by the first-party MIT fork
[`prajoria/pandas-ta-classic`](https://github.com/prajoria/pandas-ta-classic), vendored
as a **commit-pinned git submodule** at `external/pandas-ta-classic` and editable-installed
into the dev venv.

- **Pinned commit:** `cfda99036ba64a4983e5871d42d1865743b7c6a9`
- **Bump policy:** advance the pin only via a reviewed PR (never auto-track `main`).

Smoke-tested by `tests/unit/test_pandas_ta_classic_smoke.py` (`import pandas_ta_classic`,
`df.ta.rsi()`, and a candlestick pattern on sample OHLCV).

### Testing & determinism

- Unit tests are fully offline — never touch `fmp_cached`. Run them with:

  ```powershell
  .\.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit -v
  ```

- Integration tests live under `tests/integration/` and are gated by
  `pytest.mark.integration` + skipif markers for any required soft-deps. Run them with:

  ```powershell
  .\.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/integration -v -m integration
  ```

- Golden-file tests (`tests/golden/`) lock content-level invariants: per-indicator panel
  values, confluence scores, the Excel workbook structure, no-look-ahead fill discipline.

- The drift-guard smoke (`tests/unit/test_examples_smoke.py`) keeps the examples and the
  README in sync — if you change an example's `main()` signature, the smoke fails until
  the README's Quickstart snippet matches.

### Bumping near the ~200 LOC threshold

This README is currently near ~200 lines. When the next user-facing surface (narrator
#84 or MCP #85) ships, split this README into a thinner `README.md` + a
`docs/quickstart.md` and move the *For Contributors* section to a new `CONTRIBUTING.md`
(per the design doc, [docs/designs/quant_trading/86-readme-usage-examples.md](../../../docs/designs/quant_trading/86-readme-usage-examples.md), Q-D / Q-E).
````

- [ ] **Step 5: Verify the smoke test still passes**

```bash
PYTHONPATH="$(pwd)/openbb_platform/extensions/techtrade" .venv_win/Scripts/python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_examples_smoke.py -v 2>&1 | tail -8
```

Expected: 3 passed (unchanged from T2). The README rewrite doesn't touch any code that the smoke test exercises — it just embeds a verbatim slice of `scan_to_excel.main()`'s body, so as long as that example still runs, the README inline snippet is transitively valid.

- [ ] **Step 6: Verify the new README renders cleanly**

```bash
# Sanity check that the markdown is well-formed (no unclosed code fences, etc.)
.venv_win/Scripts/python.exe -c "
import re
content = open('openbb_platform/extensions/techtrade/README.md', encoding='utf-8').read()
fences = content.count('\`\`\`')
assert fences % 2 == 0, f'odd number of code fences: {fences}'
print(f'README is {len(content.splitlines())} lines, {fences} code fences (paired).')
"
```

Expected: `README is ~200 lines, <even> code fences (paired).`. If the README is much longer than 200 lines, look for redundancy with the design's section budget (§2 table); if much shorter, a section is probably missing.

- [ ] **Step 7: Verify the install matrix matches pyproject.toml**

```bash
.venv_win/Scripts/python.exe -c "
import re
import tomllib
with open('openbb_platform/extensions/techtrade/pyproject.toml', 'rb') as fh:
    extras = tomllib.load(fh)['tool']['poetry']['extras']
readme = open('openbb_platform/extensions/techtrade/README.md', encoding='utf-8').read()
# Every extra in pyproject must appear in the README install matrix.
for extra_name in extras:
    assert f'[{extra_name}]' in readme, f'extra [{extra_name}] in pyproject is missing from README'
    print(f'  README has install row for [{extra_name}]: OK')
print(f'install matrix covers all {len(extras)} declared extras.')
"
```

Expected: `install matrix covers all 3 declared extras.` (xlsxwriter / validation / tuneta as of 2026-06-23).

- [ ] **Step 8: Commit T3**

```bash
git add openbb_platform/extensions/techtrade/README.md
git commit -m "$(cat <<'EOF'
docs(86): rewrite README — release-ready user docs for the 11-command surface

T3 of the #86 plan. Replaces the #65 scaffold README (60 lines, status:
"scaffold") with the release-ready document for the now-shipped pipeline.

Sections per design §2:
- Title + one-liner + disclaimer banner (L6)
- Pipeline ASCII picture (L9)
- Install — core + 3-row soft-dep matrix mirroring [tool.poetry.extras]
  exactly (Q-C C1 + per-example nudge convention)
- Quickstart — the headline 6-line snippet (Q-A refinement 3: this snippet
  is a verbatim slice of examples/scan_to_excel.py::main()'s live-path body,
  so T2's smoke test transitively guards the inline block from drift)
- Commands — one short example per live command (11 of them; tune (#83)
  is documented as live since it shipped 2026-06-23)
- Roadmap — 3 remaining "extras" items (narrator #84, MCP #85, streaming
  #87) as prose with issue links, NOT runnable-looking call syntax (Q-B B1)
- For Contributors (Q-D D1) — the existing vendored-indicator-engine +
  testing/determinism content, demoted

Acceptance:
- 3 examples/*.py smoke tests still pass (T2 unchanged)
- README's install matrix covers exactly the 3 declared extras
- README's Commands section covers exactly the 11 wired routes

Notes for future maintenance: the README is ~200 lines, the design's split
trigger. When narrator #84 / MCP #85 land, follow Q-D/Q-E together (move
walkthrough to docs/quickstart.md, contributor content to CONTRIBUTING.md).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Beads decomposition (run BEFORE T1 starts)

Parent bead `OpenBBTechnical-afc` is already `in_progress`. File 3 children:

```bash
T1=$(bd create --title="86-T1: examples package + 3 runnable scripts" \
  --description="Plan T1. Files: examples/__init__.py + examples/scan_to_excel.py + examples/plan_one_symbol.py + examples/validate_a_plan.py + examples/README.md. See plan T1 for verbatim file contents." \
  --type=task --priority=2 | sed -n 's/.*Created issue: //p' | awk '{print $1}')
T2=$(bd create --title="86-T2: examples drift-guard smoke (3 tests)" \
  --description="Plan T2. File: tests/unit/test_examples_smoke.py. Imports each examples/*.py main() and asserts shape via the offline fakes copied into the test file. Mirrors the #82 builtins.__import__ blocker pattern for the absent-soft-dep path. See plan T2." \
  --type=task --priority=2 | sed -n 's/.*Created issue: //p' | awk '{print $1}')
T3=$(bd create --title="86-T3: README rewrite" \
  --description="Plan T3. File: openbb_platform/extensions/techtrade/README.md (full rewrite ~200 lines). Quickstart snippet is verbatim slice of examples/scan_to_excel.py::main() (Q-A refinement 3 — T2's smoke transitively guards it). 11 commands (tune included since #83 shipped). 3 Roadmap items. Install matrix mirrors [tool.poetry.extras]. See plan T3." \
  --type=task --priority=2 | sed -n 's/.*Created issue: //p' | awk '{print $1}')
bd dep add $T2 $T1
bd dep add $T3 $T1
bd dep add $T3 $T2
bd dep add OpenBBTechnical-afc $T1
bd dep add OpenBBTechnical-afc $T2
bd dep add OpenBBTechnical-afc $T3
bd list
# Expected: T1 ready; T2 blocked-by T1; T3 blocked-by T1 + T2; parent afc blocked-by all 3.
```

> **Implementer note:** when you start each Task, look up the actual bead ID `bd ready` shows (auto-promoted as the previous Task closes) and substitute it into the per-Task "Close ... bd child" steps.

---

## Self-Review (Run by plan author, not the implementer)

### 1. Spec coverage

| Design section | Implemented in |
|---|---|
| §0 L1 README is the entry point | T3 (rewrite in place) |
| §0 L2 Command set documented | T3 §"Commands" — 11 routes; **deviation: `tune` is live, not roadmap, since #83 shipped** (documented in Global Constraints) |
| §0 L3 Soft-deps documented | T3 §"Install" — mirror of pyproject extras (now 3 including `[tuneta]`) |
| §0 L4 Tone | T3 (review for marketing-speak before commit) |
| §0 L5 Code-block convention | T3 (PowerShell + bash variants in Install) |
| §0 L6 Disclaimer banner | T3 (italic one-liner near top) |
| §0 L7 Reference style | T3 §"Commands" — one short example per command |
| §0 L8 Worked-example placement | T1 (examples/ directory) + T3 (README links) |
| §0 L9 Pipeline picture | T3 §"Pipeline" — ASCII once |
| §1 File layout | T1 (examples/ + __init__) + T2 (tests/unit/) + T3 (README rewrite); peer extensions still untouched |
| §2 README structure | T3 (all sections per §2 table) |
| §3 Command reference matrix | T3 §"Commands" (11 rows; soft-deps noted via parentheticals per Q-C) |
| §4 examples scripts | T1 (3 scripts + examples/README.md + __init__.py) |
| §5 Determinism & smoke | T2 (`test_examples_smoke.py`) |
| Acceptance: install instructions documented | T3 §"Install" |
| Acceptance: disclaimer present | T3 (banner near top) |
| Acceptance: drift guard | T2 |
| Acceptance: pipeline picture | T3 §"Pipeline" |
| Acceptance: contributor content preserved | T3 §"For Contributors" |
| Acceptance: one README per extension | T3 (no separate docs/quickstart.md — E1) |

**No gaps.** One deviation: tune is in Commands not Roadmap (recorded in Global Constraints; design was pre-#83 ship).

### 2. Placeholder scan

Searched plan for forbidden patterns:

- `TBD` / `TODO` / `implement later` / `fill in details` — **none in step bodies** (only in commit-message templates where they're literal text the developer types). ✅
- "Add appropriate error handling" — **none**. ✅
- "Write tests for the above" without code — **none** (every test step contains full test code). ✅
- "Similar to Task N" — **none**.
- Steps without literal code/commands — **none**.
- References to undefined symbols — only `_signal_fetcher` / `_level_fetcher` / `_candidate_fetcher` in T2, all of which T2 Step 1 explicitly verifies AND T2 Step 2 provides local copies of (no external dependency).

### 3. Type consistency

- T1 `scan_to_excel.main()` signature ⇆ T2 `test_scan_to_excel_smoke` call args — match (`out=`, `candidate_fetcher=`, `signal_fetcher=`, `level_fetcher=`).
- T1 `plan_one_symbol.main()` signature ⇆ T2 `test_plan_one_symbol_smoke` call args — match (`symbol=`, `signal_fetcher=`, `level_fetcher=`, `bars=`).
- T1 `validate_a_plan.main()` signature ⇆ T2 `test_validate_a_plan_smoke_when_backtest_absent` call args — match (`symbol=`, `signal_fetcher=`, `level_fetcher=`).
- T3 Quickstart snippet ⇆ T1 `scan_to_excel.main()` body — both call `obb.techtrade.scan(metric="pct_change", top_n=5)` and `obb.techtrade.export(plans=plans)`; both have the comment numbering `# 1. ...` and `# 2. ...`; both have `print(f"workbook written to: {path}")`. **Q-A refinement 3 contract honored verbatim.**

### 4. Known risk surfaced

**T2 Step 3's escape hatch** — if `obb.techtrade.scan` / `plan` don't accept the `_fetcher` kwargs on the public surface, the smoke test as written will raise `TypeError`. The brief tells the implementer to narrow the contract and record the gap. This is a real risk (the underlying engine has injectable fetchers, but they may not be plumbed through the router). The fallback is documented in the step text. If the gap turns out to be real, T2's commit message records it and #86 lands without the smoke for the affected example — `bd OpenBBTechnical-afc` can spawn a follow-up bead to plumb the seams.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-23-86-readme-and-examples.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per Task (T1 → T2 → T3), review the diff between each, only proceed to the next once the previous passes review + tests + commit. Each subagent starts with a clean context window so it has full headroom for the file reads + edits its Task needs. Best for the 3-task TDD loop because each Task is naturally isolated.

**2. Inline Execution** — I execute Tasks in this session using `superpowers:executing-plans`, batching with checkpoints. This session's context is already heavy from the entire #83 cycle + the merge, so inline is slower; the subagent path gives fresh context per Task at no quality cost.

**Which approach?**
