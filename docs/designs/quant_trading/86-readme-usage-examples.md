# 86 — README + Usage Docs + Worked Examples

**GitHub:** [#86](https://github.com/prajoria/OpenBB/issues/86) · **Phase:** P8 · **Sprint:** 7 · **Size:** M
**Depends on:** [#65](https://github.com/prajoria/OpenBB/issues/65) (scaffold + the current README) plus the full P3-P6 pipeline ([#73](https://github.com/prajoria/OpenBB/issues/73) selector, [#74](https://github.com/prajoria/OpenBB/issues/74) confluence, [#75](https://github.com/prajoria/OpenBB/issues/75) signals, [#76](https://github.com/prajoria/OpenBB/issues/76) sizing, [#77](https://github.com/prajoria/OpenBB/issues/77) orders, [#78](https://github.com/prajoria/OpenBB/issues/78) fills, [#79](https://github.com/prajoria/OpenBB/issues/79) scan, [#80](https://github.com/prajoria/OpenBB/issues/80) recommendation, [#81](https://github.com/prajoria/OpenBB/issues/81) export, [#82](https://github.com/prajoria/OpenBB/issues/82) validate)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §9 (command surface), §17 (testing & determinism), §18 (delivery roadmap)
**Scope:** Replace the **scaffold-era** `openbb_platform/extensions/techtrade/README.md` (last updated at #65, still says *"Status: scaffold"*) with a release-ready document for users of the now-complete pipeline. Add a short, runnable **worked example** for every public command (`obb.techtrade.{segments, movers, signals, plan, scan, orders, simulate, export, validate, about}`), document the **soft-dep install matrix** (`xlsxwriter`, `validation`), and add a small `examples/` directory with end-to-end scripts the README links to.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

This is the **documentation pass** that turns techtrade from "implementation-complete on a feature
branch" into something a new user can pick up, install, and run by reading one page. The current
README is a scaffold artifact: it advertises a `segments / movers / signals / plan / scan / orders /
simulate / export / validate / tune` surface as **"Status: scaffold (issue #65)"**, but the surface
is in fact live (every command above except `tune` is implemented and tested by #66 through #82).
A first-time reader who follows the README today sees a status line that contradicts the code; this
issue closes that gap.

The deliverable is three documents and one directory:

1. The **README rewrite** — what techtrade is, what each command does, how to install with or
   without the soft-deps, one minimal end-to-end snippet, and a pointer to `examples/`. Audience:
   a finance-literate user who knows OpenBB and wants to evaluate techtrade in fifteen minutes.
2. A **command reference section** in the README — one short example block per command, with the
   exact arguments and the shape of the returned `OBBject.results`. Audience: a user who has
   installed techtrade and is looking up "how do I call `export`?" without reading the source.
3. A small **`examples/`** directory — a couple of complete, runnable Python scripts that chain
   the commands end-to-end (the "scan → recommend → export" headline and a "validate one plan"
   companion). Audience: a user who wants a copy-paste starting point.
4. (Optional, see Q-E) A short **`docs/quickstart.md`** under the extension that the README links
   to for the longer walkthrough, keeping the README itself scannable.

The defining engineering constraint is **executability**. Every snippet in the README and every
script in `examples/` must run as-is against the current code (no `# TODO: not implemented yet`
asides, no fictitious arguments). The headline open question (Q-A) is how to *enforce* that —
unit-test the README itself, copy-paste lift snippets from the existing pytest fixtures, or rely
on review discipline. The pipeline is now complex enough (10 commands, two soft-deps, two
optional engines for `export`) that drift will start silently within weeks of a rewrite unless the
verification mechanism is explicit.

This is a **docs-only issue** — no new Python code on the engine side; the only Python that lands
is the `examples/*.py` scripts and (if Q-A picks the executable-test option) a tiny
`tests/unit/test_readme_examples.py`.

---

## 0. Key decisions (locked) + open questions

### 0.1 Locked (from PRD §9 / §17 / §18 + the shipped surface)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | The README is **the** entry point | `openbb_platform/extensions/techtrade/README.md` (replaces the #65 scaffold doc in place) | Search engines, PyPI, GitHub all surface this file; everything else links from it |
| L2 | Command set documented | The current live set: `about`, `segments`, `movers`, `signals`, `plan`, `scan`, `orders`, `simulate`, `export`, `validate` | `tune` ([#83](https://github.com/prajoria/OpenBB/issues/83), "extra" tier, not implemented) is mentioned as **roadmap**, not documented as live; `tune` is removed from the scaffold-era surface line until it lands |
| L3 | Soft-deps documented | **Two**: `[xlsxwriter]` for the alternative Excel engine ([#81](https://github.com/prajoria/OpenBB/issues/81)), `[validation]` for `openbb-backtest` ([#82](https://github.com/prajoria/OpenBB/issues/82)). Both shown with their install commands; both show graceful-degradation behaviour | Mirrors the actual `[tool.poetry.extras]` block; no hypothetical extras (`[tuneta]`, `[agent]`, etc.) are mentioned as installable until they exist |
| L4 | Tone | **Direct, finance-literate, US-English, no marketing**. Mirrors the existing PRD prose and the established design-doc convention (the same voice you are reading now) | No "powerful", "blazing-fast", "AI-powered" copy; one terse paragraph per concept; runnable code blocks are the proof |
| L5 | Code-block convention | **PowerShell + bash variants** for install / test commands (`.venv_win\Scripts\python.exe` is the canonical Windows interpreter per `CLAUDE.md`; bash form is given alongside for non-Windows); Python snippets use **`from openbb import obb`** unless they're testing an engine seam | A reader on either platform finds a runnable line; the engine-internal calls (e.g. `build_recommendation`) appear under "advanced / testing" only |
| L6 | Determinism / disclaimer | A short **"Outputs are paper / research — not investment advice"** banner near the top of the README, mirroring the locked Excel-export disclaimer (PRD §20 Q9 / [#81](https://github.com/prajoria/OpenBB/issues/81) L3) | Compliance posture is consistent across surfaces (Excel sheet + README + future agent prompts); one-line, never suppressible |
| L7 | Reference style | **One example per command**, max ~6 lines, showing the typical args and the shape of `OBBject.results` ("returns a `list[TradePlan]`") | The exhaustive parameter table lives in the command docstring (already authored and rendered into the static package surface); the README does not duplicate it |
| L8 | Worked-example placement | Live runnable scripts under **`openbb_platform/extensions/techtrade/examples/`** (sibling of `tests/` and `openbb_techtrade/`); the README links to them | Scripts are real Python files (not fenced blocks), so they survive a lint pass and can be smoke-imported in CI; one less surface to drift |
| L9 | The pipeline picture | An ASCII diagram **once** in the README ("segment → movers → panel → signal → rule → orders → fills → recommendation → export / validate"), reused (not redrawn) wherever else the pipeline is described | Anchors the mental model; matches the PRD §9 chain so a reader can cross-reference |

### 0.2 Open questions (please review / brainstorm)

> **Q-A — How do we *prevent* the README snippets from drifting from the code? (THE central choice.)**
> Docs that include code snippets rot the moment the code changes. With ten commands, two
> soft-deps, and an active dev branch, the README will go stale within a month if there is no
> mechanism to catch it. Four options, from cheapest to most defensible:
>
> | Opt | Mechanism | Pros | Cons |
> |---|---|---|---|
> | **A1** — review discipline only | Author the README once; trust PR review to keep it in sync | Zero new code; zero CI cost | Empirically fails on every project with > 5 contributors; the scaffold README is itself the proof |
> | **A2** — link, don't quote | Every command's example in the README is a hyperlink to the **already-passing pytest fixture** that exercises that command | Snippets are *guaranteed* to compile + match real signatures (because they live in pytest); README becomes a curated index of test fixtures | Worse reading experience — a user wanting to *see* the example has to click out; fixtures are written for test concision, not narrative clarity |
> | **A3 — RECOMMEND** — runnable `examples/` + smoke test | Write **real `examples/<name>.py` scripts** that the README links to; a `tests/unit/test_examples_smoke.py` imports each script and asserts the `main()` returns the expected shape (no live API — uses the same offline-fake seams the unit suite uses) | Snippets stay readable + are CI-checked; reuses the existing offline-fake convention (`_signal_fetcher` / `_level_fetcher` etc.); zero new test infrastructure | Slight indirection — README points at `examples/scan_to_excel.py` instead of inlining a 6-line block. Mitigation: the README still inlines a 6-line "headline" snippet, plus the link to the deep example |
> | A4 | doctest blocks in the README itself | Embeds snippets directly in the README; `pytest --doctest-glob='*.md'` runs them | Doctest semantics are awkward for OBBject outputs (no canonical repr); breaks on whitespace; OpenBB's pytest config does not currently enable doctest |
>
> **Recommend A3** — runnable `examples/` + a small unit test that imports each script and exercises
> its `main()` against the offline fakes. The README inlines short snippets for the **headline** flow
> (scan → recommend → export) and links to the longer examples for the rest. Tests live in
> `tests/unit/test_examples_smoke.py` and reuse the same `_signal_fetcher` / `_level_fetcher` / bar
> fakes already in `tests/unit/test_plan.py` and `tests/unit/test_scan.py`.
>
> - **Answer (Review):** ✅ **Approved — A3 (runnable `examples/` + offline smoke test).**
>
>   1. **A1 is correctly rejected — the scaffold README is the failure proof.** This doc exists
>      precisely because review-only discipline let the #65 README drift to a status line that
>      contradicts the shipped surface. Re-adopting A1 would reproduce the exact failure we are
>      paying down. Non-negotiable.
>
>   2. **A3 over A2 — readability + verification, not one or the other.** A2 (link to pytest
>      fixtures) guarantees correctness but ships a worse reading experience: fixtures are written
>      for test concision, not narrative. A3 keeps the example *readable as documentation* while
>      still CI-checking it, and reuses the existing `_signal_fetcher` / `_level_fetcher` offline
>      seams — zero new test infrastructure. A4 (doctest) is rightly rejected: OBBject has no
>      canonical repr and OpenBB's pytest config does not enable `--doctest-glob`.
>
>   3. **Refinement (the one real gap to close):** the **inline 6-line headline snippet** in the
>      Quickstart (§2.2) is *not* itself one of the `examples/*.py` files, so it sits outside the
>      smoke test and can drift independently — the same class of bug A3 is meant to kill. Make
>      the inline snippet a verbatim slice of `examples/scan_to_excel.py::main()` (or generate it
>      from that file) so the single inline block is covered transitively. Without this, A3 guards
>      the linked examples but leaves the most-read snippet unguarded.
>
>   4. **Shape-only assertions are the right scope.** Locking content (golden snapshots) here
>      would make the smoke brittle and duplicate the engine's `tests/golden/` locks. Asserting
>      `list[TradePlan]` / `str`-path-exists is enough to catch signature and return-shape drift,
>      which is what actually rots a README.

> **Q-B — Should the README cover `tune` / `narrator` / `MCP` ([#83](https://github.com/prajoria/OpenBB/issues/83) / [#84](https://github.com/prajoria/OpenBB/issues/84) / [#85](https://github.com/prajoria/OpenBB/issues/85)) as "Roadmap" or omit them entirely?**
> All three are "extra-tier", not implemented, but already referenced by name in the scaffold
> README's surface line (`obb.techtrade.… / tune`). Two options:
>
> | Opt | What goes in | Trade-off |
> |---|---|---|
> | **B1 — RECOMMEND** | A short **"Roadmap"** section near the bottom that lists the four future extras (`tune` #83, narrator #84, MCP #85, streaming/intraday #87) with one-line summaries and the issue links | Honest about what is and isn't shipped; sets expectations; documents the soft-dep extras (`[tuneta]`, `[agent]`) as planned, not installable |
> | B2 | Omit entirely, document only the live surface | Cleaner README; some users may not realise more is coming and re-implement it externally |
>
> **Recommend B1.** A roadmap section is one paragraph and a 4-row list; the cost is negligible and
> the benefit (a user who is evaluating techtrade for a longer horizon can see the plan) is real.
> The Roadmap section explicitly marks each item *"not yet implemented; tracking issue [#…]"* so it
> cannot be misread as a feature claim.
>
> - **Answer (Review):** ✅ **Approved — B1 (Roadmap section: #83 / #84 / #85 / #87).**
>
>   1. **B1 beats B2 because the scaffold already leaked the names.** `tune` is named in the
>      current README's surface line; silently deleting it (B2) leaves users who saw the old
>      surface, or who read issue comments, wondering whether it regressed. A one-paragraph
>      Roadmap converts that ambiguity into an honest "planned, not shipped."
>
>   2. **Guardrail on presentation (must-do, not optional):** render roadmap items as prose with
>      issue links — **never** as runnable-looking call syntax (e.g. avoid `obb.techtrade.tune(...)`
>      in a python fence). A copy-pasteable-looking line for an unimplemented command is exactly
>      the "fictitious argument" failure §0 bans. Each row should read `tune (#83) — not yet
>      implemented` in plain text.
>
>   3. **Keep it bottom-of-page and decoupled from the live Commands matrix (§3).** The Roadmap
>      must never share a table or heading level with the live surface, or a skimming reader will
>      conflate the two. Bottom placement (per §2's skeleton) is correct.
>
>   4. **Cross-check the issue numbers before merge.** B1 lists #83 (tune) / #84 (narrator) /
>      #85 (MCP) / #87 (streaming/intraday). Confirm #87 is the streaming issue and that no extra
>      tier item is missing, so the Roadmap is exhaustive rather than a partial teaser.

> **Q-C — Where does the soft-dep install matrix live?**
> Two install commands matter to a real user:
> `pip install openbb-techtrade` (core, ships today)
> `pip install 'openbb-techtrade[validation]'` (also installs `openbb-backtest`, lights up
> `obb.techtrade.validate`)
> `pip install 'openbb-techtrade[xlsxwriter]'` (installs `xlsxwriter`, enables `engine="xlsxwriter"`
> on `obb.techtrade.export`)
>
> | Opt | Where | Trade-off |
> |---|---|---|
> | **C1 — RECOMMEND** | An **"Install"** section near the top with a small 3-row table mapping extra → what it enables → which command needs it | Visible upfront; users hit it before they hit the first command snippet that would fail without it |
> | C2 | Per-command — each example block notes the soft-dep when relevant | Local to where it bites; but the user only finds it after their first failed call |
>
> **Recommend C1 + a one-line cross-reference at each affected example.** The table is the
> authoritative install matrix; each `export` / `validate` example carries a parenthetical
> *"(requires `[xlsxwriter]`)"* / *"(requires `[validation]`)"* nudge.
>
> - **Answer (Review):** ✅ **Approved — C1 (upfront install matrix) + per-example nudges.**
>
>   1. **Upfront table prevents the first-failed-call experience.** C2 (per-command only) means a
>      user learns `[validation]` exists *after* `validate` raises `TechtradeDependencyError`. The
>      install matrix at the top lets them install the right extra before they hit the wall. The
>      parenthetical nudges (C1's second half) keep the reminder local where it bites — this is the
>      both-and that C1 already specifies, and it's the correct call.
>
>   2. **Make the matrix mirror `[tool.poetry.extras]` exactly, including the core row.** The
>      table should be authoritative against `pyproject.toml` (per L3): one row for the bare
>      `pip install openbb-techtrade` and one each for `[xlsxwriter]` and `[validation]`. Do not
>      list any extra (`[tuneta]`, `[agent]`) that isn't installable today — those belong in the
>      Roadmap (Q-B), not the install matrix, or the matrix becomes a list of broken commands.
>
>   3. **Tie the nudge to the degradation message.** The parenthetical in each example should use
>      the *same* extra name the runtime error prints (`pip install 'openbb-techtrade[validation]'`),
>      so a user who hits the error and a user who reads the docs see identical, copy-pasteable
>      install strings. One source of truth for the install command across README + runtime.

> **Q-D — Do we keep the existing `## Vendored indicator engine` and `## Testing & determinism`
> sections, edit them in place, or split them off?**
> Both sections are correct as written (the submodule pin, the golden-file harness, the offline
> test discipline are all still the live conventions). The question is whether they belong in the
> user-facing README or in a separate `CONTRIBUTING.md` / `docs/development.md`.
>
> | Opt | Layout | Trade-off |
> |---|---|---|
> | **D1 — RECOMMEND** | Keep both in the README, **demoted** from top-level to *"For Contributors"* near the bottom | One page = one source of truth; tests / submodule discipline stays discoverable for contributors without an extra doc to lose |
> | D2 | Move both to a new `openbb_platform/extensions/techtrade/CONTRIBUTING.md` | Cleaner user-facing README; one more file to maintain and link |
>
> **Recommend D1.** The README is already short (60 lines) and these sections are 30 of them;
> moving them out for the sake of cleanliness is over-engineering. Demoting them under
> *"For Contributors"* signals the audience switch.
>
> - **Answer (Review):** ✅ **Approved — D1 (keep contributor content, demoted to *For Contributors*).**
>
>   1. **One page = one source of truth — correct for the current size.** Splitting to a separate
>      `CONTRIBUTING.md` (D2) for 30 lines is premature; it adds a file to lose and a link to rot
>      for no reading-experience gain. The submodule pin, golden harness, and offline-test
>      discipline stay discoverable next to the code they govern.
>
>   2. **The audience-switch heading is doing real work — make it unambiguous.** A `## For
>      Contributors` (or `## Development`) heading with a one-line preface ("the sections below are
>      for people changing techtrade, not using it") prevents a user from mistaking the submodule
>      fetch / golden-file discipline for required user setup.
>
>   3. **Consistency check with Q-E:** D1's "don't split yet" and E1's "revisit at ~200 lines"
>      share the same threshold, and §2's skeleton totals ~180 lines. That's internally
>      consistent — but it means the README is *near* the split line on day one. Flag the ~200-line
>      trigger in a comment so the next editor knows D2 + E2 become live together once narrator/MCP
>      land.

> **Q-E — Do we need a separate `docs/quickstart.md` inside the extension?**
> Some OpenBB extensions have a `docs/` directory (e.g. the vendored `pandas-ta-classic` ships
> `docs/quickstart.md` and `docs/tutorials.md`); most do not. The current techtrade extension has
> no `docs/` directory — only `README.md`.
>
> | Opt | Layout | Trade-off |
> |---|---|---|
> | **E1 — RECOMMEND** | **No separate doc.** README + `examples/*.py` is sufficient for the v1 surface. Revisit when narrator ([#84](https://github.com/prajoria/OpenBB/issues/84)) / MCP ([#85](https://github.com/prajoria/OpenBB/issues/85)) land and the surface area outgrows one page | Lowest surface, fewest things to keep in sync, no new directory |
> | E2 | Add `openbb_platform/extensions/techtrade/docs/quickstart.md` with the longer narrative; README points to it | Mirrors the convention some other extensions use; but the README is already short enough to carry the full quickstart inline |
>
> **Recommend E1.** Keep everything in the README until it crosses ~200 lines; split then.
>
> - **Answer (Review):** ✅ **Approved — E1 (no separate `docs/quickstart.md` for v1).**
>
>   1. **README + `examples/` is the right surface for a 10-command extension.** A separate
>      `docs/quickstart.md` (E2) duplicates the headline flow that already lives in the Quickstart
>      section and the `examples/*.py` scripts, creating a third place to drift. Fewer surfaces is
>      strictly better while everything fits on one scannable page.
>
>   2. **`examples/README.md` is the correct lightweight middle-ground.** The file layout (§1)
>      already adds a one-line `examples/README.md` index. That gives the "where do I start"
>      pointer a `docs/quickstart.md` would provide, without a parallel narrative to maintain.
>
>   3. **Name the split trigger explicitly.** E1's "~200 lines" is the same threshold as D1.
>      When narrator (#84) / MCP (#85) land and push the surface past one page, revisit E2 **and**
>      D2 together (move the walkthrough to `docs/quickstart.md`, contributor content to
>      `CONTRIBUTING.md`). Until then, E1 holds.

---

## 1. File layout (new + changed)

```
openbb_platform/extensions/techtrade/
├── README.md                         # REWRITE (L1) — replaces the #65 scaffold README in place
├── examples/                         # NEW (L8 / Q-A A3) — runnable, CI-smoked scripts
│   ├── __init__.py                   #   marker so pytest can import the package cleanly
│   ├── scan_to_excel.py              #   the headline end-to-end: scan → export to .xlsx
│   ├── plan_one_symbol.py            #   single-symbol path: plan → orders → simulate
│   ├── validate_a_plan.py            #   plan → validate (requires `[validation]` extra)
│   └── README.md                     #   one-line description of each script + how to run
├── tests/unit/
│   └── test_examples_smoke.py        # NEW (Q-A A3) — imports each examples/*.py and asserts
│                                     #   its main() runs end-to-end against the offline fakes
└── (no changes to engine/, reporting/, validation/, models.py, testing.py)
```

**Module-boundary rules**
- `examples/*.py` import **only** from `openbb_techtrade.*` and `openbb` (the public surface). They
  do **not** import from `engine.confluence`, `engine.rules`, `engine.orders`, or any other
  internal seam — examples document the *user* surface, not the engine internals.
- Each example is structured as:
  ```python
  def main(...) -> <return shape>:
      """One-line docstring."""
      ...
      return result

  if __name__ == "__main__":
      main()
  ```
  so the smoke test can `from openbb_techtrade.examples.<name> import main; main(...)` against an
  offline fake. (The `if __name__ == "__main__"` guard runs the live path when a user runs
  `python -m openbb_techtrade.examples.scan_to_excel`.)
- `test_examples_smoke.py` reuses the same offline fakes already in `tests/unit/test_plan.py` and
  `tests/unit/test_scan.py` (`_signal_fetcher`, `_level_fetcher`, mover-candidate fakes) — no new
  fake-data scaffolding is introduced.
- No cycles: `examples ← openbb_techtrade.public_surface ← openbb`. README is a leaf.

---

## 2. README structure (the rewrite — L1 / L2 / L7)

The rewritten README has the following section skeleton (final wording is authored as part of the
implementation; this is the contract):

| Section | What's in it | ≈ lines |
|---|---|---|
| **Title + one-liner** | `# openbb-techtrade` + the existing one-sentence pitch ("Segment-aware technical-indicator trading engine…") | 3 |
| **Disclaimer banner** (L6) | One italic line, identical to the Excel disclaimer (PRD §20 Q9). | 1 |
| **What it does** | 2-3 short paragraphs: the pipeline picture (L9 ASCII), what each stage produces, the soft-dep philosophy. | ~25 |
| **Install** (Q-C C1) | Core install + the 3-row soft-dep install matrix (`[xlsxwriter]` / `[validation]`); first-run `dev_install.py -e` + submodule fetch lines. | ~20 |
| **Quickstart** | The **headline 6-line snippet**: `scan` → `export` (the user's morning-flow), inline. Plus links to `examples/*.py` for the longer flows. | ~10 |
| **Commands** (L7 / L2) | One sub-section per live command (`about`, `segments`, `movers`, `signals`, `plan`, `scan`, `orders`, `simulate`, `export`, `validate`), each with: a one-line description, a 4-6 line example, and the return shape. | ~80 |
| **Roadmap** (Q-B B1) | Short bullet list of the four "extras" issues with one-liners and links. | ~10 |
| **For Contributors** (Q-D D1) | The existing **Vendored indicator engine** + **Testing & determinism** content, demoted to this section. | ~30 |

Total target: ~180 lines (current README is 60). Still scannable.

### 2.1 The pipeline picture (L9 ASCII)

```
                                                            ┌─→ obb.techtrade.export ──→ .xlsx (6 sheets)
                                                            │   (paper-filled plans)
segments → movers → indicator panel → signal → rule/sizing → orders → paper fills → recommendation
   #69       #70         #72/#73         #74        #76         #77       #78           #80
                                                            │
                                                            └─→ obb.techtrade.validate ──→ ValidationReport
                                                                (requires [validation])      verdict ∈ {robust,fragile,overfit}
                                                                                              #82
```

(Exact arrows / spacing finalized at implementation; the picture is content-true to the PRD §9
chain. This same diagram is the L9 "draw once, reuse everywhere" anchor.)

### 2.2 The headline snippet (Quickstart section)

```python
from openbb import obb

# 1. Scan all 11 GICS sectors for ranked, paper-filled trade plans:
plans = obb.techtrade.scan(metric="pct_change", top_n=5).results

# 2. Export the top plans to a 6-sheet Excel workbook:
path = obb.techtrade.export(plans=plans).results
print(f"workbook written to: {path}")
```

(Exact arg set / output finalized at implementation; this is the contract for what the snippet
proves — `scan` returns a list of plans, `export` returns a path.)

---

## 3. Command reference matrix (the §2 "Commands" content, condensed)

The README's Commands section documents each of these. The matrix below is the contract for
*which* commands appear and what each example demonstrates:

| Command | Method | Returns | Example demonstrates | Soft-dep |
|---|---|---|---|---|
| `obb.techtrade.about()` | GET | `{extension_name, extension_version}` | the smoke that techtrade is installed | — |
| `obb.techtrade.segments(...)` | GET | `list[SegmentConfig]` | listing the 11 GICS sectors | — |
| `obb.techtrade.movers(segment=..., metric=..., top_n=...)` | GET | `list[MoverList]` | the top movers per sector | — |
| `obb.techtrade.signals(symbols=..., preset=...)` | GET | `list[MoverSignal]` | the per-symbol confluence vote + score | — |
| `obb.techtrade.plan(symbols=..., risk=..., as_of=...)` | GET | `list[TradePlan]` | a single-segment or single-symbol plan | — |
| `obb.techtrade.scan(metric=..., top_n=..., preset=..., risk=...)` | GET | `list[TradePlan]` (cross-segment ranked) | the headline morning-flow | — |
| `obb.techtrade.orders(plan=...)` | GET | `list[Order]` | materializing a plan's order legs | — |
| `obb.techtrade.simulate(orders=..., bars=...)` | GET | `list[Fill]` | paper-filling order legs forward | — |
| `obb.techtrade.export(plans=..., path=..., engine=...)` | POST | `str` (workbook path) | writing the 6-sheet workbook | `[xlsxwriter]` opt |
| `obb.techtrade.validate(plan=..., method=..., horizon_years=...)` | POST | `ValidationReport` (verdict ∈ {robust, fragile, overfit}) | robustness-validating a plan | `[validation]` req |

Each row in this table maps 1:1 to a sub-section of the README's "Commands" section (Q-C nudge:
the `export` / `validate` rows carry a parenthetical pointer to the soft-dep table).

---

## 4. `examples/` — the runnable scripts (Q-A A3 / L8)

| Script | What it does | Soft-dep | Smoke-tested by |
|---|---|---|---|
| `scan_to_excel.py` | Calls `scan` → `export` → prints the workbook path. The headline end-to-end. | — | `test_examples_smoke.py::test_scan_to_excel_smoke` |
| `plan_one_symbol.py` | Builds a single-symbol `plan`, materializes its `orders`, drives `simulate` over a synthetic forward window, prints the realized `Fill`s. | — | `test_examples_smoke.py::test_plan_one_symbol_smoke` |
| `validate_a_plan.py` | Builds a `plan`, calls `validate(method="wfo", horizon_years=5)`, prints the verdict. Skips cleanly when `openbb-backtest` is absent (mirrors the integration-test pattern). | `[validation]` | `test_examples_smoke.py::test_validate_smoke` (skipif when soft-dep absent) |

**Contract for each script:**

- Top-level docstring states the purpose, the soft-deps required, and the expected output.
- A `main(...)` function that accepts the **same offline fakes** the unit suite uses (`signal_fetcher=…`,
  `level_fetcher=…`, `bars=…`, `BacktestConfig=…`) so the smoke test can drive it with no network.
- A `if __name__ == "__main__":` guard that calls `main()` with **no** fakes — the live path.
- `print()` statements that show the user what landed (counts, sample row, output path).
- Width-clipped to 88 cols, ruff-clean, mypy-clean (rides existing CI).

---

## 5. Determinism & smoke testing (Q-A A3)

### 5.1 Determinism guarantee

The README itself contains no executable assertions; the determinism guarantee for the examples
is that **`test_examples_smoke.py` runs to green offline**. The smoke test:

- Imports each `examples/*.py` module and calls `main(...)` with the offline fakes.
- Asserts the returned shape matches the README's documented contract (a `list[TradePlan]` is
  a `list` of `TradePlan` instances; an `export` path is a `str` that exists on disk).
- **Does not** lock content (no golden snapshot) — the examples are illustrative, not normative;
  the golden locks for actual content live under `tests/golden/` for the engine output.

### 5.2 `tests/unit/test_examples_smoke.py` — the drift guard (Q-A)

```python
import openbb_techtrade.examples.scan_to_excel as scan_to_excel
import openbb_techtrade.examples.plan_one_symbol as plan_one_symbol
# ...

def test_scan_to_excel_smoke(tmp_path):
    """README's headline snippet runs end-to-end (offline) and writes a workbook."""
    path = scan_to_excel.main(
        out=tmp_path / "wb.xlsx",
        signal_fetcher=_fake_signal_fetcher,
        level_fetcher=_fake_level_fetcher,
        candidate_fetcher=_fake_candidate_fetcher,
    )
    assert path.endswith(".xlsx")
    assert os.path.exists(path)
```

(Exact assertion set finalized at implementation; the contract is that **the smoke fails if any
example script breaks its README-documented contract**, and that the smoke is fully offline.)

### 5.3 Integration smoke (optional, not part of #86's required scope)

The integration suite (`tests/integration/`) already covers the live-API path for the engine seams
(`test_scan_integration.py`, `test_validate.py`). #86 does not add a new integration test — the
unit-smoke is enough to prove the README/examples don't drift.

---

## Acceptance mapping (#86)

| Acceptance criterion (issue) | Satisfied by | Open dependency |
|---|---|---|
| README + usage docs covering the full live surface | §2 (full section skeleton), §3 (command matrix) | Q-B (Roadmap), Q-D (For Contributors layout) |
| Worked examples for the headline flows | §4 (`examples/scan_to_excel.py`, `plan_one_symbol.py`, `validate_a_plan.py`) | Q-A (drift-guard) |
| Soft-dep install instructions documented (`[xlsxwriter]`, `[validation]`) | §2 Install section; Q-C C1 install matrix | — |
| Disclaimer present (mirrors PRD §20 Q9 / [#81](https://github.com/prajoria/OpenBB/issues/81)) | L6 banner near top of README | — |
| Roadmap section for not-yet-shipped extras | Q-B B1 (`tune` / narrator / MCP / streaming) | — |
| Drift guard: README snippets stay in sync with the code | Q-A A3 + §5.2 (`test_examples_smoke.py`) | — |
| Pipeline picture documented | L9 ASCII (§2.1) | — |
| Contributor content preserved | Q-D D1 (Vendored indicator + Testing/Determinism demoted to *For Contributors*) | — |
| One README per extension (consistent with peer extensions) | E1 (no separate `docs/quickstart.md`) | — |

> **Net new risks surfaced:** (1) **Q-A** — without the smoke test the README will silently rot,
> the way the scaffold README did between #65 and today; recommend A3 before any rewrite lands.
> (2) **Q-B** — omitting the Roadmap section invites confusion when users find `tune` references
> in older docs / issue comments; recommend B1. Both have a clear default; both should be
> confirmed before implementation.

---

## Implementation order (post-review)

Per the established pattern, implementation lands in **three commits**:

1. **`feat(techtrade): #86 rewrite README + add examples/`** — the new `README.md` + the three
   `examples/*.py` scripts + `examples/README.md` index + `examples/__init__.py`.
2. **`test(techtrade): #86 examples drift-guard smoke (3 tests)`** — `test_examples_smoke.py`,
   one test per example.
3. *(only if needed)* **`docs(techtrade): #86 fix small docs drift caught by review`** — optional
   follow-up if review surfaces any final-pass wording.

Total target: ~600-800 lines added, 60 deleted (the existing scaffold README). Net code: ~5-10
lines (the examples' `if __name__ == "__main__":` guards); the rest is markdown + the smoke test.
