# 81 — Excel Recommendation Export (6 Sheets + Conditional Formatting + Disclaimer)

**GitHub:** [#81](https://github.com/prajoria/OpenBB/issues/81) · **Phase:** P5 · **Sprint:** 5 · **Size:** L
**Depends on:** [#80](https://github.com/prajoria/OpenBB/issues/80) (Recommendation builder) · [#64](https://github.com/prajoria/OpenBB/issues/64) (Q9, **RESOLVED**)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §14.3 (Excel recommendation export), §20 Q9 (engine/disclaimer decision)
**Scope:** Add `reporting/excel_export.py` + the `obb.techtrade.export(plans, path=…, engine=…)` command that writes a deterministic **6-sheet `.xlsx` workbook** (Recommendations, Levels, Reasoning, Orders, Fills, Summary) with conditional formatting, a per-workbook disclaimer on **Recommendations**, and a **golden test** that locks structure/values/disclaimer.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

This step is the techtrade pipeline's **report generator** — it takes the finished trade
recommendations and writes them to a polished, multi-sheet **Excel workbook** a human can open,
skim, filter, and share. Everything upstream lives in memory as Python objects; this is where it
becomes a tangible deliverable on disk. Each recommendation (built by
[#80 the Recommendation builder](./80-recommendation-builder.md)) becomes one row, and the workbook
breaks the detail across **six fixed sheets**: *Recommendations* (the headline BUY/SELL/HOLD call),
*Levels* (entry/stop/target and the risk geometry), *Reasoning* (the narrative + per-indicator vote
breakdown), *Orders* (the orders that would be placed), *Fills* (the paper-simulated executions from
[#78](./78-paperbroker-fill-sim.md)), and *Summary* (run-level roll-ups: counts, average risk:reward,
the preset and weights used).

Two product requirements shape the design. First, **conditional formatting**: the workbook is
color-coded so the eye lands on what matters — green BUYs, red shorts, a data-bar on risk:reward, a
color scale on the score — so it reads like a dashboard, not a CSV dump. Second, a **mandatory
disclaimer** ("Research/paper output — not investment advice") printed on the Recommendations sheet
of *every* workbook; this is a locked compliance requirement (PRD §20 Q9), never suppressible.

The defining engineering constraint is **determinism**. The same inputs must always produce the same
logical workbook, so it can be locked by a golden test. That turns out to be subtle for `.xlsx`
files, which are zips of XML carrying wall-clock timestamps — so a literal byte-for-byte golden is
both fragile and impossible across the two supported engines (`openpyxl`, the default, and the
optional `xlsxwriter`). The headline open question below resolves this by golden-locking a
**structure/value snapshot** (read the workbook back, normalize sheets/cells/formats/disclaimer to
JSON, and compare via the existing [#71](https://github.com/prajoria/OpenBB/issues/71) test
harness) rather than raw bytes. Money stays `Decimal` end-to-end; Excel display rounding is
presentation-only and never mutates the stored model value.

---

## 0. Key decisions (locked) + open questions

### 0.1 Locked (carried from §20 Q9 [#64](https://github.com/prajoria/OpenBB/issues/64), `ExportConfig` in `models.py`, PRD §14.3 / §17)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | Export engine (**Q9 — do not reopen**) | **`openpyxl` is the default core engine**; `xlsxwriter` is an **optional** engine selectable via `ExportConfig.engine ∈ {openpyxl, xlsxwriter}` | Matches `ExportConfig.engine` default; no heavy dep in core; reuses the `fmp_cached/equity_screener_tool.py` `pd.ExcelWriter(engine="openpyxl")` convention (L7) |
| L2 | Sheet set | **Fixed 6 sheets** in order `Recommendations, Levels, Reasoning, Orders, Fills, Summary` (`ExportConfig.include_sheets` default) | `include_sheets` may *subset* but never reorder; golden locks the canonical 6 |
| L3 | Disclaimer (**Q9**) | **REQUIRED** one-liner *"Research/paper output — not investment advice"* on the **Recommendations** sheet of **every** workbook | Asserted by the golden test (§5); never suppressible by config |
| L4 | Default path | `Analysis/exports/techtrade_<YYYY-MM-DD>.xlsx`, date = the run's **as-of** (not wall-clock) | Deterministic filename; dir auto-created (Q-F) |
| L5 | Conditional formatting | `ExportConfig.conditional_formatting` **default `True`** | Action/Conviction/R:R/Stop %/Score formatting on by default (§3); `False` ⇒ plain values only |
| L6 | Determinism | **Byte/structure-stable** workbook: rows sorted **segment → conviction**, fixed column order, **no wall-clock timestamps in cells** beyond the as-of/run date | The central testability constraint; drives Q-A |
| L7 | Convention reuse | `pandas.ExcelWriter(engine=…)` + `df.to_excel(...)`, mirroring `fmp_cached/equity_screener_tool.py` (one writer, sheet-per-`to_excel`) | No bespoke XML; openpyxl post-pass adds formatting/disclaimer |
| L8 | Router wiring | `export` attaches via `openbb_techtrade.reporting.export_router` — already listed in `techtrade_router._include_subrouters`; the empty `reporting/` package already exists | New `export_router.py` auto-wires the moment it lands; bare-`OBBject` return (static-package-builder rule) |
| L9 | Numeric discipline | Money = `Decimal`, scores/ratios/percents = `float` (per `models.py`); cells render via Excel **number_format**, the **stored value is the model value** (no pre-round) | Display rounding ≠ stored value (Q-E) |

### 0.2 Open questions (please review / brainstorm)

> **Q-A — the golden `.xlsx` stability mechanism (HEADLINE — the central testing choice).**
> An `.xlsx` is a **zip of XML parts**; **byte-identical is fragile and partly impossible**:
> - openpyxl writes `docProps/core.xml` with `<dcterms:created>`/`<dcterms:modified>` **wall-clock
>   timestamps**, and the zip stores per-member mtimes → two runs differ byte-wise.
> - an openpyxl version bump re-serializes XML (attribute order, defaults) → bytes churn with no
>   logical change.
> - **`openpyxl` and `xlsxwriter` produce completely different bytes** for the *same logical
>   workbook*, so a single byte-golden **cannot** cover both engines (L1).
>
> | Opt | Mechanism | Pros | Cons |
> |---|---|---|---|
> | **(i) — RECOMMEND** | **Structure/value golden:** write to a temp file, **read back** with `openpyxl.load_workbook`, normalize (sheet names+order, per-sheet header row + cell values, number formats, CF rule descriptors, disclaimer text) → compare via the existing **`testing.assert_matches_golden`** JSON harness ([#71](https://github.com/prajoria/OpenBB/issues/71), already handles `Decimal`/`date`) | Engine-agnostic; openpyxl-version-robust; diffable JSON; **reuses the in-tree harness**; `TECHTRADE_REGEN_GOLDEN=1` regen path | Doesn't lock raw bytes (we argue bytes are the wrong invariant) |
> | (ii) | **Zip normalization:** strip/pin `docProps` timestamps + zip mtimes (fixed epoch), then byte-compare | True byte-stability for one engine | Still **single-engine only**; brittle to openpyxl internals; custom post-processor to maintain |
> | (iii) | **Per-sheet DataFrame equality:** `pd.read_excel(sheet)` → `assert_frame_equal` per sheet | Simple value check | Loses formatting/CF/disclaimer (those aren't cells) → needs a second structural pass anyway |
>
> **Recommendation: (i)** — read the workbook back and assert a **structural/value snapshot**, *not* raw
> bytes; the "golden `.xlsx`" becomes a committed **JSON structural snapshot** (no binary in git) plus,
> optionally, **one committed sample `.xlsx` as a non-asserted human-openable artifact**. **Confirm:**
> structure/value golden over byte-identical, and whether to commit the sample `.xlsx` artifact at all.
>
> - **Answer (Review):** ✅ **Approved — option (i), structural/value golden.**
>
>   1. **Byte-identical is the wrong invariant for `.xlsx`.** The format is a zip of XML with
>      embedded timestamps and engine-specific serialization. Byte-comparison would create a
>      permanently flaky test that breaks on every openpyxl version bump, CI clock skew, or
>      engine switch. This is not a theoretical concern — `docProps/core.xml` embeds wall-clock
>      `dcterms:created` and `dcterms:modified` that differ *every run*.
>
>   2. **JSON structural snapshot is strictly better.** It locks what matters (sheet names,
>      column order, cell values, number formats, CF rule descriptors, disclaimer text) while
>      ignoring what doesn't (XML attribute order, zip mtimes, engine serialization quirks).
>      It reuses the existing `testing.assert_matches_golden` harness (#71) — no new testing
>      infrastructure needed.
>
>   3. **Commit the sample `.xlsx` as a non-asserted artifact — yes.** A human-openable sample
>      in the repo is useful for onboarding and PR review. It should be clearly documented as
>      non-asserted (the JSON golden is the source of truth).

> **Q-B — conditional-formatting portability across engines (openpyxl vs xlsxwriter).**
> openpyxl **does** support color scales / data bars / cell-is rules
> (`openpyxl.formatting.rule.{ColorScaleRule, DataBarRule, CellIsRule, FormulaRule}` +
> `ws.conditional_formatting.add(range, rule)`) — just more verbose than xlsxwriter's
> `ws.conditional_format(...)`. So full §14.3 formatting is achievable on the **default** engine. Open:
> - **B1 (RECOMMEND):** ship **full formatting on openpyxl** (it is the default + core engine, L1, and
>   `conditional_formatting=True` is the default, L5). Define the rules **once** as an engine-agnostic
>   `FORMAT_SPEC` (list of rule descriptors: target column, kind, thresholds/colors) and render them with
>   **two thin appliers** (`_apply_openpyxl`, `_apply_xlsxwriter`) — single source of truth, mirroring the
>   `selector.SOURCE_TABLE` discipline from [#73](https://github.com/prajoria/OpenBB/issues/73).
> - **B2:** formatting-rich **only** on `xlsxwriter`, with a **plainer openpyxl fallback** (Action/Conviction
>   fills + number formats, but skip data-bars). Less openpyxl code; weaker default deliverable.
>
> **Cross-engine golden coverage (ties to Q-A):** the structural golden reads CF rules back via openpyxl.
> An xlsxwriter-written file is still a valid `.xlsx` openpyxl can open, **but openpyxl may not round-trip
> xlsxwriter's CF descriptors identically**. Proposal: the **shared** golden asserts only engine-agnostic
> logical structure (sheet set + values + disclaimer); **formatting is asserted per-engine** in lighter
> engine-specific checks. **Confirm:** is xlsxwriter formatting **parity** in scope for v1, or is xlsxwriter
> "best-effort richer" with only openpyxl formatting golden-locked?
>
> - **Recommendation:** B1 — ship **full conditional formatting on the default openpyxl engine** from a
>   single engine-agnostic `FORMAT_SPEC` + two thin appliers; golden-lock **openpyxl** formatting only and
>   treat xlsxwriter as **best-effort richer** (no formatting parity required for v1).
> - **Answer (Review):** ✅ **Approved — B1 (full openpyxl formatting, best-effort xlsxwriter).**
>
>   1. **Full formatting on openpyxl — correct for the default engine.** openpyxl supports all
>      the CF rules needed (CellIsRule, ColorScaleRule, DataBarRule). The workbook is a *report*,
>      not a CSV dump — conditional formatting is what makes it useful at a glance.
>
>   2. **Single `FORMAT_SPEC` + two appliers — correct architecture.** One source of truth for
>      the rules (thresholds, colors, target columns), two thin rendering functions. This is
>      the same pattern as `selector.SOURCE_TABLE` from #73: the data is declared once, the
>      engine-specific rendering is thin and mechanical.
>
>   3. **xlsxwriter best-effort — pragmatic for v1.** Achieving byte-identical CF round-trip
>      across two engines is a rabbit hole. xlsxwriter formatting will *look* right (it uses
>      the same `FORMAT_SPEC`), but the golden test doesn't assert it. If a user reports a
>      formatting discrepancy, it's a bug fix, not a design failure.

> **Q-C — exact per-sheet column mapping + ordering (confirm §14.3 → fields).**
> §2 proposes the full `Recommendation`/`Order`/`Fill` field → column mapping for all six sheets. Two
> spots need sign-off:
> - **Reasoning sheet** needs the **per-family vote breakdown** (Trend/Momentum/Volatility/Volume), which
>   lives on `TradePlan.signal.votes` — **not** on `Recommendation`. This forces the input to be
>   `list[TradePlan]`, not `list[Recommendation]` (→ Q-D). Confirm vote grouping/format (one column per
>   family with a compact `name:vote×weight` string? or a signed family sum?).
> - **Summary roll-ups** — `as-of, calendar, preset, weights, segment counts, #BUY/SELL/FLAT, avg R:R,
>   submodule pin, validation coverage` — are **not** all on any one model. Derivable from the plans:
>   `as-of` (`plan.as_of`), segment counts, `#BUY/SELL/FLAT` (count by `action`), `avg R:R`
>   (mean `risk_reward` over actionable rows), `validation coverage` (count of plans with `.validation`
>   populated, [#82](https://github.com/prajoria/OpenBB/issues/82)). **Not** derivable: `calendar`, `preset`, `weights` ([#74](https://github.com/prajoria/OpenBB/issues/74) confluence weights),
>   `submodule pin` — these are **run context** threaded from the producing `scan` ([#79](https://github.com/prajoria/OpenBB/issues/79)) → Q-D.
>
> - **Recommendation:** adopt the §2 column→field mapping as the single `SHEET_SPEC`; render the Reasoning
>   sheet's per-family breakdown as **one column per family** holding a compact signed family sum from
>   `plan.signal.votes`; derive every Summary roll-up that can be computed from `plans`, and source the
>   rest (`calendar`/`preset`/`weights`/`submodule pin`) from the optional `scan` run-`context` (Q-D).
> - **Answer (Review):** ✅ **Approved — follow recommendation.**
>
>   1. **`SHEET_SPEC` as the single column→field mapping — correct.** One table that governs all
>      six sheets' columns and ordering eliminates the column-drift risk. Any column change is
>      a single edit in `SHEET_SPEC`, not a hunt through sheet-building functions.
>
>   2. **Per-family signed sum for Reasoning sheet — correct.** One column per family (`Trend`,
>      `Momentum`, `Volatility`, `Volume`) with a signed family sum is compact and readable.
>      The full per-vote breakdown (`macd_hist:+0.8×0.20`) would be useful but overly dense for
>      Excel — the signed sum gives the right level of detail. The per-vote breakdown is
>      available in the `reasoning` text and in `top_factors`.
>
>   3. **Derive-from-plans + context for Summary — correct.** Everything computable from plans
>      should be computed. The four non-derivable fields (`calendar`, `preset`, `weights`,
>      `submodule pin`) come from the scan orchestrator, not from any single plan. Threading
>      them via an optional `context` mapping (Q-D) is the right separation.

> **Q-D — input shape + how Summary metadata is threaded (← decides the command signature).**
> The issue signature is `export(plans, path=…, engine=…)`. **`plans` must be `list[TradePlan]`** — it is
> the only object carrying all six sheets' data (`.recommendation` → Recommendations/Levels; `.signal.votes`
> → Reasoning; `.orders` → Orders; `.simulated_fills` → Fills). `list[Recommendation]` alone **cannot**
> populate Orders/Fills/votes. Open: how does the **Summary** run-context reach `export`?
> - **(i) — RECOMMEND:** `export(plans, *, config=ExportConfig(), context=None)` where `context` is an
>   optional metadata mapping/`Data` (`{preset, weights, calendar, submodule_pin}`) produced by `scan`
>   ([#79](https://github.com/prajoria/OpenBB/issues/79)); everything else is **derived from `plans`**. Absent `context` ⇒ Summary shows `"n/a"` for the
>   non-derivable cells (export still succeeds).
> - **(ii):** extend `ExportConfig` with the run-context fields (single handle, but bloats the config model).
> - **(iii):** require the caller to pass a richer `RunContext` `Data` (cleanest typing; one more model + a
>   contract `scan` must emit).
>
> **Confirm:** `plans: list[TradePlan]`, plus the metadata-threading shape (recommend (i): derive-from-plans
> + optional `context`), and whether `path`/`engine` are top-level kwargs (issue signature) **or** pulled from
> `ExportConfig` (model) — recommend **both**: explicit kwargs win, else fall back to `ExportConfig`.
>
> - **Recommendation:** `plans: list[TradePlan]` with option (i) — derive everything possible from `plans`
>   and accept an **optional `context`** mapping from `scan` for the non-derivable Summary cells (missing
>   ⇒ `"n/a"`); accept `path`/`engine` as top-level kwargs that **override** `ExportConfig`, falling back to
>   the config when omitted.
> - **Answer (Review):** ✅ **Approved — `list[TradePlan]` + optional `context` + kwargs override.**
>
>   1. **`plans: list[TradePlan]` — the only viable input shape.** `list[Recommendation]` alone
>      cannot populate Orders, Fills, or the vote breakdown (Reasoning sheet). The full plan
>      carries everything: `.recommendation` → Recommendations/Levels, `.signal.votes` →
>      Reasoning, `.orders` → Orders, `.simulated_fills` → Fills.
>
>   2. **Option (i) for Summary metadata — correct.** Derive what you can from plans, accept
>      the rest as optional `context`. This means `export` works standalone (with `"n/a"` for
>      non-derivable cells) and richer when called from `scan`. Option (ii) bloats `ExportConfig`
>      with run-context fields that don't belong on a config model. Option (iii) adds a new
>      model contract that `scan` must emit — more ceremony for v1.
>
>   3. **Kwargs override `ExportConfig` — correct.** `export(plans, path="custom.xlsx")` should
>      just work without constructing an `ExportConfig`. The explicit kwarg wins; the config is
>      the fallback for defaults.

> **Q-E — number formats + `Decimal` → Excel cells.**
> Cells are IEEE float; money is `Decimal` (L9). Proposal: write `float(Decimal)` as the **cell value**
> (unrounded — keeps the golden stable and the value lossless to display precision) and apply a **display**
> `number_format` so rounding is *presentation only*:
> - currency (`entry/stop/target/limit/risk_per_share/fill price/commission/slippage`) → `'$#,##0.00'`
> - shares/qty → `'#,##0'`
> - score → `'+0.00;-0.00'`; R:R → `'0.0'`
> - **percent fields tension:** `stop_distance_pct` etc. are stored **already in percent units** (e.g.
>   `-3.1` means −3.1%), but Excel's `'0.0%'` format **multiplies by 100**. Two fixes: **(a — RECOMMEND)**
>   keep the model value and use a literal-suffix format `'0.0"%"'` (no multiply → cell value == model
>   field, golden-stable); **(b)** store `value/100` and use `'0.0%'` (cell value ≠ model field). Confirm (a).
> - **Open:** do we ever **pre-round** a stored value (e.g. R:R to 1dp)? Recommend **no** — display-format
>   only; the model value is the source of truth.
>
> - **Recommendation:** write `float(Decimal)` as the **unrounded** cell value with display `number_format`
>   only; for percent fields use the literal-suffix format `'0.0"%"'` (option a — no ×100, so the cell value
>   equals the model field and stays golden-stable); **never pre-round** a stored value.
> - **Answer (Review):** ✅ **Approved — unrounded cell values + display-only formatting.**
>
>   1. **`float(Decimal)` as unrounded cell value — correct.** The cell stores the full-precision
>      value; the `number_format` controls display rounding. This is the Excel-native way:
>      presentation ≠ storage. Pre-rounding would lose precision and break golden stability
>      (a rounding rule change would flip cell values).
>
>   2. **Literal-suffix `'0.0"%"'` for percent fields (option a) — correct.** The model stores
>      `stop_distance_pct = -3.1` (meaning −3.1%). Excel's `'0.0%'` format would multiply by
>      100, displaying −310%. The literal-suffix format avoids the ×100 and keeps
>      `cell value == model field` — essential for golden stability and for any programmatic
>      reader of the `.xlsx`.
>
>   3. **Never pre-round — confirmed.** R:R displayed as `2.0` via `'0.0'` format, but the
>      cell holds `1.9743...`. A downstream formula referencing that cell gets the true value.

> **Q-F — file-writing side-effects inside an `OBBject` command.**
> `export` is unusual for OpenBB: it has a **write side-effect** and returns the **path**.
> - **Return:** `OBBject` whose `results` is the **`str` path written** (bare `OBBject`, L8). Confirm
>   results-is-path (vs. a small `{path, sheets, rows}` summary dict).
> - **Default dir:** `Analysis/exports/` created with `mkdir(parents=True, exist_ok=True)`. **Open:** resolve
>   `Analysis/exports/` relative to **CWD**, a configured **base dir**, or the **repo root**? CWD is fragile
>   for an installed package; recommend a resolved base (env/`ExportConfig` override, default repo-relative).
> - **Overwrite:** same as-of ⇒ same filename. Recommend **overwrite silently** (deterministic, re-runnable
>   artifact); ASK if instead we should version/suffix or refuse.
> - **Filename date = run as-of**, never `datetime.now()` (else non-deterministic filename + golden drift, L4/L6).
>
> - **Recommendation:** return the **`str` path written** as `OBBject.results`; default-write under a
>   **resolved base dir** (env / `ExportConfig` override, default repo-relative `Analysis/exports/`) created
>   with `mkdir(parents=True, exist_ok=True)`; **overwrite silently** on a same-as-of filename; always date
>   the filename by the run **as-of**, never wall-clock.
> - **Answer (Review):** ✅ **Approved — follow recommendation.**
>
>   1. **Return `str` path as `OBBject.results` — simple and sufficient.** A summary dict
>      (`{path, sheets, rows}`) is tempting but unnecessary: the caller already knows the
>      sheets (L2 fixed set) and can count rows from the input plans. The path is the only
>      new information the export produces.
>
>   2. **Resolved base dir (not CWD) — correct.** CWD is fragile for an installed package.
>      An env/config-overridable base with a sane repo-relative default (`Analysis/exports/`)
>      works for both interactive use (from repo root) and deployed use (configured path).
>
>   3. **Overwrite silently — correct for a deterministic artifact.** Same inputs + same as-of
>      = same file. Versioning/suffixing would accumulate stale files. The determinism guarantee
>      (L6) means the overwritten file is identical to the previous one for the same inputs.
>
>   4. **Filename date = run as-of, never wall-clock — essential.** `datetime.now()` in the
>      filename would break determinism and make golden testing impossible. The `as_of` date
>      is the only meaningful timestamp for the analysis.

---

## 1. Module layout (new + changed)

```
openbb_platform/extensions/techtrade/openbb_techtrade/reporting/
├── __init__.py          # EXISTING — empty package (docstring only); no change
├── excel_export.py      # NEW — the workbook builder (pure; pandas + openpyxl only):
│                        #   export(plans, *, config=ExportConfig(), context=None) -> str (path)
│                        #   SHEET_SPEC  : sheet -> ordered (column, field-accessor) — single source of truth (Q-C)
│                        #   FORMAT_SPEC : engine-agnostic conditional-format rule descriptors (Q-B)
│                        #   _build_<sheet>_df(plans) -> DataFrame  (6 builders)
│                        #   _apply_openpyxl(ws, spec) / _apply_xlsxwriter(ws, spec)  (two thin appliers)
│                        #   _write_title_and_disclaimer(ws)        (Recommendations only, L3)
└── export_router.py     # NEW — sub-router (auto-wired by techtrade_router._include_subrouters, L8):
                         #   export(plans, path=None, engine="openpyxl") -> OBBject(results=<path str>)

openbb_platform/extensions/techtrade/tests/golden/
├── test_excel_export.py            # NEW — write -> read back -> structural/value golden (Q-A opt i):
│                                   #   sheets+order, header+cells, number formats, CF rule descriptors,
│                                   #   disclaimer present; both engines (formatting per-engine, Q-B)
└── fixtures/
    └── excel_export_recs.json      # NEW — committed STRUCTURAL snapshot golden (to_jsonable, #71 harness)
    └── techtrade_sample.xlsx       # OPTIONAL — committed human-openable artifact, NON-asserted (Q-A)
```

**Module-boundary rules**
- `excel_export.py` is **pure + offline**: imports only `models`, `pandas`, `openpyxl` (and `xlsxwriter`
  **lazily**, only when `engine="xlsxwriter"`). **No** `obb.*`, no network, no `engine/`/`confluence`/`rules`
  imports — it consumes already-built `TradePlan`s and emits a file. Fully golden-testable without
  `openbb.build()`.
- **One mapping table** (`SHEET_SPEC`) decides every sheet's columns + order; nothing else encodes column
  layout (kills the column-drift risk, mirroring `selector.SOURCE_TABLE` in [#73](https://github.com/prajoria/OpenBB/issues/73)).
- **One rule table** (`FORMAT_SPEC`) decides conditional formatting; the two engine appliers render it — no
  per-engine rule logic duplicated (Q-B).
- `export_router.py` is thin: validate/normalize `plans`, call `excel_export.export`, wrap the returned path
  in a **bare `OBBject`** (no parametrized model) so `package_builder.build_func_returns` renders an
  importable annotation — the established `screener_router`/`plan_router` pattern.
- No cycles: `models ← excel_export ← export_router`. `models` stays a leaf.

---

## 2. Workbook structure (§14.3)

One row per recommendation, **sorted segment → conviction** (L6). The six sheets and their proposed
column → field mappings (Q-C):

### 2.1 `Recommendations` — the headline call (title block + disclaimer, L3)

| Column | Source (`TradePlan` `p`) | Format (Q-E) |
|---|---|---|
| Segment | `p.recommendation.segment` | text |
| Symbol | `.symbol` | text |
| Action | `.action` (`BUY`/`SELL_SHORT`/`HOLD/FLAT`) | **CF fill** (§3) |
| Conviction | `.conviction` (`High`/`Medium`/`Low`) | **CF shade** (§3) |
| Score | `.score` | `'+0.00;-0.00'` + CF color scale |
| Entry | `.entry_price` | `'$#,##0.00'` |
| Stop | `.stop_price` | `'$#,##0.00'` |
| Target | `.target_price` | `'$#,##0.00'` |
| Stop % | `.stop_distance_pct` | `'0.0"%"'` + CF color scale |
| R:R | `.risk_reward` | `'0.0'` + **CF data-bar/scale** (§3) |
| Shares | `.position_size` | `'#,##0'` |
| Reasoning (short) | `.reasoning` (truncated — **Q-C** rule) | text |

### 2.2 `Levels` — price/stop/target detail & gaps

`Symbol←.symbol`, `Entry←.entry_price`, `Stop←.stop_price`, `Target←.target_price`,
`Stop Distance %←.stop_distance_pct`, `Target Distance %←.target_distance_pct`, `ATR(14)←.atr`,
`Risk/Share←.risk_per_share`, `Risk %←.risk_pct_of_notional`, `Time Stop (bars)←.time_stop_bars`.

### 2.3 `Reasoning` — full narrative & attribution

`Symbol←.symbol`, `Reasoning (full)←.reasoning`, `Top Factors←.top_factors` (joined),
`Caveats←.caveats`, **+ per-family vote breakdown** `Trend / Momentum / Volatility / Volume` grouped from
**`p.signal.votes`** (Q-C — this is why input is `list[TradePlan]`, Q-D).

### 2.4 `Orders` — order list per plan (`p.orders`, one row per `Order`)

`Symbol←.symbol`, `Side←.side`, `Qty←.quantity`, `Type←.order_type`, `Limit←.limit_price`,
`Stop←.stop_price`, `TIF←.tif`, `Intent←.intent`.

### 2.5 `Fills` — paper-simulated fills (`p.simulated_fills`, one row per `Fill`)

`Symbol←.symbol`, `Side←.side`, `Qty←.quantity`, `Fill Price←.price`, `Commission←.commission`,
`Slippage←.slippage`, `Timestamp←.timestamp`.

> **The lone in-cell timestamp (determinism, L6):** `Fill.timestamp` is a tz-aware datetime — the **only**
> timestamp written to a cell. It is **deterministic** (the *t+1* session-close localization fixed by
> [#78](https://github.com/prajoria/OpenBB/issues/78) Q-F), **not** wall-clock, so it does **not** break byte/structure-stability. The export must write
> that fill timestamp verbatim and never stamp `datetime.now()` anywhere.

### 2.6 `Summary` — run metadata & roll-ups (Q-C / Q-D)

| Cell | Provenance |
|---|---|
| As-of date | derived: `plans[*].as_of` (uniform) |
| Calendar | **context** (`XNYS` default) |
| Preset | **context** ([#79](https://github.com/prajoria/OpenBB/issues/79)/[#75](https://github.com/prajoria/OpenBB/issues/75) preset) |
| Weights | **context** ([#74](https://github.com/prajoria/OpenBB/issues/74) confluence weights) |
| Segment counts | derived: count by `segment` |
| # BUY / SELL / FLAT | derived: count by `recommendation.action` |
| Avg R:R | derived: mean `risk_reward` over actionable rows |
| Submodule pin | **context** (`pandas-ta-classic` commit) |
| Validation coverage | derived: # plans with `.validation` populated ([#82](https://github.com/prajoria/OpenBB/issues/82)) |

### 2.7 Title block + disclaimer (Recommendations only, L3) — ASCII sketch (§14.3)

```
OpenBB TechTrade — Top-Mover Recommendations — 2026-06-09   [Research/paper output — not advice]
┌────────────────┬────────┬────────┬──────────┬───────┬───────┬───────┬────────┬────────┬─────┬────────┬───────────────────────────┐
│ Segment        │ Symbol │ Action │Conviction│ Score │ Entry │ Stop  │ Target │ Stop % │ R:R │ Shares │ Reasoning                 │
├────────────────┼────────┼────────┼──────────┼───────┼───────┼───────┼────────┼────────┼─────┼────────┼───────────────────────────┤
│ Info Technology│ NVDA   │ BUY    │ High     │ +0.72 │ 121.40│ 117.6 │ 129.0  │ -3.1%  │ 2.0 │ 41     │ Trend+ (MACD,ADX28), RSI62…│
└────────────────┴────────┴────────┴──────────┴───────┴───────┴───────┴────────┴────────┴─────┴────────┴───────────────────────────┘
```

The title block occupies the first ~2 rows; the table header is **frozen** and carries an **auto-filter**
(§3). The disclaimer text is a required string in the title block (L3) — asserted by the golden (§5).

---

## 3. Conditional formatting (§14.3, `conditional_formatting=True` default, L5)

Rules are declared **once** in `FORMAT_SPEC` and rendered by the engine appliers (Q-B / B1):

| Target | Rule | openpyxl | xlsxwriter |
|---|---|---|---|
| `Action` | **discrete fill** — green `BUY`, red `SELL_SHORT`, grey `HOLD/FLAT` | `CellIsRule`/`FormulaRule` + `PatternFill` | `conditional_format(type='text'/'cell', format=…)` |
| `Conviction` | **shade** High>Medium>Low | `CellIsRule` × 3 fills | `conditional_format` × 3 |
| `R:R` | **data-bar / 3-color scale** green ≥ 2.0, amber 1.0–2.0, red < 1.0 | `DataBarRule` / `ColorScaleRule` | `conditional_format(type='data_bar'/'3_color_scale')` |
| `Stop %` | **color scale** (tighter = better) | `ColorScaleRule` | `3_color_scale` |
| `Score` | **color scale** centered at 0 | `ColorScaleRule` | `3_color_scale` |

Non-CF presentation (always on, even when `conditional_formatting=False`): **frozen header row**
(`ws.freeze_panes`), **auto-filter** on Recommendations (`ws.auto_filter.ref`), **currency/percent number
formats** (Q-E), **column auto-width** (computed from max cell length per column — deterministic, content-derived).

> **The openpyxl-vs-xlsxwriter open question (Q-B) restated:** openpyxl can express every rule above, so
> **B1** ships full formatting on the **default** engine and keeps xlsxwriter as the "richer/charts" option.
> The golden (§5) locks the **rule descriptors** (target range + kind + thresholds) read back via openpyxl;
> xlsxwriter formatting is verified by a **lighter per-engine smoke** because openpyxl may not round-trip
> xlsxwriter's CF identically. **Decision needed:** xlsxwriter formatting parity in-scope for v1, or
> openpyxl-only formatting golden + best-effort xlsxwriter?

---

## 4. `export` command (`obb.techtrade.export`)

```python
# reporting/export_router.py  (bare OBBject return per the static-package-builder rule, L8)
@router.command(methods=["POST"])
def export(
    plans: list,                       # list[TradePlan] (Q-D) — carries recommendation/orders/fills/votes
    path: str | None = None,           # default Analysis/exports/techtrade_<as_of>.xlsx (L4, Q-F)
    engine: str = "openpyxl",          # {openpyxl, xlsxwriter} (L1) — xlsxwriter imported lazily
) -> OBBject:
    """Write the 6-sheet recommendation workbook (§14.3); results -> the written file path (str)."""
    from openbb_techtrade.reporting.excel_export import export as _export
    from openbb_techtrade.models import ExportConfig
    cfg = ExportConfig(path=path, engine=engine)     # explicit kwargs win, else ExportConfig (Q-D)
    return OBBject(results=_export(plans, config=cfg))
```

| Aspect | Behaviour | Ref |
|---|---|---|
| Input | `plans: list[TradePlan]` (single ⇒ length-1 list) | Q-D |
| `results` | the **`str` path written** | Q-F |
| Default path | `Analysis/exports/techtrade_<as_of>.xlsx`, dir auto-created | L4, Q-F |
| Engine | `openpyxl` default; `xlsxwriter` optional (lazy import) | L1 |
| Config | `path`/`engine` kwargs override `ExportConfig`; `include_sheets`/`conditional_formatting` from config | L2/L5, Q-D |
| Side-effect | overwrite same-as-of file silently (recommend) | Q-F |

> Like `screener_router`/`plan_router`, `export` returns a **bare `OBBject`**; the `str`-path payload is
> documented in the docstring (PRD §9.2 round-trips). The `Recommendation`/`ExportConfig` `Data` models
> already round-trip Python/REST/CLI/MCP, so the **same content is available without opening Excel** (§14.3).

---

## 5. Determinism & golden test (§14.3, L6)

### 5.1 Determinism guarantees
- **Sorted rows** segment → conviction (stable secondary key on symbol to break ties), **fixed column
  order** from `SHEET_SPEC` — never reordered.
- **No wall-clock in cells:** filename date and any "as-of" cell = the run's `as_of`; the only datetime cell
  is the deterministic `Fill.timestamp` (§2.5). `export` never calls `datetime.now()`.
- **Pure function:** identical `plans` (+ `context`) ⇒ identical logical workbook. `float(Decimal)` cell
  values are not pre-rounded (Q-E) → no rounding drift.
- **Auto-width is content-derived** (max cell length), not environment-derived → stable.

### 5.2 `tests/golden/test_excel_export.py` — structural/value golden (Q-A opt i)

```python
# write to a tmp path, read it back, normalize, compare to the committed JSON snapshot.
def test_export_golden(tmp_path):
    p = export(SAMPLE_PLANS, path=str(tmp_path / "wb.xlsx"), engine="openpyxl")
    wb = load_workbook(p)
    snapshot = {
        "sheets": wb.sheetnames,                                  # order + set (L2)
        "recommendations": _cells(wb["Recommendations"]),         # header + values, segment→conviction sorted
        "levels":   _cells(wb["Levels"]),  "reasoning": _cells(wb["Reasoning"]),
        "orders":   _cells(wb["Orders"]),  "fills":     _cells(wb["Fills"]),
        "summary":  _cells(wb["Summary"]),
        "number_formats": _formats(wb["Recommendations"]),        # currency/percent (Q-E)
        "cond_formats":   _cf_rules(wb["Recommendations"]),       # Action/R:R/Score descriptors (§3)
        "disclaimer_present": _has_text(wb["Recommendations"], "not investment advice"),   # L3
    }
    assert_matches_golden("excel_export_recs", snapshot, fixture_dir=FIXTURES)   # #71 harness, regen via env
```

| Assertion | Locks |
|---|---|
| `wb.sheetnames == [Recommendations, Levels, Reasoning, Orders, Fills, Summary]` | L2 sheet set + order |
| per-sheet header + cell values, rows sorted segment → conviction | §2 mapping (Q-C) + L6 sort |
| number formats on currency/percent/score columns | Q-E |
| CF rule descriptors present on Action/Conviction/R:R/Stop %/Score | §3 (engine-agnostic, Q-B) |
| **disclaimer string present on Recommendations** | **L3 / Q9 acceptance** |
| `float(Decimal)` cell values match the model (within tol) | L9 / Q-E |
| (per-engine) `engine="xlsxwriter"` writes the 6 sheets + disclaimer | L1 (formatting parity per Q-B) |

> **Why structure over bytes (Q-A):** the golden asserts *what a reader sees* — sheets, values, formats,
> disclaimer — not the zip bytes, so it survives openpyxl version bumps and covers **both** engines from one
> harness. A committed `techtrade_sample.xlsx` (optional) is a **non-asserted** human artifact only.

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/golden/test_excel_export.py -m "not integration" -v
```

---

## Acceptance mapping (#81)

| Acceptance criterion (issue) | Satisfied by | Open dependency |
|---|---|---|
| `reporting/excel_export.py` via `pd.ExcelWriter(engine="openpyxl")`; xlsxwriter optional extra | §1 layout + §4; L1/L7 | Q-B (formatting parity) |
| 6 sheets: Recommendations, Levels, Reasoning, Orders, Fills, Summary (§14.3) | §2 (6-sheet mappings); L2 | Q-C (column/vote/Summary mapping) |
| Conditional formatting: color-coded Action, R:R color scale, conviction | §3 (`FORMAT_SPEC` + appliers); L5 | Q-B (openpyxl vs xlsxwriter) |
| Per-workbook disclaimer on Recommendations ("Research/paper — not advice") | §2.7 title block; **L3** | — (locked, Q9) |
| `export(plans, path=…, engine=…)` → file path; default `Analysis/exports/techtrade_<date>.xlsx` | §4 command; L4 | Q-D (input shape), Q-F (path/side-effects) |
| Golden `.xlsx` test (byte/structure-stable) | §5 structural/value golden via [#71](https://github.com/prajoria/OpenBB/issues/71) harness | **Q-A** (structure vs byte) |
| `obb.techtrade.export(...)` writes the 6-sheet workbook to default/given path | §4 (`export_router`, auto-wired); L8 | Q-F |
| formatting + disclaimer present; output matches golden | §3 + §5 (disclaimer + CF asserted) | Q-A, Q-B |
| reflects Q9 engine/disclaimer decision | L1 (openpyxl default + xlsxwriter optional) + L3 (disclaimer required) | — (Q9 RESOLVED, do not reopen) |
| Depends on [#80](https://github.com/prajoria/OpenBB/issues/80) (Recommendation builder) | §2 consumes `TradePlan.recommendation` (built by [#80](https://github.com/prajoria/OpenBB/issues/80)); plans produced by `scan` [#79](https://github.com/prajoria/OpenBB/issues/79) | Q-D (context threading) |

> **Net new risks surfaced:** (1) **Q-A** — a literal byte-identical `.xlsx` golden is infeasible across
> engines and openpyxl versions; the doc recommends a **structure/value** golden via the existing [#71](https://github.com/prajoria/OpenBB/issues/71)
> harness — confirm before coding the test. (2) **Q-B** — full conditional formatting on the **default**
> openpyxl engine is achievable but verbose; decide whether xlsxwriter must reach formatting **parity** in
> v1. (3) **Q-D** — `export` must take `list[TradePlan]` (not `list[Recommendation]`) and needs a
> run-`context` for the Summary roll-ups; confirm the threading shape.
