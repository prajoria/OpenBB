# techtrade pipeline — cross-plan API contract (#73–#86)

> **Status:** locked reference for the plan set. This is **not** an implementation plan; it
> is the single source of truth for module paths, function signatures, type names, and the
> per-issue commit boundary that every individual plan (`2026-06-13-techtrade-*-NN.md`)
> must match. If a plan and this contract disagree, the contract wins — fix the plan.

**Why this exists:** the 14 remaining issues form one dependency chain (indicators → confluence
→ signals → rules → orders → fills → {recommendation → excel ; validate} → tune/agent/docs).
Each is built by a fresh subagent. Without a locked contract, Task 3 calls `clearLayers()` and
Task 7 calls `clearFullLayers()`. Lock the names once, here.

---

## 1. House rules (apply to every plan)

- **Sub-skill:** every plan header carries `REQUIRED SUB-SKILL: superpowers:subagent-driven-development`, checkbox steps, TDD throughout (write failing test → run red → implement → run green → ruff → commit).
- **Codegen invariant (non-negotiable):** every `@router.command` function annotates `-> OBBject:` (bare). **Never** `OBBject[Model]` — the static package builder raises `NameError` on a parametrized return. The conceptual `list[X]` / `X` payload goes in the docstring `Returns` block only. (Confirmed in `techtrade_router.about`, `screener_router.segments/movers`.)
- **DI-seam:** every live `obb.*` data call sits behind an injectable function parameter that defaults to a lazy-import body (`from openbb import obb` inside the default fetcher). Unit tests inject offline fakes; the default path is integration-only. Mirror `engine/movers.py` (`candidate_fetcher`) and `engine/indicators.py` (`ohlcv_fetcher`).
- **Provider:** `fmp_cached` only. No `fmp`, no yfinance, no fallback.
- **Decimal discipline:** money/quantity (prices, qty, volume, commission, slippage) = `Decimal`; scores/ratios/percentages/indicator values/votes/weights = `float`; dates = `date`; fill timestamps = `datetime`.
- **Determinism:** fixed periods/weights, `talib=False`, seeded synthetic frames, look-ahead-free (`resolve_session` snaps `as_of` back to the last session). Golden fixtures lock outputs.
- **Lazy imports:** `pandas`, `pandas_ta_classic`, `openbb`, `openpyxl`, `tuneta`, `openbb_backtest` are imported **inside** function bodies, never at module top level, so `import openbb` stays light and optional deps stay optional.
- **Ruff:** root `ruff.toml`, line-length 122, `fix = true`. The enforced local gate. Run `…\.venv_win\Scripts\python.exe -m ruff check <files>` on every changed file. (black + mypy are CI-only locally.)
- **Env:** `…\.venv_win\Scripts\python.exe` (bash: `/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe`). `cd` to repo root first. Never system Python.
- **Test marks:** unit = default (offline, hermetic); golden = `pytestmark = pytest.mark.golden` + `_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"` + `assert_matches_golden` (#71 harness, `DEFAULT_TOL = 1e-9`, regen via `TECHTRADE_REGEN_GOLDEN=1`); integration = `pytestmark = pytest.mark.integration` + try/except → `pytest.skip`.
- **Noise files — always leave UNSTAGED** when committing: `openbb_platform/core/openbb/assets/reference.json`, `openbb_platform/core/openbb/package/__init__.py`, `openbb_platform/extensions/agents/tests/test_config.py`.
- **Commit boundary:** one issue = one commit. Stage only that issue's new/changed files. Co-author trailer `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`.

---

## 2. Existing surface (already merged — build ON this, do not modify for behavior)

| Path | What it gives downstream |
|---|---|
| `engine/screener.py` | `GICS_SECTOR_ETFS` (11 sectors, canonical order), `list_segments(...)→list[SegmentConfig]` |
| `engine/universe.py` | `resolve_universe(config, ...)→list[str]` (DI seams: `holdings_fetcher`, `screener_fetcher`, `constituents`) |
| `engine/movers.py` | `resolve_session(as_of, calendar)→date`, `rank_movers(...)`, `compute_ohlcv_metrics(...)`, `build_mover_list(config, ...)→MoverList`, `list_movers(segment, ...)→list[MoverList]` |
| `engine/indicators.py` | `IndicatorConfig`/`DEFAULT_CONFIG`, `ohlcv_to_frame(rows)→DataFrame`, `build_indicator_panel(symbol, as_of, rows, *, config)→IndicatorPanel`, `_default_ohlcv_fetcher(...)`, `build_panel_for_symbol(symbol, *, as_of, calendar, ohlcv_fetcher, lookback, config)→IndicatorPanel` |
| `models.py` | every Data model below (DO NOT change field names/types) |
| `testing.py` | `to_jsonable`, `assert_matches_golden(name, payload, *, fixture_dir, tol=DEFAULT_TOL)` |
| `techtrade_router.py` | `_include_subrouters()` already tries to import `engine.signals_router`, `engine.plan_router`, `reporting.export_router`, `validation.validate_router` (ImportError-skipped until built) |

**`models.py` field contract (frozen):**
- `IndicatorPanel(symbol, as_of, trend: dict[str,float], momentum, volatility, volume, candles: dict[str,int])`
- `IndicatorVote(family: Literal["trend","momentum","volatility","volume"], name: str, vote: float, weight: float)`
- `MoverSignal(symbol, segment, as_of, score: float, direction: Literal["long","short","flat"], votes: list[IndicatorVote], rank_in_segment: int)`
- `EntryExitRule(entry_threshold=0.4, exit_on_opposite=True, atr_stop_mult=2.0, target_r_multiple=2.0, max_holding_bars: int|None=20)`
- `Order(symbol, side: Literal["buy","sell","sell_short","buy_to_cover"], quantity: Decimal, order_type: Literal["market","limit","stop"]="market", limit_price: Decimal|None, stop_price: Decimal|None, tif: Literal["day","gtc"]="day", intent: Literal["entry","exit_stop","exit_target","exit_time","exit_signal"])`
- `Fill(order_ref: str, timestamp: datetime, symbol, side: str, quantity: Decimal, price: Decimal, commission: Decimal, slippage: Decimal)`
- `Recommendation(symbol, segment, as_of, action: Literal["BUY","SELL_SHORT","HOLD/FLAT"], conviction: Literal["High","Medium","Low"], score, entry_price: Decimal, stop_price: Decimal, target_price: Decimal, stop_distance_pct: float, target_distance_pct: float, risk_reward: float, atr: float, position_size: Decimal, risk_per_share: Decimal, risk_pct_of_notional: float, time_stop_bars: int|None, reasoning: str, top_factors: list[str], caveats: str)`
- `TradePlan(symbol, segment, as_of, signal: MoverSignal, rule: EntryExitRule, position_size: Decimal, orders: list[Order], simulated_fills: list[Fill], recommendation: Recommendation, validation: Data|None=None)`
- `ExportConfig(path: str|None, engine: Literal["openpyxl","xlsxwriter"]="openpyxl", include_sheets: list[str]=[Recommendations,Levels,Reasoning,Orders,Fills,Summary], conditional_formatting=True)`

---

## 3. New modules + canonical signatures (the lock)

Each issue adds the rows tagged with its number. **Names below are authoritative** — plans must use them verbatim.

### #73 — `engine/selector.py` + `engine/indicators_technical.py`
```python
# indicators_technical.py — OpenBB-technical adapter (graceful fallback to #72 classic path)
def technical_panel(symbol, as_of, ohlcv_rows, *, config=DEFAULT_CONFIG) -> IndicatorPanel: ...
def _obb_technical_available() -> bool: ...   # True iff openbb_technical importable

# selector.py — reuse-first source decision (one source per indicator, no duplication)
INDICATOR_SOURCE: dict[str, str]              # indicator_key -> "technical" | "classic"
def build_panel(symbol, as_of, ohlcv_rows, *, config=DEFAULT_CONFIG,
                source="auto") -> IndicatorPanel: ...   # auto = technical-where-covered else classic
def build_panels_bulk(frames: dict[str, list], as_of, *, config=DEFAULT_CONFIG) -> dict[str, IndicatorPanel]: ...
#   bulk path binds ONE accessor `acc = df.ta`, sets `acc.cores = 0`, runs a custom ta.Strategy list
```
Parity oracle test: `tests/unit/test_selector_parity.py`, `importorskip("openbb_technical")` (skips locally, runs in CI), compares classic-vs-technical per shared indicator within tolerance.

### #74 — `engine/confluence.py`
```python
@dataclass(frozen=True)
class ConfluenceWeights:
    trend: float = 0.40; momentum: float = 0.25; volatility: float = 0.20; volume: float = 0.15
DEFAULT_WEIGHTS = ConfluenceWeights()

def trend_votes(panel, *, adx_gate=20.0) -> list[IndicatorVote]: ...
def momentum_votes(panel) -> list[IndicatorVote]: ...
def volatility_votes(panel, *, regime=...) -> list[IndicatorVote]: ...
def volume_confirmation(panel) -> float: ...        # multiplier in ~[0,1+]; NOT an additive vote
def composite_score(panel, *, weights=DEFAULT_WEIGHTS) -> tuple[float, list[IndicatorVote]]: ...
#   raw = Σ_family(w · mean(vote_i)); score = clip(raw · volume_confirmation, -1, +1)
def direction_for(score, *, entry_threshold=0.4) -> Literal["long","short","flat"]: ...
def conviction_for(score) -> Literal["High","Medium","Low"]: ...   # |s|>=0.7 High, >=0.4 Medium, else Low
def build_signal(panel, segment, *, weights=DEFAULT_WEIGHTS, entry_threshold=0.4,
                 rank_in_segment=0) -> MoverSignal: ...
```
Golden: `tests/golden/test_confluence_golden.py` locks score + full `votes` breakdown.

### #75 — `strategies/presets.py` + `engine/signals_router.py`
```python
# presets.py
PRESETS: dict[str, ConfluenceWeights]      # "trend_follow" (default), "mean_revert", "breakout"
def resolve_preset(preset="trend_follow", weights: dict|None=None) -> ConfluenceWeights: ...
# engine/signals.py (pure core behind the router)
def build_signals(symbols=None, segment=None, *, preset="trend_follow", weights=None,
                  as_of=None, panel_fetcher=None) -> list[MoverSignal]: ...   # ranks → rank_in_segment
# engine/signals_router.py
@router.command(methods=["GET"])
def signals(segment=None, symbols=None, preset="trend_follow", as_of=None) -> OBBject: ...
```

### #76 — `engine/rules.py`
```python
def stop_price(entry: Decimal, atr: float, direction, rule: EntryExitRule) -> Decimal: ...
def target_price(entry: Decimal, stop: Decimal, direction, rule: EntryExitRule) -> Decimal: ...
def position_size(entry: Decimal, stop: Decimal, *, account_size: Decimal,
                  risk_per_trade: float) -> Decimal: ...    # floor(risk_budget / |entry-stop|) Decimal
def apply_rule(signal: MoverSignal, *, entry: Decimal, atr: float, rule=EntryExitRule(),
               account_size=Decimal("100000"), risk_per_trade=0.01) -> dict: ...
#   returns {"entry","stop","target","qty","risk_per_share"} all Decimal where money
```
Q6 sizing inputs: `account_size: Decimal` + `risk_per_trade: float` (abstract notional; no personal dollars).

### #77 — `engine/orders.py` + `engine/plan_router.py`
```python
# orders.py
def generate_orders(signal, *, entry, stop, target, qty, rule) -> list[Order]: ...
#   entry leg (intent="entry") first, then exit_stop / exit_target / exit_time legs with correct side
def build_trade_plan(signal, *, entry, atr, rule=EntryExitRule(), account_size, risk_per_trade,
                     recommendation=None) -> TradePlan: ...
# engine/plan.py (pure) + engine/plan_router.py
def build_plans(symbols=None, segment=None, *, preset="trend_follow", risk=0.01,
                as_of=None, ...fetchers...) -> list[TradePlan]: ...
@router.command(methods=["GET"])
def plan(segment=None, symbols=None, preset="trend_follow", risk=0.01, as_of=None) -> OBBject: ...
@router.command(methods=["GET"])
def orders(plan: TradePlan) -> OBBject: ...     # materializes plan.orders
```
NOTE `engine/plan_router.py` hosts `plan`, `orders`, **and `scan` (#79)**; `simulate` (#78) also lands here or in a dedicated `simulate` command on the same router — see #78/#79 plans.

**Cross-plan resolution — `TradePlan.recommendation` is required but #80 ships after #77.** Because issues are implemented in number order and each is a standalone commit, #77 cannot import #80. Resolution: #77's `build_trade_plan` assembles a **self-contained `Recommendation` inline** from the data it already holds (entry/stop/target/qty/atr/score/direction → action via direction, conviction via a tiny local `|score|` bucketing, levels, sizing, and a **basic deterministic one-line `reasoning`** with `top_factors=[]`, `caveats=""`). #80 then introduces the canonical `engine/execution.py` (`build_recommendation` + `render_reasoning`, full templated narrative) **and refactors `build_trade_plan` to delegate to it** (DRY) — that refactor + the richer golden are part of #80's commit. The #77 plan must therefore include a small inline recommendation helper, and the #80 plan must include the refactor-#77-to-delegate step. Both must keep `Recommendation` field names exactly as frozen in §2.

### #78 — `execution/broker.py` (new `execution/` package)
```python
class BrokerInterface(Protocol):
    def submit(self, order: Order, bar) -> Fill | None: ...
    def cancel(self, order_ref: str) -> None: ...
    def positions(self) -> list: ...
@dataclass
class PaperBroker:   # implements BrokerInterface
    commission_per_share: Decimal = Decimal("0"); slippage_bps: Decimal = Decimal("5")
    def submit(self, order, bar) -> Fill | None: ...     # next-bar-open ± slippage; intrabar stop/target vs high/low
def simulate(orders: list[Order], bars: list, *, broker=None) -> list[Fill]: ...   # no same-bar peek
@router.command(methods=["GET"])
def simulate(...) -> OBBject: ...    # router command on plan_router
```
No-look-ahead golden: bar-t signal fills at t+1 only (`tests/golden/` + unit assert).

### #79 — `engine/scan.py` (+ `scan` command on `plan_router`)
```python
def scan_segments(metric="pct_change", top_n=10, *, preset="trend_follow", as_of=None,
                  ...fetchers...) -> list[TradePlan]: ...   # screener→signals→rules→orders→fills, cross-segment ranked
@router.command(methods=["GET"])
def scan(metric="pct_change", top_n=10, preset="trend_follow", as_of=None) -> OBBject: ...
```

### #80 — `engine/execution.py` (recommendation builder; distinct from `execution/` pkg of #78)
```python
def build_recommendation(plan_or_signal, *, entry, stop, target, atr, qty,
                         risk_per_share, account_size) -> Recommendation: ...
def render_reasoning(signal: MoverSignal) -> tuple[str, list[str], str]: ...  # (reasoning, top_factors, caveats)
#   deterministic template from signal.votes; references the highest-|weight·vote| factors
```
Buckets: action from direction (long→BUY, short→SELL_SHORT, flat→HOLD/FLAT); conviction via `conviction_for`.

### #81 — `reporting/excel_export.py` + `reporting/export_router.py`
```python
def export_workbook(plans: list[TradePlan], config: ExportConfig=ExportConfig()) -> str: ...
#   6 sheets (Recommendations, Levels, Reasoning, Orders, Fills, Summary); openpyxl; disclaimer on
#   Recommendations; default path Analysis/exports/techtrade_<as_of>.xlsx; byte-stable
@router.command(methods=["GET"])
def export(plans: list[TradePlan], path=None, engine="openpyxl") -> OBBject: ...   # results = path str
```
Golden `.xlsx` test asserts sheet set, disclaimer text, deterministic structure.

### #82 — `validation/backtest_bridge.py` + `validation/validate_router.py`
```python
def plan_to_backtest_config(plan: TradePlan, *, start, end, ...) -> "BacktestConfig": ...  # lazy import
def validate_plan(plan: TradePlan, *, method="wfo", thresholds=None,
                  validator=None) -> "ValidationReport": ...   # validator seam → obb.backtest.validate
def attach_validation(plan: TradePlan, report) -> TradePlan: ...   # sets plan.validation
@router.command(methods=["POST"])
def validate(plan: TradePlan, method="wfo") -> OBBject: ...
```
Graceful degradation: missing `openbb_backtest` → clear `OptionalDependencyError`-style message, core still imports.

### #83 — `tuning/tuneta_adapter.py` + `tuning/tune_router.py` (`[tuneta]` extra)
```python
def tune_segment(segment, *, validator=None, tuner=None, ...) -> "TuningReport": ...
#   only params passing #82 validation (robust verdict) persist; defaults ship un-tuned
@router.command(methods=["POST"])
def tune(segment, ...) -> OBBject: ...   # clear message when [tuneta] absent
```
New `tuning/` package. Add `tuneta` extra to `pyproject.toml [tool.poetry.extras]`.

### #84 — `agent/narrator.py` (`[agent]` extra)
```python
def narrate_plan(plan: TradePlan) -> str: ...          # reuses Recommendation.reasoning; never mutates
def narrate_segment(plans: list[TradePlan]) -> str: ...
```
New `agent/` package. Deterministic; NG4 — never alters plan/score/orders.

### #85 — `agent/mcp_tools.py` (`[agent]` extra)
```python
def register_tools(server) -> None: ...   # exposes segments/movers/signals/plan/scan/orders/simulate/export/validate
#   calls public obb.techtrade.* only; no private decision logic
```
"core-unchanged-when-removed" test: with `agent/` absent/uninstalled, all non-agent commands pass.

### #86 — `README.md` + `docs/`
Docs only: install (submodule + extras), command surface, worked `scan → plan → export` example, presets/weights/risk inputs, disclaimer, PRD backlink.

---

## 4. Router wiring map (what each command lands on)

| Command | Router module | Issue |
|---|---|---|
| `segments`, `movers` | `engine/screener_router.py` | done |
| `signals` | `engine/signals_router.py` | #75 |
| `plan`, `orders`, `simulate`, `scan` | `engine/plan_router.py` | #77/#78/#79 |
| `export` | `reporting/export_router.py` | #81 |
| `validate` | `validation/validate_router.py` | #82 |
| `tune` | `tuning/tune_router.py` (add to `_include_subrouters`) | #83 |
| MCP tools | `agent/mcp_tools.py` (not a Router) | #85 |

`_include_subrouters()` in `techtrade_router.py` already lists signals/plan/export/validate; **#83 must append `tuning/tune_router`** to that tuple.

---

## 5. Per-issue commit file manifest (stage exactly these)

- **#73** `engine/indicators_technical.py`, `engine/selector.py`, `tests/unit/test_selector.py`, `tests/unit/test_indicators_technical.py`, `tests/unit/test_selector_parity.py`, `tests/golden/test_selector_golden.py` (+fixture)
- **#74** `engine/confluence.py`, `tests/unit/test_confluence.py`, `tests/golden/test_confluence_golden.py` (+fixture)
- **#75** `strategies/presets.py`, `engine/signals.py`, `engine/signals_router.py`, `tests/unit/test_signals.py`, `tests/golden/test_signals_golden.py` (+fixture), `tests/integration/test_signals_integration.py`
- **#76** `engine/rules.py`, `tests/unit/test_rules.py`
- **#77** `engine/orders.py`, `engine/plan.py`, `engine/plan_router.py`, `tests/unit/test_orders.py`, `tests/unit/test_plan.py`
- **#78** `execution/__init__.py`, `execution/broker.py`, `tests/unit/test_broker.py`, `tests/golden/test_no_lookahead_golden.py` (+fixture), command added to `engine/plan_router.py`
- **#79** `engine/scan.py`, `scan` command on `engine/plan_router.py`, `tests/unit/test_scan.py`, `tests/integration/test_scan_integration.py`
- **#80** `engine/execution.py`, `tests/unit/test_execution.py`, `tests/golden/test_recommendation_golden.py` (+fixture)
- **#81** `reporting/excel_export.py`, `reporting/export_router.py`, `tests/unit/test_excel_export.py`, `tests/golden/test_excel_golden.py` (+fixture .xlsx)
- **#82** `validation/backtest_bridge.py`, `validation/validate_router.py`, `tests/unit/test_backtest_bridge.py`, `tests/integration/test_validate_integration.py`
- **#83** `tuning/__init__.py`, `tuning/tuneta_adapter.py`, `tuning/tune_router.py`, `pyproject.toml` (extra), `_include_subrouters` edit, `tests/unit/test_tuneta_adapter.py`
- **#84** `agent/__init__.py`, `agent/narrator.py`, `pyproject.toml` (agent extra), `tests/unit/test_narrator.py`
- **#85** `agent/mcp_tools.py`, `tests/unit/test_mcp_tools.py`, `tests/unit/test_core_without_agent.py`
- **#86** `README.md`, any `docs/` pages
- **always unstaged:** `reference.json`, `package/__init__.py`, `agents/tests/test_config.py`

---

## 6. Dependency / sequencing (epic critical path)

`#73 → #74 → #75 → #76 → #77 → #78 → { #80 → #81 ; #82 }` then `#83`(needs #82), `#84`(needs #81), `#85`(needs #84), `#86`(needs #81). `#79` needs #78. Implement in issue-number order; each is its own commit through the full dev-cycle.
