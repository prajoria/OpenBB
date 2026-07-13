# Phase 6: Validation, Docs, Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the openbb-fmp-trading v1 by shipping the optional backtest-bridge validator, running end-to-end integration tests against live `fmp_cached`, closing the 4 target GitHub epics, filing post-v1 follow-ups, and polishing `pyproject.toml` for release.

**Architecture:** Phase 6 is a validation + governance phase — it adds one thin new surface (`obb.fmp_trading.validate(...)` behind the optional `[validation]` extra, delegating to `openbb-backtest`'s WFO/CPCV harness), proves the extension works end-to-end against real infrastructure (real FMP calls, real MySQL cache, real market data), and formally retires the 4 in-flight design epics that this PRD supersedes.

**Tech Stack:**
- Python 3.10-3.13
- `openbb-fmp-trading` extension (Phases 0-5 already merged)
- `openbb-backtest` extension (#82 backtest_bridge, already merged upstream) — imported lazily
- `openbb-fmp-cached` (only provider — never raw `fmp`)
- MySQL cache (Phase 3 infra)
- `pytest` with `@pytest.mark.live` marker
- `gh` CLI for epic closure + follow-up filing

## Global Constraints

**CODEGEN CRITICAL:** Every router command's return type is annotated as **bare `OBBject`**, never `OBBject[ValidationReport]` or any parameterized form. The Fast/OpenAPI codegen chokes on parameterized OBBject in this extension's package layout. If you find yourself typing `OBBject[` in a router file, stop and use bare `OBBject`.

- **Provider:** always `fmp_cached` — never raw `fmp`, never `yfinance`. Anywhere you see a `provider=` kwarg default, it must be `"fmp_cached"`.
- **Every command returns bare `OBBject`** — no generic parameterization on router return types.
- **`[validation]` extra is OPTIONAL** — extension core must import, register, and run without `openbb-backtest` installed. The validate router registers itself lazily from `fmp_trading_router.py` inside a `try/except ImportError` guard.
- **"Core-unchanged-when-removed" test still passes** — the existing Phase 5 test that asserts removing the extension leaves openbb-core intact must remain green after Phase 6 additions.
- **Live integration tests are opt-in** — marked `@pytest.mark.live`, excluded by default via `pytest.ini` `-m "not live"` filter.
- **Never commit secrets** — `.env` and `~/.openbb_platform/user_settings.json` stay gitignored; CI uses repo secrets for FMP keys.

---

## Task P6.1: Backtest Bridge — `obb.fmp_trading.validate(...)`

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/backtest_bridge.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/validate_router.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_validation_optional.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_backtest_bridge_translation.py`

**Consumes:**
- Phase 2 intraday endpoints (`fmp_cached` 5-minute bars) — historical replay source
- Phase 4 confluence preset definitions (the "intraday_confluence" preset dict)
- techtrade #82 `openbb_backtest.harness.WFOHarness` + `CPCVHarness` (optional dep)

**Produces:**
- New optional command `obb.fmp_trading.validate(preset, start_date, end_date, method, n_splits, provider)`
- `ValidationReport` dict: `{verdict, pbo, deflated_sharpe, n_splits, oos_sharpe_mean, oos_sharpe_std, config_hash}`
- Custom exception `FmpTradingDependencyError` with pip-install hint
- Unit tests that pass whether or not `[validation]` is installed

### Steps

- [ ] **1. Create the validation package skeleton**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/__init__.py`:

```python
"""Optional validation subpackage — depends on openbb-backtest.

This subpackage is only importable when the [validation] extra is installed.
Callers must guard imports with try/except ImportError.
"""

from openbb_fmp_trading.validation.backtest_bridge import (
    BacktestBridge,
    FmpTradingDependencyError,
    ValidationReport,
)

__all__ = ["BacktestBridge", "FmpTradingDependencyError", "ValidationReport"]
```

- [ ] **2. Implement the backtest bridge with lazy import**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/backtest_bridge.py`:

```python
"""Thin wrapper over openbb-backtest #82 (backtest_bridge).

Translates the intraday confluence preset from Phase 4 into a BacktestConfig
that openbb-backtest's WFO/CPCV harness can execute over historical 5-min bars.

The openbb_backtest import is deferred to method-call time so that merely
importing this module does not require the [validation] extra.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from openbb_fmp_trading.confluence.presets import load_preset


class FmpTradingDependencyError(ImportError):
    """Raised when an optional extra is required but not installed."""

    def __init__(self, extra: str) -> None:
        super().__init__(
            f"The '{extra}' extra is required for this operation. "
            f"Install with: pip install 'openbb-fmp-trading[{extra.strip('[]')}]'"
        )
        self.extra = extra


@dataclass(frozen=True)
class ValidationReport:
    """Result of running a preset through the backtest validation harness."""

    verdict: Literal["robust", "fragile", "overfit"]
    pbo: float                # Probability of Backtest Overfitting, [0.0, 1.0]
    deflated_sharpe: float    # Deflated Sharpe Ratio
    n_splits: int
    oos_sharpe_mean: float
    oos_sharpe_std: float
    method: Literal["wfo", "cpcv"]
    preset_name: str
    start_date: str           # ISO-formatted
    end_date: str
    config_hash: str          # stable hash of the resolved BacktestConfig

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BacktestBridge:
    """Bridge that translates preset → BacktestConfig → validation run."""

    def __init__(self, provider: str = "fmp_cached") -> None:
        if provider != "fmp_cached":
            raise ValueError(
                f"BacktestBridge only supports 'fmp_cached', got {provider!r}"
            )
        self.provider = provider

    def _import_backtest(self):
        """Deferred import — raises FmpTradingDependencyError if missing."""
        try:
            import openbb_backtest  # noqa: F401
            from openbb_backtest.config import BacktestConfig
            from openbb_backtest.harness import CPCVHarness, WFOHarness
        except ImportError as exc:
            raise FmpTradingDependencyError("[validation]") from exc
        return BacktestConfig, WFOHarness, CPCVHarness

    def _preset_to_config(
        self,
        preset_name: str,
        start_date: date,
        end_date: date,
        BacktestConfig: Any,
    ) -> Any:
        """Translate a Phase 4 preset dict into a BacktestConfig."""
        preset = load_preset(preset_name)
        return BacktestConfig(
            symbols=preset["universe"],
            start=start_date,
            end=end_date,
            interval="5min",
            provider=self.provider,
            strategy_id="fmp_trading.confluence",
            strategy_params={
                "signals": preset["signals"],
                "weights": preset["weights"],
                "threshold": preset["threshold"],
                "cooldown_bars": preset.get("cooldown_bars", 3),
            },
            cash=preset.get("starting_cash", 100_000.0),
            slippage_bps=preset.get("slippage_bps", 3),
            fee_bps=preset.get("fee_bps", 1),
        )

    @staticmethod
    def _hash_config(cfg: Any) -> str:
        payload = json.dumps(asdict(cfg), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @staticmethod
    def _classify(pbo: float, deflated_sharpe: float) -> str:
        """Verdict rubric from techtrade #82 spec §4.3."""
        if pbo >= 0.5 or deflated_sharpe <= 0.0:
            return "overfit"
        if pbo >= 0.3 or deflated_sharpe < 0.5:
            return "fragile"
        return "robust"

    def validate(
        self,
        preset: str,
        start_date: date,
        end_date: date,
        method: Literal["wfo", "cpcv"] = "wfo",
        n_splits: int = 5,
    ) -> ValidationReport:
        BacktestConfig, WFOHarness, CPCVHarness = self._import_backtest()
        cfg = self._preset_to_config(preset, start_date, end_date, BacktestConfig)
        harness_cls = WFOHarness if method == "wfo" else CPCVHarness
        harness = harness_cls(cfg, n_splits=n_splits)
        result = harness.run()

        verdict = self._classify(result.pbo, result.deflated_sharpe)
        return ValidationReport(
            verdict=verdict,               # type: ignore[arg-type]
            pbo=result.pbo,
            deflated_sharpe=result.deflated_sharpe,
            n_splits=n_splits,
            oos_sharpe_mean=result.oos_sharpe_mean,
            oos_sharpe_std=result.oos_sharpe_std,
            method=method,
            preset_name=preset,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            config_hash=self._hash_config(cfg),
        )
```

- [ ] **3. Implement the validate router (bare OBBject!)**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/validate_router.py`:

```python
"""Router exposing obb.fmp_trading.validate(...).

CRITICAL: return type is bare OBBject — never OBBject[ValidationReport].
The Fast/OpenAPI codegen breaks on parameterized OBBject in this layout.
"""

from datetime import date
from typing import Literal

from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import Field
from typing_extensions import Annotated

from openbb_fmp_trading.validation.backtest_bridge import BacktestBridge

validate_router = Router(prefix="/validate")


@validate_router.command(
    methods=["POST"],
    examples=[
        'obb.fmp_trading.validate(preset="intraday_confluence", '
        'start_date="2025-01-02", end_date="2025-06-30")',
    ],
)
def validate(
    cc: CommandContext,
    preset: Annotated[
        str,
        Field(description="Confluence preset name (e.g. 'intraday_confluence')."),
    ],
    start_date: Annotated[
        date,
        Field(description="Historical replay start (inclusive)."),
    ],
    end_date: Annotated[
        date,
        Field(description="Historical replay end (inclusive)."),
    ],
    method: Annotated[
        Literal["wfo", "cpcv"],
        Field(description="Validation method: walk-forward or CPCV."),
    ] = "wfo",
    n_splits: Annotated[
        int,
        Field(description="Number of validation splits.", ge=2, le=20),
    ] = 5,
    provider: Annotated[
        str,
        Field(description="Data provider — must be 'fmp_cached'."),
    ] = "fmp_cached",
) -> OBBject:  # BARE — do NOT parameterize
    """Run a confluence preset through the WFO/CPCV validation harness.

    Requires the [validation] extra:  pip install 'openbb-fmp-trading[validation]'
    """
    bridge = BacktestBridge(provider=provider)
    report = bridge.validate(
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        method=method,
        n_splits=n_splits,
    )
    return OBBject(results=report.to_dict())
```

- [ ] **4. Register validate_router lazily in the top-level router**

Edit `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py` — add the lazy registration below the existing router setup (near the bottom of the file, after any existing `include_router` calls):

```python
# --- Optional [validation] extra ------------------------------------------
# Register validate_router only if openbb-backtest is installed. The core
# extension MUST import cleanly without it — see Phase 5 core-unchanged test.
try:
    from openbb_fmp_trading.validation.validate_router import validate_router

    router.include_router(validate_router)
except ImportError:
    # openbb-backtest not installed → obb.fmp_trading.validate simply
    # will not exist in this environment. Documented behavior.
    pass
```

- [ ] **5. Write unit tests that verify optional-ness**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_validation_optional.py`:

```python
"""Verify that fmp_trading imports cleanly with or without [validation]."""

import importlib
import sys

import pytest


def test_core_import_without_backtest(monkeypatch):
    """Removing openbb_backtest from sys.modules must not break fmp_trading."""
    # Force-fail any openbb_backtest import
    real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict
    ) else __builtins__.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("openbb_backtest"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)

    # Purge any cached modules that might have imported openbb_backtest
    for mod in list(sys.modules):
        if mod.startswith(("openbb_fmp_trading", "openbb_backtest")):
            sys.modules.pop(mod, None)

    # This must succeed even when openbb-backtest is unavailable
    fmp_trading = importlib.import_module("openbb_fmp_trading.fmp_trading_router")
    assert fmp_trading.router is not None


def test_validate_raises_with_hint_when_backtest_absent(monkeypatch):
    from openbb_fmp_trading.validation.backtest_bridge import (
        BacktestBridge,
        FmpTradingDependencyError,
    )

    real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict
    ) else __builtins__.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("openbb_backtest"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    for mod in list(sys.modules):
        if mod.startswith("openbb_backtest"):
            sys.modules.pop(mod, None)

    bridge = BacktestBridge()
    from datetime import date

    with pytest.raises(FmpTradingDependencyError) as exc:
        bridge.validate("intraday_confluence", date(2025, 1, 2), date(2025, 6, 30))
    assert "[validation]" in str(exc.value)
    assert "pip install" in str(exc.value)
```

- [ ] **6. Write a translation-only unit test (no backtest run)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_backtest_bridge_translation.py`:

```python
"""Test preset → BacktestConfig translation without executing a backtest.

Uses a lightweight stub for BacktestConfig so no openbb-backtest install
is required to run these tests.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from openbb_fmp_trading.validation.backtest_bridge import BacktestBridge


@dataclass
class _StubBacktestConfig:
    symbols: list[str]
    start: date
    end: date
    interval: str
    provider: str
    strategy_id: str
    strategy_params: dict[str, Any] = field(default_factory=dict)
    cash: float = 100_000.0
    slippage_bps: int = 3
    fee_bps: int = 1


def test_preset_translation_uses_fmp_cached(monkeypatch):
    bridge = BacktestBridge(provider="fmp_cached")
    cfg = bridge._preset_to_config(
        "intraday_confluence",
        date(2025, 1, 2),
        date(2025, 6, 30),
        _StubBacktestConfig,
    )
    assert cfg.provider == "fmp_cached"
    assert cfg.interval == "5min"
    assert cfg.strategy_id == "fmp_trading.confluence"
    assert "signals" in cfg.strategy_params


def test_provider_guard_rejects_raw_fmp():
    with pytest.raises(ValueError, match="fmp_cached"):
        BacktestBridge(provider="fmp")


@pytest.mark.parametrize(
    ("pbo", "dsr", "expected"),
    [
        (0.10, 1.20, "robust"),
        (0.35, 0.80, "fragile"),
        (0.25, 0.30, "fragile"),
        (0.60, 0.50, "overfit"),
        (0.20, -0.10, "overfit"),
    ],
)
def test_verdict_classification(pbo, dsr, expected):
    assert BacktestBridge._classify(pbo, dsr) == expected


def test_config_hash_is_stable(monkeypatch):
    bridge = BacktestBridge()
    cfg1 = bridge._preset_to_config(
        "intraday_confluence", date(2025, 1, 2), date(2025, 6, 30), _StubBacktestConfig
    )
    cfg2 = bridge._preset_to_config(
        "intraday_confluence", date(2025, 1, 2), date(2025, 6, 30), _StubBacktestConfig
    )
    assert bridge._hash_config(cfg1) == bridge._hash_config(cfg2)
```

- [ ] **7. Run unit tests and rebuild the platform**

```bash
.venv_win\Scripts\python.exe -m pytest \
  openbb_platform/extensions/fmp_trading/tests/unit/test_validation_optional.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_backtest_bridge_translation.py \
  -v
```

Expected output:
```
tests/unit/test_validation_optional.py::test_core_import_without_backtest PASSED
tests/unit/test_validation_optional.py::test_validate_raises_with_hint_when_backtest_absent PASSED
tests/unit/test_backtest_bridge_translation.py::test_preset_translation_uses_fmp_cached PASSED
tests/unit/test_backtest_bridge_translation.py::test_provider_guard_rejects_raw_fmp PASSED
tests/unit/test_backtest_bridge_translation.py::test_verdict_classification[0.1-1.2-robust] PASSED
tests/unit/test_backtest_bridge_translation.py::test_verdict_classification[0.35-0.8-fragile] PASSED
tests/unit/test_backtest_bridge_translation.py::test_verdict_classification[0.25-0.3-fragile] PASSED
tests/unit/test_backtest_bridge_translation.py::test_verdict_classification[0.6-0.5-overfit] PASSED
tests/unit/test_backtest_bridge_translation.py::test_verdict_classification[0.2--0.1-overfit] PASSED
tests/unit/test_backtest_bridge_translation.py::test_config_hash_is_stable PASSED
========================= 10 passed in 0.42s =========================
```

Then rebuild so `obb.fmp_trading.validate` becomes discoverable when the extra is installed:
```bash
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
```

- [ ] **8. Commit**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/validation/ \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py \
        openbb_platform/extensions/fmp_trading/tests/unit/test_validation_optional.py \
        openbb_platform/extensions/fmp_trading/tests/unit/test_backtest_bridge_translation.py

git commit -m "$(cat <<'EOF'
feat(fmp_trading): add optional [validation] backtest bridge (P6.1)

Adds obb.fmp_trading.validate(preset, start_date, end_date, method, n_splits,
provider) as an optional command behind the [validation] Poetry extra.

- Lazy-imports openbb-backtest — extension core still imports cleanly when
  [validation] is absent; missing dep raises FmpTradingDependencyError with
  a pip-install hint.
- Router return type is BARE OBBject (parameterized breaks codegen).
- Provider guard: fmp_cached only, never raw fmp.
- Verdict rubric (robust/fragile/overfit) matches techtrade #82 §4.3.

Refs: #82 (techtrade backtest_bridge), PRD §10 P6.1.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Verification

- `pip install openbb-fmp-trading` (without `[validation]`) → `import openbb_fmp_trading` succeeds; `obb.fmp_trading.validate` is absent from the OBB namespace.
- `pip install 'openbb-fmp-trading[validation]'` → `obb.fmp_trading.validate(...)` is callable and returns an `OBBject` whose `.results` dict has keys `verdict`, `pbo`, `deflated_sharpe`, `config_hash`.
- All 10 unit tests pass in <1s.
- Codegen sanity check: `grep -R "OBBject\[" openbb_platform/extensions/fmp_trading/openbb_fmp_trading/` returns **zero hits**.

---

## Task P6.2: Close 4 Target Epics (#87, #84, #85, #231)

**Files:** No source changes — this task is pure GitHub bookkeeping using `gh`.

**Consumes:**
- The merged PRD spec (`docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`)
- The merged Phase 0-5 implementation PRs
- The Phase 6 PR from tasks P6.1 + P6.3-P6.5

**Produces:**
- 4 closed GitHub epics with linkbacks to superseding PRs and to the PRD
- A closure audit trail visible from `gh issue list --state closed --label epic`

### Steps

- [ ] **1. Confirm epic titles before commenting (never cite a bare number — CLAUDE.md rule)**

```bash
gh issue view 87  --json number,title,state,labels --jq '"\(.number) \(.title) [\(.state)]"'
gh issue view 84  --json number,title,state,labels --jq '"\(.number) \(.title) [\(.state)]"'
gh issue view 85  --json number,title,state,labels --jq '"\(.number) \(.title) [\(.state)]"'
gh issue view 231 --json number,title,state,labels --jq '"\(.number) \(.title) [\(.state)]"'
```

Expected (titles will vary — record exactly what `gh` returns and use those below):
```
87 P9 streaming/intraday + live broker interface [OPEN]
84 Narrator — deterministic briefing generator [OPEN]
85 MCP tool exposure + core-unchanged-when-removed test [OPEN]
231 Design specs for #84 (Narrator) + #85 (MCP exposure) [OPEN]
```

- [ ] **2. Capture the merged PR numbers for linkback**

Record the merged PR numbers for each phase in a scratch file so the closure comments are precise:

```bash
gh pr list --state merged --search "fmp_trading Phase" \
  --json number,title,mergedAt \
  --jq '.[] | "\(.number)  \(.mergedAt[0:10])  \(.title)"'
```

Expected (example):
```
418  2026-07-01  Phase 5 — MCP + xlsxwriter + core-unchanged test
399  2026-06-25  Phase 4 — Confluence engine + presets
...
```

Store the Phase 5 PR number as `$PR_P5` and the current Phase 6 PR number as `$PR_P6` (set after `gh pr create` in Task P6.5).

- [ ] **3. Close #87 (streaming/intraday + live broker)**

```bash
gh issue comment 87 --body "$(cat <<'EOF'
Closed by the openbb-fmp-trading extension shipped in the following phases:

- Phase 2 (intraday endpoints, 5-min bars via fmp_cached) — PR #<P2>
- Phase 3 (session engine, MySQL-backed replay, BrokerInterface abstraction) — PR #<P3>
- Phase 4 (confluence signal engine + presets) — PR #<P4>
- Phase 5 (MCP exposure + xlsxwriter reporting) — PR #<P5>
- Phase 6 (optional [validation] backtest bridge + live integration tests) — PR #<P6>

The Phase 3 BrokerInterface (`openbb_fmp_trading/brokers/base.py`) is the
extension point for a live broker; the paper adapter is the default v1 impl.

See the full design in:
`docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`
EOF
)"

gh issue close 87 --reason completed
```

Expected: `gh issue view 87 --json state --jq .state` returns `"CLOSED"`.

- [ ] **4. Close #84 (Narrator — deterministic briefing)**

```bash
gh issue comment 84 --body "$(cat <<'EOF'
Closed by the openbb-fmp-trading Narrator, shipped in Phase 5:

- `openbb_fmp_trading/narrator/briefing.py` — deterministic Markdown briefing
  from SessionResult (same input → byte-identical output; verified by
  golden-file test).
- Optional [agent] extra wires the briefing through the MCP tool surface for
  agentic consumers.

Implementation PR: #<P5>
Design in: `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md` §7
EOF
)"

gh issue close 84 --reason completed
```

- [ ] **5. Close #85 (MCP tool exposure + core-unchanged-when-removed test)**

```bash
gh issue comment 85 --body "$(cat <<'EOF'
Closed by openbb-fmp-trading Phase 5:

- Extension registers as an MCP toolset via the `[agent]` extra
  (`openbb_fmp_trading/mcp/server.py`).
- The core-unchanged-when-removed contract test lives at
  `openbb_platform/extensions/fmp_trading/tests/unit/test_core_unchanged_when_removed.py`
  and passes on every CI run.
- Phase 6 (PR #<P6>) preserves this contract: the new optional [validation]
  extra also does not perturb openbb-core when uninstalled.

Implementation PR: #<P5>
Design in: `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md` §8
EOF
)"

gh issue close 85 --reason completed
```

- [ ] **6. Close #231 (design specs for #84 + #85)**

```bash
gh issue comment 231 --body "$(cat <<'EOF'
Closed — the design specs originally called for in this issue were superseded
and absorbed into the unified PRD:

`docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`

- §7 covers the Narrator (originally #84's design spec)
- §8 covers the MCP tool exposure (originally #85's design spec)

Both implementations shipped in Phase 5 (PR #<P5>) and are validated by
the Phase 6 live integration suite (PR #<P6>).
EOF
)"

gh issue close 231 --reason completed
```

- [ ] **7. Verify all four are closed**

```bash
gh issue list --state closed --search "87 84 85 231" \
  --json number,title,state,closedAt \
  --jq '.[] | "\(.number)  \(.state)  \(.closedAt[0:10])  \(.title)"'
```

Expected: 4 rows, all `CLOSED`, all with closure dates from today.

### Verification

- Each closed issue's most recent comment references the PRD path and the specific superseding PR number.
- `gh issue view <N>` on each of the four shows `state: CLOSED` and `stateReason: completed`.
- No open epic remains that duplicates the PRD scope (spot-check by searching the epic label): `gh issue list --label epic --state open --search "fmp trading"` returns zero rows.

---

## Task P6.3: File Post-v1 Follow-up Issues

**Files:** No source changes — `gh` bookkeeping only.

**Consumes:**
- PRD §5.6 (FMP `/api/v3/*` → `/stable/*` migration tech-debt)
- PRD non-goal NG7 (AlertManager v2 delivery channels)
- Phase 4 alert-engine limitations (threshold-only, no pattern detection)

**Produces:**
- 3 new open issues on the `openbb-fmp-trading` epic label, all tagged `post-v1`
- Each issue has: motivation, acceptance criteria, effort estimate, and dependency notes

### Steps

- [ ] **1. File the AlertManager v2 follow-up (multi-channel delivery)**

```bash
gh issue create \
  --title "AlertManager v2: webhook/push/email delivery channels (post-v1)" \
  --label "post-v1,fmp-trading,enhancement" \
  --body "$(cat <<'EOF'
## Motivation

v1 AlertManager (shipped in Phase 4) is threshold-based and emits alerts only
to stdout + JSON log. Per PRD non-goal NG7, real delivery channels were
deliberately deferred. This issue tracks the v2 delivery layer.

## Scope

Extend `openbb_fmp_trading/alerts/manager.py` with a pluggable
`AlertChannel` abstraction and ship three built-in implementations:

- **WebhookChannel** — POST JSON to a user-configured URL with HMAC signature
- **EmailChannel** — SMTP via `email-validator` + Python stdlib `smtplib`
- **PushChannel** — Pushover / ntfy.sh / Apple Push (evaluate; start with ntfy)

## Acceptance criteria

- [ ] `AlertChannel(ABC)` with `deliver(alert: Alert) -> DeliveryReceipt`
- [ ] Config surface via `user_settings.json` — never hardcoded credentials
- [ ] Delivery retries with exponential backoff (max 3 attempts)
- [ ] Unit tests using `responses`/`aiosmtpd` fixtures — no real network
- [ ] Integration test suite skipped by default (`@pytest.mark.live`)
- [ ] AlertManager continues to fall back to stdout when all channels fail
- [ ] Documented in `README.md` under \"Alert delivery\"

## Effort

M (~1.5 weeks). Depends on nothing — self-contained addition.

## References

- PRD non-goal NG7: `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`
- v1 impl: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/alerts/manager.py`
EOF
)"
```

- [ ] **2. File the FMP `/api/v3/*` → `/stable/*` migration follow-up**

```bash
gh issue create \
  --title "FMP: migrate gainers/losers/actives from /api/v3/* to /stable/* (post-v1)" \
  --label "post-v1,fmp-trading,tech-debt" \
  --body "$(cat <<'EOF'
## Motivation

Per PRD §5.6, the current fmp_cached fetchers for `market_movers_gainers`,
`market_movers_losers`, and `market_movers_actives` still hit the legacy
`/api/v3/*` endpoints. FMP's `/stable/*` variants are the supported long-term
surface (better rate limits, more consistent schema). This is pre-existing
tech debt inherited from openbb-fmp — not a Phase 0-6 regression.

## Scope

- Update `openbb_fmp_cached/models/market_movers_*` fetcher URLs
- Reconcile any field-name deltas between `/api/v3` and `/stable` responses
- Update the fmp_cached test cassettes
- Bump `openbb-fmp-cached` minor version

## Acceptance criteria

- [ ] All three market_movers fetchers hit `/stable/*` URLs
- [ ] fmp_cached unit tests pass against the new cassettes
- [ ] fmp_trading Phase 0 `session_bootstrap` integration test still green
- [ ] No behavioral regression in `SessionEngine` universe expansion (Phase 3)
- [ ] Changelog entry in both `openbb-fmp-cached` and `openbb-fmp-trading`

## Effort

S (~2-3 days). Well-scoped mechanical change with test-suite guardrails.

## References

- PRD §5.6: `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`
- FMP `/stable` docs: https://site.financialmodelingprep.com/developer/docs/stable
EOF
)"
```

- [ ] **3. File the pattern-based alerts v2 follow-up**

```bash
gh issue create \
  --title "AlertRules v2: breakout, wedge, chart-formation ML detectors (post-v1)" \
  --label "post-v1,fmp-trading,research" \
  --body "$(cat <<'EOF'
## Motivation

v1 AlertRules (Phase 4) are threshold-based only:
- price crosses X
- indicator crosses Y
- volume > N × avg

This issue tracks pattern-level detectors — a substantially larger design
task that warrants its own spec + prototype cycle.

## Scope (research phase)

- Enumerate target patterns: bull/bear flag, ascending/descending wedge,
  head-and-shoulders, double top/bottom, cup-and-handle, breakout confirmation
- Evaluate implementation approaches:
  1. **Rule-based** (pivot detection + geometric fit — deterministic, fast)
  2. **Classical ML** (features + XGBoost — needs a labeled dataset)
  3. **Deep learning** (CNN over price rasters — heaviest, best accuracy)
- Prototype the strongest approach on the SPY/QQQ 5-min history in the
  fmp_cached cache; measure precision/recall against a manually labeled set.
- Write a design spec analogous to the Phase 4 alerts spec.

## Acceptance criteria (research deliverable — implementation is a separate issue)

- [ ] Design spec at `docs/superpowers/specs/YYYY-MM-DD-pattern-alerts-v2.md`
- [ ] Prototype notebook with precision/recall numbers
- [ ] Recommendation on which detectors to ship in v2.0

## Effort

L for research (~2-4 weeks). Implementation issue TBD after spec lands.

## References

- v1 impl: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/alerts/rules.py`
- PRD §5 alert-scope statement
EOF
)"
```

- [ ] **4. Verify the three issues exist and are open**

```bash
gh issue list --label post-v1 --state open --search "fmp-trading" \
  --json number,title,labels \
  --jq '.[] | "\(.number)  \(.title)"'
```

Expected: 3 rows, each with the exact titles above.

### Verification

- All three issues visible under `gh issue list --label post-v1`.
- Each links to the PRD by relative path and includes an effort estimate.
- Follow-up issue for AlertManager v2 explicitly cites NG7 (so future readers can trace the deferral rationale).

---

## Task P6.4: Live Integration Tests Against `fmp_cached`

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/tests/integration/__init__.py` (if missing)
- Create: `openbb_platform/extensions/fmp_trading/tests/integration/test_live_fmp_cached_session.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/integration/test_live_cache_hit_rate.py`
- Modify: `openbb_platform/extensions/fmp_trading/pytest.ini` (or `pyproject.toml [tool.pytest.ini_options]`)

**Consumes:**
- Phase 3 `SessionEngine`, `SessionConfig`, `SessionResult`
- Phase 2 fmp_cached intraday endpoints
- MySQL cache (must be running locally or in CI — see fixture below)
- `~/.openbb_platform/user_settings.json` with a valid `fmp_cached_api_key`

**Produces:**
- Two `@pytest.mark.live` integration tests validating PRD acceptance
  criteria AC-1 (end-to-end session completes cleanly) and AC-3 (tier-1
  cache hit rate ≥ 95% on second run)
- A `live` marker registered in `pytest.ini` and excluded from the default
  test run

### Steps

- [ ] **1. Register the `live` marker and exclude it from default runs**

Modify `openbb_platform/extensions/fmp_trading/pyproject.toml` — add the pytest config block if not already present:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: requires external API access + credentials",
    "live: requires live FMP calls + running MySQL (opt-in only)",
]
addopts = "-m 'not live'"
```

- [ ] **2. Create the session-level live test**

Create `openbb_platform/extensions/fmp_trading/tests/integration/test_live_fmp_cached_session.py`:

```python
"""AC-1: run a short live session end-to-end against real fmp_cached + MySQL.

Marked live — excluded from the default pytest run. Run explicitly with:

    .venv_win\\Scripts\\python.exe -m pytest \\
        openbb_platform/extensions/fmp_trading/tests/integration/test_live_fmp_cached_session.py \\
        -m live -v -s
"""

from __future__ import annotations

import os
from datetime import date, time

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def credentials_present():
    """Skip the module if fmp_cached_api_key is not configured."""
    from openbb_core.app.service.user_service import UserService

    user = UserService().default_user_settings
    key = getattr(user.credentials, "fmp_cached_api_key", None)
    if not key:
        pytest.skip("fmp_cached_api_key missing from user_settings.json")
    return True


@pytest.fixture(scope="module")
def mysql_reachable():
    """Skip if the fmp_cached MySQL cache is not reachable."""
    host = os.environ.get("FMP_CACHE_MYSQL_HOST", "localhost")
    port = int(os.environ.get("FMP_CACHE_MYSQL_PORT", "3306"))
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        try:
            s.connect((host, port))
        except OSError:
            pytest.skip(f"MySQL not reachable at {host}:{port}")
    return True


def test_short_live_session_flat_at_close(credentials_present, mysql_reachable):
    """AC-1: SessionEngine runs a 10-min slice, exits cleanly, ends flat."""
    from openbb_fmp_trading.session.config import SessionConfig
    from openbb_fmp_trading.session.engine import SessionEngine

    cfg = SessionConfig(
        session_date=date.today(),
        start_time=time(9, 30),
        end_time=time(9, 40),          # 10-minute slice
        preset="intraday_confluence",
        provider="fmp_cached",
        starting_cash=100_000.0,
        max_positions=3,
        mode="paper",
    )

    engine = SessionEngine(cfg)
    result = engine.run()

    assert result.exit_code == 0, f"Session exit_code={result.exit_code}"
    assert result.flat_at_close is True, "Session ended with open positions"
    assert result.n_bars_processed > 0, "No bars processed — bootstrap broken?"
    assert result.session_id, "SessionResult.session_id must be populated"

    # PnL sanity — this is a live test, PnL can be positive or negative
    assert isinstance(result.realized_pnl, float)
    assert isinstance(result.unrealized_pnl, float)
    # After flat_at_close there should be no unrealized
    assert abs(result.unrealized_pnl) < 1e-6
```

- [ ] **3. Create the cache-hit-rate live test**

Create `openbb_platform/extensions/fmp_trading/tests/integration/test_live_cache_hit_rate.py`:

```python
"""AC-3: on a repeat replay, ≥95% of FMP calls served from cache.

The fmp_cached provider exposes a counter of upstream FMP HTTP calls. We run
the same slice twice; the second run must issue <5% of the first run's calls.
"""

from __future__ import annotations

import os
from datetime import date, time

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def credentials_and_mysql():
    from openbb_core.app.service.user_service import UserService

    user = UserService().default_user_settings
    if not getattr(user.credentials, "fmp_cached_api_key", None):
        pytest.skip("fmp_cached_api_key missing")

    import socket

    host = os.environ.get("FMP_CACHE_MYSQL_HOST", "localhost")
    port = int(os.environ.get("FMP_CACHE_MYSQL_PORT", "3306"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        try:
            s.connect((host, port))
        except OSError:
            pytest.skip(f"MySQL not reachable at {host}:{port}")
    return True


def _run_slice_and_count_calls():
    """Return the number of upstream FMP calls emitted during one session run."""
    from openbb_fmp_cached.metrics import upstream_call_counter
    from openbb_fmp_trading.session.config import SessionConfig
    from openbb_fmp_trading.session.engine import SessionEngine

    upstream_call_counter.reset()
    cfg = SessionConfig(
        session_date=date.today(),
        start_time=time(10, 0),
        end_time=time(10, 10),
        preset="intraday_confluence",
        provider="fmp_cached",
        starting_cash=100_000.0,
        max_positions=3,
        mode="paper",
    )
    SessionEngine(cfg).run()
    return upstream_call_counter.value()


def test_second_run_hits_cache_at_least_95_percent(credentials_and_mysql):
    """AC-3: cache warmup then replay — second run must be ≥95% cache-served."""
    first = _run_slice_and_count_calls()
    assert first > 0, "First run made zero FMP calls — cache-hit test is meaningless"

    second = _run_slice_and_count_calls()
    hit_rate = 1.0 - (second / first)
    assert hit_rate >= 0.95, (
        f"AC-3 violated: cache hit rate {hit_rate:.1%} "
        f"(first={first} upstream calls, second={second}). Need ≥95%."
    )
```

- [ ] **4. Run the unit + integration suites (non-live) to confirm the `live` marker filters correctly**

```bash
.venv_win\Scripts\python.exe -m pytest \
  openbb_platform/extensions/fmp_trading/tests/ -v
```

Expected: all existing tests pass; the two new files are collected but **skipped** because of `addopts = "-m 'not live'"`. You should see something like:
```
====== 132 passed, 2 deselected in 4.51s ======
```

- [ ] **5. Run the live tests explicitly (locally, once — do not add to default CI job)**

Prerequisite: MySQL cache is up (see `openbb-fmp-cached` README), `fmp_cached_api_key` is set in `~/.openbb_platform/user_settings.json`.

```bash
.venv_win\Scripts\python.exe -m pytest \
  openbb_platform/extensions/fmp_trading/tests/integration/test_live_fmp_cached_session.py \
  openbb_platform/extensions/fmp_trading/tests/integration/test_live_cache_hit_rate.py \
  -m live -v -s
```

Expected output (numbers will vary):
```
test_live_fmp_cached_session.py::test_short_live_session_flat_at_close PASSED
test_live_cache_hit_rate.py::test_second_run_hits_cache_at_least_95_percent PASSED
   [captured stdout] first=142  second=4  hit_rate=97.2%
====== 2 passed in 38.71s ======
```

If the cache hit rate is <95%, do **not** loosen the assertion. Investigate:
- Is the second run hitting a new bar boundary that wasn't cached?
- Is `fmp_cached` invalidating too aggressively on intraday?
- File a bug against `openbb-fmp-cached` before shipping.

- [ ] **6. Commit**

```bash
git add openbb_platform/extensions/fmp_trading/tests/integration/ \
        openbb_platform/extensions/fmp_trading/pyproject.toml

git commit -m "$(cat <<'EOF'
test(fmp_trading): live integration suite for AC-1 + AC-3 (P6.4)

Adds two @pytest.mark.live tests against real fmp_cached + MySQL:

- test_live_fmp_cached_session.py — AC-1: 10-min live slice runs, exits
  cleanly, flat_at_close=True.
- test_live_cache_hit_rate.py — AC-3: second replay uses <5% of the FMP
  calls that the first replay made (≥95% cache hit rate).

Both are marked 'live' and excluded from the default pytest run via
addopts = "-m 'not live'". Devs opt in with -m live.

Refs: PRD §12 AC-1, AC-3.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Verification

- Default `pytest openbb_platform/extensions/fmp_trading/tests/` → live tests deselected, all other tests pass.
- `pytest ... -m live` → both live tests pass locally with `fmp_cached_api_key` + MySQL configured.
- If either prerequisite is missing, tests **skip** with a clear reason (never fail with a stack trace).
- No live tests run in the standard CI job (verify by checking the GitHub Actions log after the PR opens).

---

## Task P6.5: `pyproject.toml` Final Polish + Changelog + README Badges

**Files:**
- Modify: `openbb_platform/extensions/fmp_trading/pyproject.toml`
- Create: `openbb_platform/extensions/fmp_trading/CHANGELOG.md`
- Modify: `openbb_platform/extensions/fmp_trading/README.md`

**Consumes:**
- Phase 0-6 accumulated deps + optional extras
- Extension entry-point convention (`openbb_platform_extension` group)
- Prior extension pyproject.toml files in `openbb_platform/extensions/` for style reference

**Produces:**
- A shippable `pyproject.toml` with clean `[agent]`, `[xlsxwriter]`, `[validation]` extras and correct entry-point
- A first-cut `CHANGELOG.md` covering v1.0.0 (Phases 0-6)
- README badges for version, Python compat, license, and cache-hit-rate

### Steps

- [ ] **1. Update `pyproject.toml` — entry point, extras, version**

Modify `openbb_platform/extensions/fmp_trading/pyproject.toml`:

```toml
[tool.poetry]
name = "openbb-fmp-trading"
version = "1.0.0"
description = "OpenBB extension: FMP-backed intraday day-trading automation with session replay, confluence signals, alerts, and optional MCP + backtest validation."
authors = ["OpenBB Team <hello@openbb.co>"]
license = "AGPL-3.0-only"
readme = "README.md"
packages = [{ include = "openbb_fmp_trading" }]

[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-core = "^1.4"
openbb-fmp-cached = "^0.2"
pandas = "^2.1"
pydantic = "^2.6"
mysql-connector-python = "^9.0"
python-dotenv = "^1.0"

# --- Optional extras ------------------------------------------------------
openbb-backtest = { version = "^0.3", optional = true }   # [validation]
xlsxwriter      = { version = "^3.2", optional = true }   # [xlsxwriter]
mcp             = { version = "^1.0", optional = true }   # [agent]

[tool.poetry.extras]
validation = ["openbb-backtest"]
xlsxwriter = ["xlsxwriter"]
agent      = ["mcp"]

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.23"
responses = "^0.25"

# --- OpenBB extension entry point ----------------------------------------
[tool.poetry.plugins."openbb_platform_extension"]
fmp_trading = "openbb_fmp_trading.fmp_trading_router:router"

[tool.pytest.ini_options]
markers = [
    "integration: requires external API access + credentials",
    "live: requires live FMP calls + running MySQL (opt-in only)",
]
addopts = "-m 'not live'"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **2. Create the CHANGELOG covering v1.0.0**

Create `openbb_platform/extensions/fmp_trading/CHANGELOG.md`:

```markdown
# Changelog

All notable changes to `openbb-fmp-trading` are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-07-XX

### Added

- **Phase 0** — extension scaffold, `obb.fmp_trading` namespace, `fmp_cached`
  provider constant, bootstrap smoke test.
- **Phase 1** — universe expansion via `market_movers_*`; deterministic
  session-symbol picker.
- **Phase 2** — intraday endpoints (5-min bars via fmp_cached); replay
  clock abstraction.
- **Phase 3** — `SessionEngine` + `SessionConfig` + MySQL-backed replay;
  `BrokerInterface` abstraction with a paper adapter.
- **Phase 4** — confluence signal engine + presets (`intraday_confluence`);
  threshold-based `AlertManager` + `AlertRules`.
- **Phase 5** — `[agent]` extra: MCP tool exposure via
  `openbb_fmp_trading.mcp.server`. `[xlsxwriter]` extra: session-report
  Excel export. Deterministic Narrator briefing. Core-unchanged-when-removed
  contract test.
- **Phase 6** — `[validation]` extra: `obb.fmp_trading.validate(preset,
  start_date, end_date)` bridges to `openbb-backtest`'s WFO/CPCV harness.
  Live integration suite for AC-1 (end-to-end session) and AC-3 (≥95%
  cache hit rate on replay).

### Provider

- Single provider: `fmp_cached` (never raw `fmp`, never `yfinance`).

### Known limitations

- AlertManager delivers to stdout + JSON log only; webhook/push/email
  channels are tracked as a v2 follow-up.
- Alert rules are threshold-based; pattern detectors (breakout, wedge,
  chart-formation) are a v2 research item.
- `market_movers_*` still hit legacy `/api/v3/*` FMP URLs; migration to
  `/stable/*` is a v2 tech-debt item.
```

- [ ] **3. Add README badges + Extras section**

Modify `openbb_platform/extensions/fmp_trading/README.md` — prepend a badge row at the very top and add an "Optional extras" section.

Top of file:

```markdown
# openbb-fmp-trading

[![PyPI version](https://img.shields.io/pypi/v/openbb-fmp-trading.svg)](https://pypi.org/project/openbb-fmp-trading/)
[![Python](https://img.shields.io/pypi/pyversions/openbb-fmp-trading.svg)](https://pypi.org/project/openbb-fmp-trading/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Cache hit rate](https://img.shields.io/badge/cache_hit_rate-%E2%89%A595%25-brightgreen)](docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md)
```

Then append (or edit) an "Optional extras" section:

```markdown
## Optional extras

The core extension installs with the base `pip install openbb-fmp-trading`.
Additional capabilities are behind Poetry extras — install any combination:

| Extra          | What you get                                                | Extra dep         |
|----------------|-------------------------------------------------------------|-------------------|
| `[agent]`      | MCP tool exposure — `obb.fmp_trading` as an MCP toolset     | `mcp`             |
| `[xlsxwriter]` | Excel export of `SessionResult` reports                     | `xlsxwriter`      |
| `[validation]` | `obb.fmp_trading.validate(...)` — WFO/CPCV backtest harness | `openbb-backtest` |

Example — install all extras:

```bash
pip install 'openbb-fmp-trading[agent,xlsxwriter,validation]'
```

Every extra is **optional**. The extension core imports cleanly and every
non-extra command remains functional if none of the extras are installed.
This is enforced by the `test_core_unchanged_when_removed` contract test.
```

- [ ] **4. Rebuild and verify the entry point wires up**

```bash
.venv_win\Scripts\pip.exe install -e openbb_platform/extensions/fmp_trading
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -c "from openbb import obb; print(hasattr(obb, 'fmp_trading'))"
```

Expected output:
```
True
```

- [ ] **5. Run the full unit-test suite one more time (belt-and-braces)**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading -m "not live" -v
```

Expected: all unit + non-live integration tests pass. Zero warnings about the `live` marker being unregistered.

- [ ] **6. Commit**

```bash
git add openbb_platform/extensions/fmp_trading/pyproject.toml \
        openbb_platform/extensions/fmp_trading/CHANGELOG.md \
        openbb_platform/extensions/fmp_trading/README.md

git commit -m "$(cat <<'EOF'
chore(fmp_trading): v1.0.0 release polish (P6.5)

- Bump version to 1.0.0.
- Finalize Poetry extras: [agent], [xlsxwriter], [validation].
- Register openbb-fmp-trading as an openbb_platform_extension entry point.
- Add CHANGELOG.md covering Phases 0-6.
- README: PyPI/Python/license/cache-hit-rate badges + Optional Extras table.

Refs: PRD §10 P6.5.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Verification

- `pip install openbb-fmp-trading` from a clean venv → `from openbb import obb; obb.fmp_trading` works; `obb.fmp_trading.validate` is **absent** (extra not installed).
- `pip install 'openbb-fmp-trading[validation]'` → `obb.fmp_trading.validate` is present.
- `pip install 'openbb-fmp-trading[agent,xlsxwriter,validation]'` → all extras work; the extension advertises 3 extra command surfaces.
- README badges render on GitHub (no broken images).
- CHANGELOG date placeholder is replaced with the actual release date at the time of `gh release create v1.0.0`.

---

## Epic-Closing Rollup: The Order of Operations

Because Task P6.2 references the Phase 6 PR number (`$PR_P6`) in the closure comments, this is the order to execute Phase 6 in:

1. **P6.1** (backtest bridge) — code + tests + commit.
2. **P6.4** (live integration suite) — code + commit.
3. **P6.5** (pyproject polish) — commit.
4. **Open the Phase 6 PR** — capture the PR number as `$PR_P6`.
5. **P6.2** (close 4 epics) — comments cite `$PR_P6`.
6. **P6.3** (file 3 follow-ups) — can be done any time; do it before the PR merges so reviewers see the follow-ups linked from the PR description.
7. **Merge the Phase 6 PR.**
8. **Tag and release:** `gh release create v1.0.0 --generate-notes --title "openbb-fmp-trading 1.0.0"`.

### Final commands to open the Phase 6 PR

```bash
git push -u origin phase6-validation-launch

gh pr create \
  --title "Phase 6: validation bridge, live integration suite, v1.0.0 launch" \
  --body "$(cat <<'EOF'
## Summary

Phase 6 of the openbb-fmp-trading rollout, closing PRD §10 P6.1-P6.5.

- **P6.1** Optional `[validation]` extra — thin bridge to `openbb-backtest`
  (#82) exposing `obb.fmp_trading.validate(preset, start_date, end_date)`.
  Extension core still imports cleanly when the extra is absent.
- **P6.2** Epic closures: #87, #84, #85, #231 will be closed on merge with
  linkback comments citing this PR + the PRD.
- **P6.3** Post-v1 follow-ups filed: AlertManager v2, FMP /stable migration,
  pattern-based alerts v2.
- **P6.4** Live integration suite for AC-1 (end-to-end session) and AC-3
  (≥95% cache hit rate on replay), gated by @pytest.mark.live.
- **P6.5** pyproject.toml polished for v1.0.0: entry point, [agent] /
  [xlsxwriter] / [validation] extras, CHANGELOG.md, README badges.

Design: `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`

## Test plan

- [x] Unit tests pass: `pytest openbb_platform/extensions/fmp_trading -m "not live"`
- [x] Codegen guard: `grep -R "OBBject\[" openbb_platform/extensions/fmp_trading/openbb_fmp_trading/` → zero hits
- [x] Live tests pass locally with fmp_cached_api_key + MySQL: `pytest ... -m live`
- [x] `pip install openbb-fmp-trading` (no extras) → obb.fmp_trading imports; validate is absent
- [x] `pip install 'openbb-fmp-trading[validation]'` → obb.fmp_trading.validate works
- [x] Core-unchanged-when-removed contract test still green

## Follow-ups (already filed)

- AlertManager v2 delivery channels (webhook / push / email)
- FMP `/api/v3/*` → `/stable/*` migration
- Pattern-based alerts v2 (research)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture the printed PR URL — it contains the number needed for Task P6.2's closure comments.

---

## Global Verification Checklist (run before requesting review)

- [ ] `pytest openbb_platform/extensions/fmp_trading -v` — all default-collected tests pass.
- [ ] `pytest openbb_platform/extensions/fmp_trading -m live -v` — passes locally with credentials + MySQL.
- [ ] `grep -R "OBBject\[" openbb_platform/extensions/fmp_trading/openbb_fmp_trading/` — **zero hits** (codegen constraint).
- [ ] `grep -R '"fmp"' openbb_platform/extensions/fmp_trading/openbb_fmp_trading/` — no raw `fmp` provider strings; every provider default is `"fmp_cached"`.
- [ ] `pip install -e '.[validation]'` succeeds; `pip install -e '.'` (no extras) also succeeds.
- [ ] `python -c "import openbb; openbb.build(); from openbb import obb; print(obb.fmp_trading._commands_map.keys())"` — lists all commands including `validate` when `[validation]` is installed.
- [ ] `python -c "..."` (same as above) with `[validation]` uninstalled — lists the same set **minus** `validate`, and no ImportError is raised.
- [ ] The four target epics (#87, #84, #85, #231) show state `CLOSED` with today's date.
- [ ] The three post-v1 follow-up issues show state `OPEN` with the `post-v1` label.
- [ ] `CHANGELOG.md` covers Phases 0-6 and lists known limitations.
- [ ] README renders on GitHub with all four badges visible.

## What "done" looks like

- Phase 6 PR merged; `v1.0.0` tag pushed; GitHub release published with auto-generated notes.
- `pip install openbb-fmp-trading==1.0.0` from PyPI works for a fresh user in a clean venv.
- The 4 target epics are closed with linkback comments; the 3 follow-ups are filed for v2 planning.
- The design spec at `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md` is unchanged (immutable historical record); the CHANGELOG and README are the living docs going forward.
- The Phase 5 core-unchanged-when-removed contract test is still green — proving that no Phase 6 addition (including `[validation]`) leaked into openbb-core.
