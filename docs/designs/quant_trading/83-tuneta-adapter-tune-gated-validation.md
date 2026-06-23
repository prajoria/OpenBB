# 83 — tuneta adapter + tune command, gated by validation

**GitHub:** [#83](https://github.com/prajoria/OpenBB/issues/83) · **Phase:** P7 · **Sprint:** 6 · **Size:** M
**Depends on:** [#82](https://github.com/prajoria/OpenBB/issues/82) (`obb.techtrade.validate` — supplies the `ValidationReport` the gate reads, **RESOLVED 2026-06-21**)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §12.4 (Optional tuning), §15 (validation gate), §18 P7 (phased delivery), §19 (TA over-tuning risk), §22 (license posture for `tuneta`)

**Scope:** Add a `tuning/` package behind a new `[tuneta]` optional extra, exposing
`obb.techtrade.tune(segment, ...) → OBBject[TuningReport]`. Per-segment pipeline:
pool the sector's OHLCV → fit `tuneta` over 8 indicator-period knobs → parse the
tuned column names back into an `IndicatorConfig` → build a sample `TradePlan` for
the segment's benchmark ETF → call **#82's** `validate(...)` over WFO folds →
**only if `verdict == "robust"`** persist the tuned config to
`~/.openbb_platform/techtrade_tuned.json`. Make the panel builder consult that file
by `symbol → segment` so tuned configs take effect on `scan` / `plan` / `signals`
transparently. Degrade gracefully when `tuneta` is absent.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout.
> techtrade implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> `openbb-backtest` is **merged in-tree** at
> [`../../../openbb_platform/extensions/backtest/`](../../../openbb_platform/extensions/backtest/);
> #82 closed on 2026-06-21, so `validate_plan` is a directly-importable in-tree symbol
> here, never a sibling-checkout reference. `tuneta` is a **third-party MIT** library
> (`jmrichardson/tuneta` on GitHub), pulled via the optional `[tuneta]` extra and
> imported lazily in-body (mirroring #82's `openbb-backtest` discipline).

---

## What this is

**Tuning** answers a narrow, dangerous question: *what indicator periods actually
worked for this sector?* The PRD's defaults (RSI(14), MACD(12,26,9), Bollinger(20, 2),
ATR(14), etc.) are honest and conservative — they ship un-tuned on purpose. But a
sector's price behaviour is regime-specific: tech's volatility profile differs from
utilities, and a one-size-fits-all RSI period leaves edge on the table. `tune`
delegates the per-sector parameter search to **`tuneta`** (`jmrichardson/tuneta`,
MIT) — a distance-correlation + Optuna optimiser that ranks `(indicator, period)`
combinations by how well they predict forward returns, then prunes correlated
candidates. The **output** is a candidate `IndicatorConfig` for the segment.

The defining constraint — and the deliberate contrast with naive
parameter-sweeping — is that the candidate is *not* trusted on the strength of its
in-sample fit. PRD §19 names "TA over-tuning" as the engine's #1 modelling risk:
tuned periods can look spectacular in the data they were fit on and collapse out
of sample. So the candidate goes through **#82's** `validate(...)` over WFO folds,
which returns a `verdict ∈ {robust, fragile, overfit}` derived from
**Probability of Backtest Overfitting** (PBO), **Deflated Sharpe Ratio** (DSR),
and the aggregated OOS Sharpe. **Only `robust` persists.** Fragile and overfit
candidates are returned in the `TuningReport` so the user can see what was
proposed and why it was rejected — but the panel builder never sees them.

Persistence is per-user (`~/.openbb_platform/techtrade_tuned.json`, mirroring how
`user_settings.json` already lives there); when present, the panel builder's
default config-lookup path consults that file by `symbol → segment` so tuned
configs **take effect transparently** on every subsequent `obb.techtrade.scan`,
`plan`, or `signals` call — no caller change required.

Like #82, `tuneta` is a **soft/optional** dependency: declared as a `[tuneta]`
extra in `pyproject.toml`, imported lazily in-body in
`tuning/tuneta_adapter.py`, and degrading to a clear
`TechtradeDependencyError` (with a copy-pasteable `pip install` hint) when absent.
Every *other* part of `obb.techtrade.*` keeps importing and running with `tuneta`
not installed — the same #85 core-unchanged-when-removed discipline #82 already
ships under.

---

## 0. Key decisions (locked) + Open questions

### Locked (do not re-open)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| **L1** | Tune scope | **Indicator periods only** — fields on `IndicatorConfig`, not `ConfluenceWeights` | `TuningReport` carries an `IndicatorConfig`. Confluence weights stay at locked Q4 defaults (`trend 0.40 / momentum 0.25 / volatility 0.20 / volume 0.15`); the 0.85-additive-sum invariant from #74/#75 is **untouched**. `tuneta` is the right tool for periods specifically. |
| **L2** | Verdict gate | **Strict: `verdict == "robust"` persists** | Stricter than PRD §15's "non-overfit" wording. `fragile` and `overfit` candidates are returned to the user in the `TuningReport` (for transparency / diagnosis) but **not** persisted. Conservative against PRD §19's TA-over-tuning risk. |
| **L3** | Persistence | **`~/.openbb_platform/techtrade_tuned.json`** | Per-user file. Schema: `{"schema_version": "1.0", "segments": {<name>: {"config": <IndicatorConfig-as-dict>, "meta": {"verdict": "robust", "pbo": ..., "dsr": ..., "tuned_at": "<iso8601>", "tuneta_version": "<x.y.z>"}}}}`. Never committed; `.gitignore`-equivalent already covers `~/.openbb_platform/` by virtue of being outside the repo. |
| **L4** | Per-segment tune target | **Pool the segment's universe** into one MultiIndex `(date, symbol)` OHLCV DataFrame | Single `tuneta.fit(X, y)` per segment, exercising tuneta's documented multi-symbol path. Statistical power across the sector vs. an ETF proxy. Forces a `pool_sector_ohlcv(segment, as_of, horizon_years)` helper with an offline-test fetcher seam (mirrors `engine/indicators.py:_default_ohlcv_fetcher`). |
| **L5** | Validate scope | **Per-segment: one `validate_plan(...)` call per `tune(segment, ...)`** | The tuned candidate `IndicatorConfig` builds a sample `TradePlan` for the segment's benchmark ETF (deterministic; see Q-A), then `openbb_techtrade.validation.backtest_bridge.validate_plan(plan, method="wfo")` returns the `ValidationReport`. Each segment proves itself; no aggregate gate. **Execution-model fact (verified 2026-06-21 against the #82 code):** `validate_plan` runs the WFO fold loop *sequentially in the caller's asyncio task* — no `ThreadPool`/`ProcessPool`/`run_in_executor`/`multiprocessing`/`joblib`/`concurrent.futures`/`ray`/`dask` usage anywhere in `openbb_backtest`. This locks §5.3's W2 contextvar approach as safe (asyncio context-copy propagates the override into the fold loop). |
| **L6** | Tuneta search space | **8 period knobs** with explicit ranges | `macd_fast (8,20)`, `macd_slow (20,40)`, `macd_signal (5,15)`, `adx_length (10,30)`, `ema_fast (10,30)`, `ema_slow (30,80)`, `rsi_length (8,30)`, `atr_length (10,30)`. The 7 non-period / coupled-bundle knobs (`stoch_k/d/smooth_k`, `bb_length/std`, `kc_length/scalar`) stay at PRD defaults — tuneta tunes one period per indicator, stoch needs 3 coherent knobs together, and `bb_std=2.0` / `kc_scalar=1.5` are shape multipliers, not periods. |
| **L7** | Command shape | **`tune(segment: str, ...) → OBBject[TuningReport]`** — single-segment per call | Matches the issue's literal `tune(segment, ...)` signature. Caller loops over the 11 GICS sectors if they want all of them; composable; no batch-resume logic in v1. |
| **L8** | Dependency posture | **Soft/optional, `[tuneta]` extra, reuses `TechtradeDependencyError`** | Mirrors #82's Q-A verbatim. `pyproject.toml` declares `tuneta = ["tuneta"]`; all `import tuneta` is lazy in-body in `tuning/tuneta_adapter.py`; absent → `TechtradeDependencyError(OpenBBError)` with hint `pip install 'openbb-techtrade[tuneta]'`. Every other techtrade command keeps importing and running (enforced by the #85 core-unchanged-when-removed test). |
| **L9** | Loader rule | **Auto-load: `build_indicator_panel(symbol, as_of, rows, *, config=None)` consults the tuned JSON by `symbol → segment` when `config is None`** | Panel builder grows an optional `config: IndicatorConfig \| None = None` arg; when `None` (default), it resolves the symbol's segment via the existing segment resolver, reads the mtime-cached tuned JSON, and uses the segment's tuned `IndicatorConfig` if present, else `DEFAULT_CONFIG`. Tuned configs ship transparent — no caller change for `scan` / `plan` / `signals`. |

> **Verdict thresholds (#82 / L5 single source of truth):** the gate that decides
> `robust` lives inside `openbb_backtest.validation.build_validation_report` with
> the precedence **overfit > robust > fragile** and the defaults `pbo_robust 0.2`
> · `pbo_overfit 0.5` · `dsr_robust 0.95` · `dsr_overfit 0.5`. #83 does **not**
> recompute the verdict — it reads `report.verdict` and checks `== "robust"`.

### Open questions (for review)

**Q-A — Sample-plan symbol for the per-segment validate (L5 input).**
The bridge from #82 validates a `TradePlan`, which carries a single `symbol`. Which symbol do we use to validate the *segment's* candidate config? Options:

| Option | Symbol | Tradeoff |
|---|---|---|
| **A1** | The segment's benchmark ETF (`SegmentConfig.benchmark_etf` — XLK for IT, XLF for Financials, etc.) | Deterministic; no dependency on the live mover ranking; ETF is the sector's canonical proxy (PRD Q3); reproducible across runs |
| **A2** | The top-1 mover from a fresh `obb.techtrade.movers(segment, as_of)` | Mirrors what `scan` actually does; but couples `tune`'s reproducibility to whatever symbol happens to be the top mover that day |
| **A3** | All symbols in the universe; gate on `verdict == "robust"` for ≥ K of N | Most thorough; multiplies wall-clock by N (~50 validates per segment); arguably YAGNI for v1 |

- **Recommendation:** **A1 — segment's benchmark ETF.** Deterministic (same input → same verdict), already in `SegmentConfig.benchmark_etf`, and PRD Q3 already nominated `etf_holdings` as the segment's canonical proxy — so validating against the ETF treats it as the sector's canonical representative.
> - **Answer (Review):** ✅ **Approved — A1 (benchmark ETF).**
>
>   1. **Determinism is the gate's whole point.** A persisted, auditable `meta` block (L3) only
>      means something if the same `(segment, as_of, horizon)` always produces the same verdict.
>      A2 couples that to the day's top-mover ranking, so the same history could persist a config
>      today and reject it tomorrow — it breaks the `tuneta_version` + `pbo`/`dsr` provenance trail
>      and makes `techtrade_tuned.json` non-reproducible. Reject A2.
>   2. **A3 is YAGNI for v1 and duplicates the gate.** "≥ K of N robust" is a *new* aggregation
>      policy layered on top of PBO/DSR, which already aggregate OOS performance internally; it
>      multiplies wall-clock ~50× per sector for a second opinion the verdict already encodes.
>      Revisit only if ETF-level verdicts prove unrepresentative in practice.
>   3. **Flag the one honest limitation (one line in the docs / `TuningReport`):** the verdict is
>      *sector-level* — a config robust on XLK is applied to individual IT constituents on
>      `scan`/`plan`, which may behave differently from the basket. That's acceptable (ETF is the
>      canonical proxy per PRD Q3), but the `TuningReport` should say so plainly so a user doesn't
>      read "robust" as a per-symbol guarantee.

**Q-B — What `y` (forward returns) does tuneta fit against?**
`tuneta.fit(X, y, …)` wants a target series. The choice anchors what the tuned periods are actually optimised *for*. Options:

| Option | Target | Tradeoff |
|---|---|---|
| **B1** | Next-day return | Simplest; matches most published TA-tuning literature; but tunes for one-day moves while the rule (`EntryExitRule.max_holding_bars=20`) is built for multi-week holds |
| **B2** | Next-5-day cumulative return | Compromise; smooths intraday noise; arbitrary horizon |
| **B3** | Next-`max_holding_bars`-cumulative return (default 20) | Aligns the optimisation target with the rule the tuned periods will actually feed; the periods get good at predicting the *kind* of move the rule is built to capture |

- **Recommendation:** **B3 — next-20-bar cumulative return** (configurable via `tune(..., forward_horizon_bars=20)`, default = `EntryExitRule.max_holding_bars`). Lines up the tuneta optimisation target with the rule that will consume the tuned periods.
> - **Answer (Review):** ✅ **Approved — B3 (next-`max_holding_bars` cumulative return).**
>
>   1. **Objective-to-rule alignment is the right principle.** Tuning periods against next-day
>      returns (B1) and then feeding a 20-bar-hold rule is an objective mismatch — the periods get
>      good at predicting moves the rule never trades. B2's 5-day is an arbitrary middle. B3 tunes
>      for the move the rule is actually built to capture. Correct.
>   2. **Must-do: read the default *from the rule*, not a literal `20`.** The doc says
>      "default = `EntryExitRule.max_holding_bars`" — make the code resolve it from
>      `EntryExitRule()` at call time, not hardcode `forward_horizon_bars=20`, so the two can't
>      silently desync if the rule default ever changes.
>   3. **Note the overlap caveat (one comment).** 20-bar cumulative returns on daily bars overlap
>      heavily, so `y` is autocorrelated and tuneta's in-sample distance-correlation scores will
>      look rosier than the true edge. This is *acceptable here* precisely because the gate (WFO
>      PBO/DSR, out-of-sample, non-overlapping folds) is downstream and catches the over-optimism —
>      worth a one-line comment in the adapter so a future reader doesn't "fix" the overlap and
>      accidentally weaken the alignment.

**Q-C — Tune-window length.**
How much history does the pooled OHLCV cover? Options: (a) match #82's `DEFAULT_HORIZON_YEARS = 5`; (b) longer (10y) for more tuning data; (c) shorter (2y) to favour recent regime.

- **Recommendation:** **5y — match #82.** Same window shapes the tune *and* the validation gate; no regime mismatch between "what we tuned on" and "what we validated on." Exposed as `tune(..., horizon_years=5)` for power users.
> - **Answer (Review):** ✅ **Approved — 5y, single source of truth.**
>
>   1. **The tune-window and the validate-window must be the *same* parameter, not two
>      independently-defaulted 5s.** That's the load-bearing point: if tune used 2y and the gate
>      used 5y, you'd fit on the recent regime and judge on a different distribution, systematically
>      inflating `fragile`/`overfit` verdicts for reasons that have nothing to do with the config.
>      Enforce in code that `horizon_years` flows from `tune(...)` into *both* `pool_sector_ohlcv`
>      and `validate_plan` — a power user who changes it changes both at once.
>   2. **5y over 10y/2y is the correct default.** 2y over-weights the current regime (more luck,
>      less power); 10y drags in structurally different regimes that the conservative defaults
>      already cover. 5y matches #82 and keeps the whole pipeline on one window.
>   3. **Minor: assert the pooled frame actually spans the requested window** (the
>      `sector_ohlcv` tests cover shape — add a span/coverage check) so a short-history sector
>      doesn't silently tune on 18 months while claiming 5y in `meta.horizon_years`.

**Q-D — Tuneta `trials` / `early_stop` budget.**
The README defaults are `trials=100, early_stop=20`. Per-segment wall-clock matters because the typical use loops over 11 sectors.

- **Recommendation:** **`trials=100, early_stop=20` verbatim** — well-trodden numbers from tuneta's own examples; exposed via `tune(..., trials=100, early_stop=20)` so power users can tighten or relax. A `verbose=False` default keeps the techtrade log surface clean (`tuneta` defaults to chatty).
> - **Answer (Review):** ✅ **Approved — `trials=100, early_stop=20`, `verbose=False`.**
>
>   1. **Sensible, well-trodden defaults exposed as params — agreed.** Nothing here needs to be
>      cleverer than tuneta's own examples for v1.
>   2. **Tie this answer to the §6 determinism commitment explicitly.** 100 trials are only
>      reproducible if Optuna's sampler is seeded — §6 already commits to pinning
>      `random_state=0` when the tuneta version supports it. Cross-reference it here so Q-D and §6
>      can't drift: "budget is 100/20, reproducibility comes from the §6 seed pin."
>   3. **Call out the parallelism/determinism interaction.** If the adapter ever passes
>      `n_jobs>1` to tuneta/Optuna, trial ordering becomes non-deterministic and the seed pin no
>      longer guarantees byte-stability. Default to single-job (or document that `n_jobs>1` trades
>      determinism for speed) so the "byte-stable across runs" claim in §6 holds by default.
>   4. **Document the wall-clock honestly.** Per-segment × 11 sectors × 100 trials can run into
>      many minutes; L7's single-segment-per-call shape is the right escape valve, but the README/
>      `tune` docstring should state the rough per-segment cost so a user looping all 11 isn't
>      surprised.

**Q-E — Tuned-file mtime cache invalidation.**
The panel builder reads the tuned JSON on every panel build (every signal, every plan, every scan symbol). Options:

| Option | Strategy | Tradeoff |
|---|---|---|
| **E1** | `lru_cache` keyed on `(path, mtime_ns)` | Micro-cheap re-check (`os.stat` is microsecond-level); cache invalidates the instant `tune` writes; correct under concurrent `tune` + `scan` |
| **E2** | Process-lifetime cache (read once at import) | Fastest; stale if `tune` runs in the same process — wrong for the interactive `obb.techtrade.tune(...); obb.techtrade.scan(...)` workflow |
| **E3** | Per-call read (no cache) | Always-fresh; ~110 stat+open+json per scan (one per symbol per sector × ~10 movers) — wasteful |

- **Recommendation:** **E1 — mtime-cached.** `(path, mtime_ns)` key invalidates exactly when the file changes; safe under interactive `tune → scan` workflows; trivially cheap on the hot path.
> - **Answer (Review):** ✅ **Approved — E1 (`lru_cache` on `(path, mtime_ns)`), with two guards.**
>
>   1. **E2 is disqualified by the headline workflow.** The whole point of #83 is the interactive
>      `obb.techtrade.tune(...); obb.techtrade.scan(...)` loop in one process — a process-lifetime
>      cache (E2) would make a freshly-tuned config invisible until restart. E3 is correct but
>      pays ~110 stat+open+json per scan for no benefit. E1 is the standard pattern. Agreed.
>   2. **Guard 1 — bound the cache.** `lru_cache` keyed on `mtime_ns` accumulates one entry per
>      historical write for the process lifetime; set an explicit `maxsize` (e.g. 8) so a long
>      interactive session that re-tunes many times doesn't leak parsed dicts.
>   3. **Guard 2 — coarse-mtime filesystems.** On filesystems with low mtime resolution, two
>      writes inside the same tick can share an `mtime_ns` and serve stale data. You already use
>      `st_mtime_ns`; add `st_size` (and/or an explicit cache-clear in `write_tuned`) as a cheap
>      tiebreaker. The `test_mtime_cache_invalidates_on_change` test should write twice in quick
>      succession to actually exercise this, not just write once.

**Q-F — What happens on `verdict in {fragile, overfit}`?**
The candidate doesn't persist (L2). What does the caller see?

- **Recommendation:** **Return the full `TuningReport` with `persisted=False`**, carrying the candidate `IndicatorConfig` (so the user can inspect what was proposed), the full `ValidationReport` (so they can see PBO / DSR / OOS Sharpe and decide whether to retry with a different `as_of` or threshold), and a `reason` string (e.g. `"verdict=fragile (pbo=0.31, dsr=0.62)"`). Nothing is written to disk. Logged at WARNING.
> - **Answer (Review):** ✅ **Approved — transparent non-persist (`persisted=False` + full report).**
>
>   1. **Transparency-without-persistence is exactly the §19 posture.** Returning the candidate
>      and the `ValidationReport` lets the user *see* what was proposed and *why* it was rejected
>      (PBO/DSR/OOS), while the gate keeps it out of the panel builder. This is the right shape.
>   2. **A rejected tune is a normal outcome, not an error — must not raise.** Log once at WARNING
>      and return; a user looping all 11 sectors must not have the loop aborted by an exception on
>      the first fragile sector. Make this explicit in the router contract and cover it with a test
>      (loop of mixed robust/fragile verdicts completes and returns all reports).
>   3. **Define the no-op-tune case too.** If tuneta proposes a config equal to `DEFAULT_CONFIG`
>      (or within rounding of it), prefer `persisted=False` with
>      `reason="no change from defaults"` rather than persisting a tuned entry identical to the
>      default — it keeps `techtrade_tuned.json` meaningful (only genuinely-different robust
>      configs land).
>   4. **Keep `reason` human-first but stable.** The `"verdict=fragile (pbo=0.31, dsr=0.62)"`
>      shape is good; just fix the field order/precision so two runs produce identical strings
>      (feeds the §6 byte-stability claim).

**Q-G — Import discipline (mirror of #82's Q-F).**
All `tuneta` imports must be lazy and in-body. Enforced by an extended #85 core-unchanged-when-removed test (the existing test already covers backtest absence; this adds the `tuneta` absent case to the same fixture).

- **Recommendation:** **Lazy, in-body, in `tuning/tuneta_adapter.py` only**, and extend the #85 test to cover `tuneta` absence alongside `openbb_backtest` absence. The `_require_tuneta()` helper mirrors `_require_backtest()` shape for shape.
> - **Answer (Review):** ✅ **Approved — lazy in-body in `tuneta_adapter.py` only, extend the #85 truth table.**
>
>   1. **Reuse the proven #82 pattern verbatim.** Single import site, lazy guard, reused
>      `TechtradeDependencyError`, sub-router registers but only *executing* `tune` triggers
>      `_require_tuneta()` — same as `validate` with `openbb-backtest`. The §6 matrix already
>      covers the full truth table (both absent / both present / each independently); that's the
>      complete enforcement. Agreed.
>   2. **Fix the two-extras error message.** When `tuneta` is present but `openbb-backtest` is
>      absent, `tune` fails with the *backtest's* dependency error (§1 already notes this). That's
>      the correct layer, but the message should name *which* extra is missing and ideally that a
>      full tune needs **both** (`[tuneta]` to fit, `[validation]` to gate) — otherwise a user who
>      installed only `[tuneta]` gets a backtest error that looks unrelated to the `tune` they ran.
>   3. **Add the explicit "import techtrade with neither extra" assertion.** The degradation test
>      should import the top-level `openbb_techtrade` package (and build a panel via the auto-load
>      path) with *both* absent, proving `tuned_defaults`/`indicators` stay importable on the hot
>      path — that's the L9 claim that most easily regresses.

---

## 1. Module layout (new)

```
openbb_platform/extensions/techtrade/openbb_techtrade/tuning/
├── __init__.py              # NEW — one-line docstring; PRD §12.4 pointer
├── tuneta_adapter.py        # NEW — the ONLY module that imports `tuneta`.
│                            #   _require_tuneta() lazy import (raises TechtradeDependencyError if absent);
│                            #   fit_segment(ohlcv, *, trials, early_stop, forward_horizon_bars) -> IndicatorConfig
│                            #   knob-spec table (L6: 8 knobs + their tuneta indicator strings + ranges);
│                            #   parse_tuned_columns(cols) -> IndicatorConfig (regex over tuneta's column-name encoding).
├── sector_ohlcv.py          # NEW — pool_sector_ohlcv(segment, as_of, horizon_years, *, fetcher=None)
│                            #   -> MultiIndex(date, symbol) OHLCV DataFrame. Injectable fetcher seam
│                            #   for offline tests (mirrors engine/indicators.py:_default_ohlcv_fetcher).
├── tuned_defaults.py        # NEW — read_tuned() / write_tuned(segment, config, meta) for
│                            #   ~/.openbb_platform/techtrade_tuned.json. Mtime-cached reader (Q-E);
│                            #   IndicatorConfig (de)serializer; schema-version check.
└── tune_router.py           # NEW — the `tune` command (obb.techtrade.tune). Adds itself to
                             #   techtrade_router._include_subrouters' tuple (so absence of
                             #   `tuneta` simply means the sub-router isn't registered, same as
                             #   the validate sub-router's behaviour with openbb-backtest absent).

openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py
└── MODIFIED — build_indicator_panel signature grows
            `config: IndicatorConfig | None = None`. When None, consult
            tuning.tuned_defaults by symbol → segment (L9). Default-arg
            behaviour preserved for every existing caller passing no `config`.

openbb_platform/extensions/techtrade/openbb_techtrade/models.py
└── MODIFIED — add `TuningReport(Data)` (segment, candidate, validation, persisted,
            reason, as_of, tuneta_version, fit_seconds). Leaf-module discipline preserved
            (no openbb_backtest import: `validation: Data | None`, same trick L2 of #82).

openbb_platform/extensions/techtrade/pyproject.toml
└── MODIFIED — declare the long-anticipated `tuneta = ["tuneta"]` extra
            (the comment for it already exists at line 18; this declares it).

openbb_platform/extensions/techtrade/tests/
├── unit/
│   ├── test_tuneta_adapter.py            # NEW — knob mapping, column parsing,
│   │                                     #   degradation when tuneta absent.
│   ├── test_sector_ohlcv.py              # NEW — MultiIndex shape, fetcher seam.
│   ├── test_tuned_defaults.py            # NEW — read/write roundtrip, mtime invalidation,
│   │                                     #   missing-file → empty, schema-version check.
│   ├── test_tune_router.py               # NEW — full pipeline with faked tuneta+validate;
│   │                                     #   robust persists, fragile/overfit do not.
│   └── test_panel_consults_tuned_defaults.py  # NEW — regression on indicators.py:
│                                              #   panel uses tuned config when segment present;
│                                              #   explicit `config=` arg overrides tuned default.
└── integration/
    └── test_tune.py                      # NEW — end-to-end against in-tree openbb-backtest
                                          #   + real tuneta; skipif tuneta / fmp_cached absent.
```

**Module-boundary rules**

- `tuning/tuneta_adapter.py` is the **only** module that imports `tuneta`. It does so **lazily inside function bodies**; there is no top-level `import tuneta` anywhere in techtrade (L8/Q-G).
- `tuning/tune_router.py` imports `openbb_techtrade.validation.backtest_bridge.validate_plan` — a regular (non-lazy) import is fine, because #82 already imports cleanly without `openbb-backtest` (its own lazy guards handle absence). The chain works: `tune` calls `validate_plan` calls backtest. If `openbb-backtest` is absent **and** `tuneta` is installed, `tune` will fail with the *backtest's* `TechtradeDependencyError`, which is the correct user-facing message (they need both to do meaningful tuning).
- `tuning/sector_ohlcv.py` depends only on `pandas` (already a base dep) and `openbb_core` / the segment-resolver. No `tuneta` import; the OHLCV layout is just a MultiIndex DataFrame.
- `tuning/tuned_defaults.py` depends only on `pathlib` and `json` (stdlib) plus `openbb_techtrade.engine.indicators.IndicatorConfig`. No `tuneta` import. This module is **always importable** even when `tuneta` is absent — so `engine/indicators.py` can call it on the hot path safely.
- `engine/indicators.py` gets a small read-only dependency on `tuning/tuned_defaults.py` (one import: `from openbb_techtrade.tuning.tuned_defaults import lookup_tuned_for_symbol`). No cycles: `tuned_defaults` does NOT import `indicators` — it returns dicts that the panel builder converts into `IndicatorConfig` itself.
- techtrade does **not** add `tuneta` to its base `[tool.poetry.dependencies]`; it lives only in the `[tuneta]` extra (L8).

---

## 2. Dependency posture & graceful degradation (L8 / Q-G)

The pattern is **identical to #82** (and the deliberate contrast with #73's hard dep on `openbb-technical`):

| | #73 (`openbb-technical`) | #82 (`openbb-backtest`) | **#83 (`tuneta`)** |
|---|---|---|---|
| Dependency kind | **Hard** — base `[tool.poetry.dependencies]` | **Soft/optional** — `[validation]` extra | **Soft/optional** — `[tuneta]` extra |
| Import site | top-level OK once installed | **lazy, in-body only** | **lazy, in-body only** |
| Absent at runtime | install error (acceptable) | **clear actionable error**; core still works | **clear actionable error**; core still works |
| Error class | `OpenBBError` subclass | `TechtradeDependencyError` (introduced #82) | `TechtradeDependencyError` (**reused**, not duplicated) |
| Enforced by | covered-set parity oracle | #85 core-unchanged-when-removed test (backtest case) | **same #85 test, extended to cover the tuneta-absent case** |

**Degradation path (lazy import + clear error):**

```python
# tuning/tuneta_adapter.py  (illustrative — mirrors backtest_bridge._require_backtest)
from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError

_PIP_INSTALL_HINT = "pip install 'openbb-techtrade[tuneta]'"


def _require_tuneta():
    """Lazily import `tuneta`, or raise a clear error.

    techtrade stays importable/installable without `tuneta`; only obb.techtrade.tune
    needs it. Other commands (movers / signals / plan / scan / export / validate)
    keep importing and running.
    """
    try:
        from tuneta.tune_ta import TuneTA
    except ImportError as exc:
        raise TechtradeDependencyError(
            "obb.techtrade.tune requires the 'tuneta' package, which is not installed. "
            f"Install it with: {_PIP_INSTALL_HINT}"
        ) from exc
    return TuneTA
```

> **Why reuse `TechtradeDependencyError`** (not a new `TechtradeTunetaError`):
> the error semantics — "an optional techtrade dependency is missing; the rest still
> works; here's the pip command" — are identical to #82's. A single leaf class
> means user code that does `except TechtradeDependencyError` catches both
> missing-`openbb-backtest` and missing-`tuneta`. The specific dependency is
> identifiable from the message (which already names both the package and the
> install command), not from the class hierarchy.

---

## 3. The tuneta adapter (the core integration)

### 3.1 The REAL `tuneta` API (grounded in `jmrichardson/tuneta` README, MIT)

```python
from tuneta.tune_ta import TuneTA

tt = TuneTA(n_jobs=4, verbose=False)
tt.fit(
    X_train,                                      # OHLCV DataFrame, MultiIndex (date, symbol) for multi-symbol
    y_train,                                      # forward-return series, indexed compatibly
    indicators=['tta.RSI', 'tta.MACD', ...],      # list of dotted indicator names (pta / tta / fta)
    ranges=[(8, 30), (8, 20), (20, 40), ...],     # (low, high) period range per indicator
    trials=100,                                   # Optuna trials per indicator
    early_stop=20,                                # early-stop after N non-improving trials
)
features = tt.transform(X_train)
# `features.columns` carries the tuned params encoded in the column NAME:
#   "tta_RSI_timeperiod_19"
#   "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9"
# This is how we read off the chosen periods.
```

Key contract points:

- `fit` **mutates internal state**; returns no value. The "tuned configuration" is recovered by inspecting `tt.transform(X).columns` (or `tt.fitted` / equivalent — verify against installed version at implementation time, README does not pin the exact attribute name).
- Multi-symbol: `X` is indexed by `(date, symbol)`. `y` must align. This matches L4's pooled-segment layout exactly.
- Distance correlation is tuneta's optimisation metric — the period that best correlates with `y` over the fit window wins.
- License: MIT; AGPL-compatible.

### 3.2 The knob-spec table (L6) — single source of truth in the adapter

The adapter ships a frozen tuple mapping `IndicatorConfig` field → `(tuneta indicator name, range)`:

| `IndicatorConfig` field | `tuneta` indicator string | Range | Notes |
|---|---|---|---|
| `macd_fast` | `tta.MACD` (fastperiod) | (8, 20) | Bundled with slow/signal; parsed as `MACD_fastperiod_<int>` |
| `macd_slow` | `tta.MACD` (slowperiod) | (20, 40) | Same bundle; parsed as `_slowperiod_<int>` |
| `macd_signal` | `tta.MACD` (signalperiod) | (5, 15) | Same bundle; parsed as `_signalperiod_<int>` |
| `adx_length` | `tta.ADX` | (10, 30) | Single-period; parsed as `ADX_timeperiod_<int>` |
| `ema_fast` | `tta.EMA` (fast slot) | (10, 30) | Two EMAs in the panel — adapter requests them as `tta.EMA` ranged (10,30) and (30,80) and binds by range |
| `ema_slow` | `tta.EMA` (slow slot) | (30, 80) | (see above) |
| `rsi_length` | `tta.RSI` | (8, 30) | Single-period; parsed as `RSI_timeperiod_<int>` |
| `atr_length` | `tta.ATR` | (10, 30) | Single-period; parsed as `ATR_timeperiod_<int>` |

The 7 untouched `IndicatorConfig` fields (`stoch_k`, `stoch_d`, `stoch_smooth_k`, `bb_length`, `bb_std`, `kc_length`, `kc_scalar`) are copied verbatim from `DEFAULT_CONFIG` into the candidate `IndicatorConfig`.

> **EMA binding sharp edge:** tuneta would treat both `tta.EMA` requests as one knob unless we differentiate. The adapter requests `tta.EMA` *twice* with disjoint ranges `(10,30)` and `(30,80)`; the column-name parser binds the period in `(10,30)` to `ema_fast` and the period in `(30,80)` to `ema_slow`. A unit test covers the binding.

### 3.3 Column-name → `IndicatorConfig` parser

The parser is a small regex map keyed on tuneta's emitted column-name encoding (one regex per knob from the table above). The full unit test asserts the round-trip: known column names → expected `IndicatorConfig` field values.

```python
# Illustrative shape; not a literal implementation
_COLUMN_RX = {
    "rsi_length":   re.compile(r"^tta_RSI_timeperiod_(\d+)$"),
    "macd_fast":    re.compile(r"^tta_MACD_fastperiod_(\d+)_slowperiod_\d+_signalperiod_\d+$"),
    "macd_slow":    re.compile(r"^tta_MACD_fastperiod_\d+_slowperiod_(\d+)_signalperiod_\d+$"),
    "macd_signal":  re.compile(r"^tta_MACD_fastperiod_\d+_slowperiod_\d+_signalperiod_(\d+)$"),
    "adx_length":   re.compile(r"^tta_ADX_timeperiod_(\d+)$"),
    "atr_length":   re.compile(r"^tta_ATR_timeperiod_(\d+)$"),
    # ema_fast / ema_slow handled by separate logic: collect every tta_EMA_timeperiod_<int>
    # then bind the value in (10,30) to ema_fast and the value in (30,80) to ema_slow.
}
```

**Failure mode**: if tuneta emits a column the parser doesn't recognise (library update, surface drift), the adapter logs at WARNING and falls back to the default for that knob — never raises. The candidate `IndicatorConfig` is then a partial tune (some knobs PRD-default, some tuned). This degrades gracefully and surfaces in the TuningReport.

### 3.4 The pooled-segment OHLCV (L4)

`sector_ohlcv.pool_sector_ohlcv(segment, as_of, horizon_years, *, fetcher=None)` returns a `pandas.DataFrame` indexed by `MultiIndex.from_product([dates, symbols])` with OHLCV columns. Implementation:

1. Resolve the segment's symbol universe via the existing segment resolver (#69 / `engine/universe.py`).
2. For each symbol, call `fetcher(symbol, start=as_of - horizon_years, end=as_of)` → per-symbol DataFrame.
3. Concatenate into the MultiIndex frame.
4. Compute `y` = forward-cumulative-return per (date, symbol) over `forward_horizon_bars` (Q-B; default 20).
5. Drop tail rows that have NaN forward returns (the last `forward_horizon_bars` rows of each symbol).

`fetcher` defaults to a lazy-imported `fmp_cached` price fetcher (same pattern as `engine/movers.py`). Tests inject a fake fetcher that returns synthetic OHLCV → fully offline unit tests.

---

## 4. The `tune` command + per-segment validate flow (L5, L7)

### 4.1 Router

```python
# tuning/tune_router.py
@router.command(methods=["POST"])
async def tune(
    segment: str,
    *,
    as_of: date | None = None,                  # default: today (UTC date)
    horizon_years: int = 5,                     # Q-C
    forward_horizon_bars: int = 20,             # Q-B
    trials: int = 100,                          # Q-D
    early_stop: int = 20,                       # Q-D
    method: str = "wfo",                        # forwarded to #82's validate
    thresholds: dict[str, float] | None = None, # forwarded to #82's validate
    provider: str | None = None,                # forwarded to #82's validate
) -> OBBject[TuningReport]:
    """Tune indicator periods for a GICS segment, gated by #82 validation.

    Pipeline (per segment):
      1. pool_sector_ohlcv(segment, as_of, horizon_years) -> (X, y)
      2. tuneta_adapter.fit_segment(X, y, trials, early_stop) -> candidate IndicatorConfig
      3. build_sample_plan(segment, candidate, as_of) -> TradePlan for benchmark ETF (Q-A: A1)
      4. validate_plan(plan, method=method, thresholds=thresholds, provider=provider)
         -> ValidationReport
      5. if report.verdict == "robust":  persist via tuned_defaults.write_tuned(segment, ...)
         else:                            do not persist; reason captured
      6. return OBBject(results=TuningReport(...))
    """
```

### 4.2 `TuningReport` model (`models.py`)

```python
# Illustrative — final field set may grow if reviewers ask for more provenance
class TuningReport(Data):
    """Outcome of one `obb.techtrade.tune(segment)` call (PRD §12.4, #83)."""
    segment: str
    as_of: date
    candidate: IndicatorConfig             # what tuneta proposed (always present, even when not persisted)
    validation: Data | None                # ValidationReport from #82 (Data|None for the L2 of-#82 reason: import isolation)
    persisted: bool                        # True iff verdict == "robust" and write succeeded
    reason: str                            # human-readable: "verdict=robust", "verdict=fragile (pbo=0.31)", etc.
    tuneta_version: str                    # captured from tuneta.__version__ at fit time
    fit_seconds: float                     # wall-clock the tuneta.fit() took
    trials: int                            # the budget actually used
    early_stop: int                        # ditto
```

> **Why `validation: Data | None` and not `validation: ValidationReport`:** same
> L2-of-#82 reason — typing it as `ValidationReport` would force `models.py` to
> import `openbb_backtest.models`, breaking the "techtrade is installable without
> `openbb-backtest`" guarantee. `Data | None` keeps the model leaf and lets the
> field carry the concrete report when populated.

### 4.3 Sample plan for the per-segment validate (Q-A: A1)

The sample plan uses the segment's benchmark ETF as `symbol`. Minimal fixture:

```python
def build_sample_plan(segment: str, candidate: IndicatorConfig, as_of: date) -> TradePlan:
    """Construct a deterministic single-symbol plan for the segment's ETF.

    The plan only needs to satisfy validate_plan's input contract — its orders /
    fills / recommendation fields don't affect the validation math (#82 design §3.2:
    validate re-runs the strategy from history, the plan is the attach target).
    """
    etf = _SEGMENT_BENCHMARK_ETFS[segment]  # XLK, XLF, ... — small constant table
    sig = MoverSignal(symbol=etf, segment=segment, as_of=as_of, score=0.5, direction="long",
                      votes=[], rank_in_segment=1)
    rec = Recommendation(...)               # zeroed; only existence required by validate_plan's input
    return TradePlan(symbol=etf, segment=segment, as_of=as_of, signal=sig,
                     rule=EntryExitRule(), position_size=Decimal("1"),
                     orders=[], simulated_fills=[], recommendation=rec)
```

> The candidate `IndicatorConfig` does NOT need to be embedded in the plan — it
> goes through the **persistence side-channel**: when `validate_plan` re-runs the
> `techtrade_confluence` strategy over the WFO folds (#82, Q-B B2), the strategy
> *also* consults the tuned-defaults file via L9's auto-load path. So the candidate
> must be **temporarily written to disk** before the validate call and **reverted**
> after — see §5.3 below.

---

## 5. Persistence + auto-load (L3, L9, Q-E)

### 5.1 JSON schema (`~/.openbb_platform/techtrade_tuned.json`)

```json
{
  "schema_version": "1.0",
  "segments": {
    "Information Technology": {
      "config": {
        "macd_fast": 14, "macd_slow": 32, "macd_signal": 9,
        "adx_length": 16, "ema_fast": 18, "ema_slow": 55,
        "rsi_length": 11, "atr_length": 18,
        "stoch_k": 14, "stoch_d": 3, "stoch_smooth_k": 3,
        "bb_length": 20, "bb_std": 2.0, "kc_length": 20, "kc_scalar": 1.5
      },
      "meta": {
        "verdict": "robust",
        "pbo": 0.18,
        "dsr": 0.97,
        "oos_sharpe": 0.84,
        "tuned_at": "2026-06-21T16:49:48Z",
        "tuneta_version": "0.2.3",
        "as_of": "2026-06-21",
        "horizon_years": 5
      }
    }
  }
}
```

Schema notes:
- `schema_version` lets future tunes recognise and migrate (or refuse) older files.
- The full 15-field `IndicatorConfig` is stored (not just the 8 tuned ones) so re-loading is straightforward; the 7 untouched fields equal `DEFAULT_CONFIG`.
- `meta` is parallel to `config`, not nested inside it — so the `config` block round-trips cleanly through `IndicatorConfig(**data["config"])` without filtering.

### 5.2 Auto-load on the hot path (L9, Q-E)

`engine/indicators.py:build_indicator_panel` signature change:

```python
# BEFORE (current)
def build_indicator_panel(symbol: str, as_of: date, rows: list[dict],
                          config: IndicatorConfig = DEFAULT_CONFIG) -> IndicatorPanel: ...

# AFTER (#83)
def build_indicator_panel(symbol: str, as_of: date, rows: list[dict],
                          *, config: IndicatorConfig | None = None) -> IndicatorPanel:
    """When config is None: consult ~/.openbb_platform/techtrade_tuned.json for the
    symbol's segment; use the tuned IndicatorConfig if present, else DEFAULT_CONFIG.
    Explicit config arg wins over both (caller intent is paramount).
    """
    if config is None:
        config = lookup_tuned_for_symbol(symbol) or DEFAULT_CONFIG
    # ... rest unchanged
```

`tuning/tuned_defaults.py:lookup_tuned_for_symbol(symbol)`:

1. Resolve the symbol's segment via the segment resolver.
2. Read the mtime-cached JSON (`_read_cached_or_load()` — `lru_cache` keyed on `(path, mtime_ns)`).
3. If the segment is present and `meta.verdict == "robust"` (defensive double-check), return `IndicatorConfig(**data["segments"][segment]["config"])`.
4. Else return `None`.

> **Backward compatibility note:** the existing `config: IndicatorConfig = DEFAULT_CONFIG` positional default is changing to a **keyword-only** `config: IndicatorConfig | None = None` — this is technically a signature change. Every in-repo caller passes `config=` by keyword (verified) so this is internally safe; but it's a public-API change worth flagging in the implementation plan's first commit message.

### 5.3 The write-validate-revert dance (a subtle correctness point)

The per-segment validate (§4.3) needs the candidate `IndicatorConfig` to be the *active* config when `techtrade_confluence` re-runs over the WFO folds. Two options:

| Option | Mechanism | Tradeoff |
|---|---|---|
| **W1** | Write candidate → validate → if not robust, revert (remove segment entry) | Correct; small window of "wrong" state on disk if a concurrent `scan` runs mid-validate |
| **W2** | Pass candidate config via a thread-local / contextvar that `lookup_tuned_for_symbol` consults first | No disk dance; no concurrency window; adds a new mechanism to test |

- **Recommendation:** **W2 — contextvar.** `tuning/tuned_defaults.py` exposes a `_TUNE_OVERRIDE: ContextVar[dict[str, IndicatorConfig] | None] = ContextVar("tune_override", default=None)`. `tune_router.tune` enters a `with _override({segment: candidate}):` block around the validate call. `lookup_tuned_for_symbol` checks the override first, then the file. No disk write happens until *after* the verdict is `robust`. Concurrent `scan` calls in another thread are unaffected.

> Documented here so reviewers can pick W1 if they prefer a simpler mental model and a one-line revert; the implementation plan can branch on the answer.

> - **Answer (Review):** ✅ **Approved — W2 (contextvar). Verified 2026-06-21 against the #82 code.**
>
>   1. **Execution-model verification (the fact your conditional asked for).** Grep across the
>      entire `openbb_backtest` package for `ThreadPool` / `ProcessPool` / `run_in_executor` /
>      `multiprocessing` / `joblib.Parallel` / `concurrent.futures` / `asyncio.gather` /
>      `asyncio.create_task` / `ray` / `dask` returns **zero hits**. The fold loop in
>      `openbb_backtest/routers/validate_router.py:206` is a plain `for i, fold in enumerate(folds):`
>      that runs sequentially in the caller's task. The `async def validate` declaration exists for
>      REST-streaming surface consistency (`09-api-surface.md` §2) but does no executor offload.
>      `validate_plan` therefore runs in the *same* asyncio task as `tune_router.tune`, which means
>      a `ContextVar` set in `tune` propagates correctly into `_run_folds` via standard asyncio
>      context-copy semantics. **W2 is safe today.**
>   2. **Therefore W2 is locked**, with two guards that survive a future #82 refactor:
>      - **Locked-in test (`test_override_visible_in_validate_fold`):** asserts the contextvar
>        override set by `tune` is *actually observed* by `lookup_tuned_for_symbol` during the
>        validate call — not just that the var is set in the `tune` frame. Catches the
>        executor-regression the moment backtest adds one.
>      - **Boundary-comment in code:** `tuned_defaults.py` documents that the override mechanism
>        assumes `validate_plan` runs in the same asyncio task; if #82 ever fans folds out via
>        `run_in_executor` or `multiprocessing`, contributors must either wrap each fold in
>        `contextvars.copy_context().run(...)` or migrate this path to W1.
>   3. **W1 stays documented above as the fallback** so a future contributor who hits the regression
>      knows the migration target: write candidate → validate → `try/finally` revert, using
>      `tempfile.NamedTemporaryFile` + `os.replace` for atomic write to dodge the Q-E coarse-mtime
>      race.
>   4. **Why W1 is *not* preferred today even though it'd also work:** the test
>      `test_fragile_verdict_does_not_persist` (§6) asserts the JSON file is *unchanged* on a
>      non-robust verdict. With W1, that test only checks the post-revert state and silently
>      tolerates the mid-validate window; with W2, "no write happens at all" is the literal
>      runtime invariant. Stronger acceptance.

---

## 6. Determinism & testing (Q-G, #85)

| Test | Kind | Asserts |
|---|---|---|
| `test_tuneta_adapter.py::test_dependency_error_when_tuneta_absent` | unit (offline) | with `tuneta` forced un-importable, `fit_segment(...)` raises `TechtradeDependencyError` whose message contains `pip install` and `'openbb-techtrade[tuneta]'` |
| `test_tuneta_adapter.py::test_degradation_other_modules_still_import` | unit (offline) | with both `tuneta` and `openbb_backtest` forced absent, every other techtrade module still imports (extends #82's existing degradation fixture) |
| `test_tuneta_adapter.py::test_knob_table_maps_to_eight_periods` | unit | the L6 knob-spec table has exactly 8 entries with the documented ranges |
| `test_tuneta_adapter.py::test_parse_columns_recovers_indicator_config` | unit | given a fixed set of tuneta column names, the parser returns the expected `IndicatorConfig` field values (round-trip) |
| `test_tuneta_adapter.py::test_parse_unknown_column_falls_back_to_default` | unit | a column name the parser doesn't recognise → that knob stays at `DEFAULT_CONFIG`; no raise |
| `test_tuneta_adapter.py::test_ema_binding_by_range` | unit | given two `tta_EMA_timeperiod_*` columns, the one in `(10,30)` binds to `ema_fast`, the one in `(30,80)` binds to `ema_slow` |
| `test_sector_ohlcv.py::test_pool_returns_multiindex_date_symbol` | unit | the returned frame has a `MultiIndex[(date, symbol)]` and OHLCV columns |
| `test_sector_ohlcv.py::test_uses_injected_fetcher` | unit | with a fake fetcher returning synthetic OHLCV for two symbols, the result has both symbols and the correct row count |
| `test_sector_ohlcv.py::test_drops_tail_rows_with_nan_forward_returns` | unit | for `forward_horizon_bars=5`, the last 5 rows per symbol are dropped from `(X, y)` |
| `test_tuned_defaults.py::test_read_missing_file_returns_none` | unit | when `~/.openbb_platform/techtrade_tuned.json` does not exist, `lookup_tuned_for_symbol("AAPL")` returns `None` (no raise) |
| `test_tuned_defaults.py::test_read_after_write_roundtrips` | unit | `write_tuned("Information Technology", config, meta)` then `lookup_tuned_for_symbol("AAPL")` (which maps to IT via the segment resolver, mocked) returns an `IndicatorConfig` equal to the written one |
| `test_tuned_defaults.py::test_mtime_cache_invalidates_on_change` | unit | after a `write_tuned`, the next `lookup` sees the new value (no stale cache) — writes **twice in quick succession** (within one mtime tick) to actually exercise the Q-E coarse-mtime guard (`st_size` tiebreaker / explicit cache-clear) |
| `test_tuned_defaults.py::test_lru_cache_maxsize_bounded` | unit | re-writing the tuned file >8 times in one process never accumulates more than `maxsize=8` cache entries (Q-E guard 1: bounded cache) |
| `test_tuned_defaults.py::test_override_visible_in_validate_fold` | unit | **§5.3 W2 lock-in test.** Sets the contextvar override in the caller frame; a faked `validate_plan` inspects the override from inside its fold loop via `lookup_tuned_for_symbol`; assertion: the strategy sees the candidate config, not `DEFAULT_CONFIG`. Catches any future #82 refactor that breaks contextvar propagation. |
| `test_tune_router.py::test_no_op_tune_does_not_persist` | unit (Q-F guard 3) | if tuneta proposes a config equal to (or within rounding of) `DEFAULT_CONFIG`, `persisted=False` and `reason="no change from defaults"`; the JSON file is unchanged. Keeps `techtrade_tuned.json` meaningful (only genuinely-different robust configs land). |
| `test_tune_router.py::test_loop_over_mixed_verdicts_does_not_raise` | unit (Q-F guard 2) | a caller looping `tune` across multiple segments where verdicts are mixed (robust, fragile, overfit) completes the full loop and returns all reports; no exception aborts a sector mid-batch. Logged at WARNING per Q-F. |
| `test_tune_router.py::test_dependency_error_message_names_missing_extra` | unit (Q-G guard 2) | when `tuneta` is present but `openbb-backtest` is absent, the surfaced `TechtradeDependencyError` message names the missing extra (`[validation]`) AND mentions that a full tune needs **both** `[tuneta]` and `[validation]`; symmetrical case when `openbb-backtest` is present but `tuneta` is absent. |
| `test_panel_consults_tuned_defaults.py::test_panel_with_neither_extra_imports_and_works` | unit (Q-G guard 3) | with both `tuneta` and `openbb_backtest` forced absent, `import openbb_techtrade` succeeds and `build_indicator_panel(symbol, as_of, rows)` builds the panel via the L9 auto-load path (which finds no tuned file and falls back to `DEFAULT_CONFIG`). Proves the hot path of L9 stays importable with no extras. |
| `test_tuned_defaults.py::test_schema_version_mismatch_returns_none_and_logs` | unit | a file with `schema_version != "1.0"` is treated as absent (returns `None`), logged at WARNING |
| `test_tune_router.py::test_robust_verdict_persists` | unit (faked tuneta + faked validate) | a `verdict="robust"` `ValidationReport` triggers `write_tuned`; `TuningReport.persisted is True`; the segment is readable from the JSON afterward |
| `test_tune_router.py::test_fragile_verdict_does_not_persist` | unit | `verdict="fragile"` → `TuningReport.persisted is False`; the JSON file is **unchanged** (or absent if it didn't exist before) |
| `test_tune_router.py::test_overfit_verdict_does_not_persist` | unit | identical to fragile path with `verdict="overfit"` |
| `test_tune_router.py::test_tune_forwards_trials_and_early_stop` | unit | `tune(..., trials=50, early_stop=10)` reaches `fit_segment` with those exact values |
| `test_tune_router.py::test_tune_uses_benchmark_etf_for_sample_plan` | unit (Q-A: A1) | the `TradePlan` passed to `validate_plan` carries `symbol == SEGMENT_BENCHMARK_ETFS[segment]` |
| `test_panel_consults_tuned_defaults.py::test_panel_uses_tuned_when_present` | unit | after writing a tuned config for IT and looking up `AAPL` (in IT), the resulting panel uses the tuned periods (different from `DEFAULT_CONFIG`) |
| `test_panel_consults_tuned_defaults.py::test_panel_falls_back_to_default` | unit | with no tuned entry for IT, the panel uses `DEFAULT_CONFIG` (regression: existing behaviour preserved) |
| `test_panel_consults_tuned_defaults.py::test_explicit_config_overrides_tuned` | unit | passing `config=` explicitly bypasses the tuned-defaults lookup (caller intent wins) |
| `test_tune.py` | **integration** | full end-to-end on a single segment against the in-tree `openbb-backtest` + real `tuneta` against `fmp_cached`; asserts a verdict ∈ `{robust, fragile, overfit}` and a coherent `TuningReport`. Skipif `tuneta` / `openbb-backtest` / `fmp_cached` absent. |

**Degradation test discipline (#85 core-unchanged-when-removed):** the unit suite simulates "tuneta absent" by monkeypatching `builtins.__import__` to raise on any `import tuneta*` (same pattern #82 uses for `openbb_backtest`). The combined test covers both packages absent simultaneously, both present, and each one independently.

**Determinism:** the adapter itself is pure translation (no RNG it owns); `tuneta` carries its own Optuna seed (the adapter pins `random_state=0` if the version supports it — verified at implementation time). The tuned-defaults file write is JSON-stable via `json.dumps(sort_keys=True, indent=2)`. So `tune(segment, as_of=X)` is byte-stable across runs given the same OHLCV inputs and tuneta version.

---

## Acceptance mapping (#83)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| `tuning/tuneta_adapter.py` behind the `[tuneta]` extra | §1 (module layout) + §2 (extra declared in `pyproject.toml`) |
| `tune(segment, ...)` → `TuningReport` of proposed params | §4 (router) + §4.2 (`TuningReport` model) |
| Gate: only params passing PRD §15 validation (PBO/DSR via #82) persist; defaults ship un-tuned | §0 L2 (strict `verdict == "robust"`) + §4.1 step 5 + §5.1 schema (`meta.verdict` recorded) |
| Test: tuning proposes params; non-robust ones are rejected | §6 `test_tune_router.py::{test_fragile_verdict_does_not_persist, test_overfit_verdict_does_not_persist}` |
| `obb.techtrade.tune(...)` runs only when extra installed; otherwise clear message | §2 (lazy `_require_tuneta` + reused `TechtradeDependencyError` with `pip install` hint); §6 `test_dependency_error_when_tuneta_absent` |
| Tuned params persist **only** if they pass validation | §0 L2 + §4.1 + §6 robust/fragile/overfit tests |
| Core behavior unchanged when extra absent | §0 L8 + §2 (degradation table) + §6 `test_degradation_other_modules_still_import` (extends the #85 enforcement) |
| Reflects PRD §12.4 ("indicator periods/weights per segment, gated by validation") | §0 L1 (periods only, per L1 decision — weights deliberately out of scope; L4 per-segment; L2 gated) |
| Reflects PRD §19 ("tune gated by openbb-backtest PBO/DSR; defaults ship un-tuned") | §0 L2 + §0 L5 (per-segment validate) + §5 (persistence only on `robust`) |

---

## Notes for reviewers

- **Q-A through Q-G + the §5.3 W1/W2 split are the active review questions.** All other content is locked.
- The full implementation will go through the writing-plans skill once this design is approved.
- Implementation lives under `bd OpenBBTechnical-950` (currently `in_progress`); the design doc is part of the in-progress claim, not a separate bead.
- A `[bug] OpenBBTechnical-46y` was filed during the #82 verification pass for a pre-existing pytest-collection collision in the broader techtrade test tree — unrelated to #83 but it will affect how we run the full unit suite during #83's TDD loop. Plan will route around it (per-file pytest invocations) until that bug is resolved separately.
