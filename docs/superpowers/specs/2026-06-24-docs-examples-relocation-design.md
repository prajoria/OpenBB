# Design — Relocate example notebooks to `docs/examples/` with stripped outputs

**Tracking:** GitHub issue [#22](https://github.com/prajoria/OpenBB/issues/22)
**Date:** 2026-06-24
**Phase:** 1 (Design) — approved 2026-06-24

## 1. Context

PR #16 (`feat/stock-analysis`) originally bundled ~25 general OpenBB example
notebooks plus unrelated demos, inflating the diff to ~74k additions across four
concerns. Review trimmed #16 to the 7-phase single-stock pipeline only and
deferred the notebooks to a follow-up — this work.

The current state in `master` (verified 2026-06-24):

| Aspect | Reality |
|---|---|
| Location | 21 `.ipynb` + 4 `.webp` + `README.md` + `content.json` + `COMMUNITY_EXAMPLE_TEMPLATE.ipynb` in top-level `examples/` |
| Output state | Outputs and `execution_count` populated in committed notebooks |
| Notable sizes | `openbbPlatformAsLLMTools.ipynb` 4.0 MB, `riskReturnAnalysis.ipynb` 945 KB |
| `.gitignore` re `*.ipynb` | **Not** ignored (only `.ipynb_checkpoints/`). The issue's premise that *.ipynb is ignored is incorrect. |
| Pre-commit | No `nbstripout` hook configured |

## 2. Goals

1. Move curated example notebooks under `docs/examples/`.
2. Strip all outputs and `execution_count` in committed notebooks.
3. Enforce output-stripping going forward via pre-commit so future commits cannot reintroduce bloat.
4. Preserve git history for moved files.
5. Keep PR diff dominated by renames, not content churn.

## 3. Non-goals

- Re-running or curating notebook content (cells stay as-is besides the output strip).
- Adding new example notebooks.
- Backporting changes to the original upstream OpenBB repository.
- Validating that every notebook actually runs end-to-end against the current
  fmp_cached provider (out of scope; can be filed as a follow-up).

## 4. Design decisions

### D1. Destination & move strategy
- Destination: `docs/examples/`
- Mechanism: `git mv examples/<file> docs/examples/<file>` per file, committed as a **pure rename** first to maximize git's rename detection.
- Output-strip and README edits land in a **separate** follow-up commit so renames remain at 100% similarity.

### D2. Curation — opt-in keep set

**Keep (11):**

| Notebook | Notes |
|---|---|
| `googleColab.ipynb` | Colab bootstrap |
| `findSymbols.ipynb` | Discovery flow |
| `loadHistoricalPriceData.ipynb` | Core price data demo |
| `financialStatements.ipynb` | Statements demo |
| `copperToGoldRatio.ipynb` | Macro example |
| `usdLiquidityIndex.ipynb` | Macro example |
| `impliedEarningsMove.ipynb` | Options example |
| `openbbPlatformAsLLMTools.ipynb` | LLM integration — conditional, see below |
| `platform_standardization.ipynb` | Platform concepts |
| `openbb_vs_langchain.ipynb` | LLM comparison |
| `COMMUNITY_EXAMPLE_TEMPLATE.ipynb` | Template for contributors |

**Drop (7):** `mAndAImpact.ipynb`, `sectorRotationStrategy.ipynb`, `riskReturnAnalysis.ipynb`, `portfolioOptimizationUsingModernPortfolioTheory.ipynb`, `currencyExchangeRateForecasting.ipynb`, `EthereumTrendAnalysis.ipynb`, `BacktestingMomentumTrading.ipynb` — not on issue candidate list, large, likely stale upstream demos.

**Conditional rule:** `openbbPlatformAsLLMTools.ipynb` is 4.0 MB raw. After strip,
if final size on disk is > 500 KB, drop it. Otherwise keep.

**Companion assets:** the `.webp` images named the same as kept notebooks move
alongside. `.webp` for dropped notebooks (`streamlit_news.webp` is referenced by
a notebook that was already removed earlier) are dropped. `content.json` moves
(it indexes the kept notebooks; update entries accordingly).

### D3. Output-strip enforcement
- Add `nbstripout` as a `pre-commit` hook in `.pre-commit-config.yaml`:
  ```yaml
  - repo: https://github.com/kynan/nbstripout
    rev: 0.7.1
    hooks:
      - id: nbstripout
  ```
- Run `pre-commit run nbstripout --all-files` once to clear current outputs on
  kept notebooks.
- Going forward, every commit auto-strips. No dev-time friction.

### D4. No `.gitignore` change
- `*.ipynb` is **not** ignored, so no `!docs/examples/**` allow-list rule is
  needed. We will note this in the PR body to close out the issue's premise.

### D5. README updates
- Move `examples/README.md` → `docs/examples/README.md`.
- Edit:
  - Remove table-of-contents entries for dropped notebooks.
  - Add a "Contributing examples" section pointing at the `nbstripout` hook so
    contributors know outputs will be auto-stripped.
  - Update any path references within the README.

### D6. Acceptance criteria
1. `docs/examples/` contains the kept set (11 notebooks + companion `.webp` + `README.md` + `content.json`).
2. Top-level `examples/` directory is removed.
3. `.pre-commit-config.yaml` includes `nbstripout` and the hook passes on the
   committed state of all moved notebooks (zero `outputs`, `execution_count: null`).
4. `git log --follow docs/examples/<any moved file>` shows the original history.
5. `pre-commit run --all-files` is green.

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `git mv` + content edit in same commit loses rename detection | Land pure rename in commit 1, strip + README edits in commit 2 |
| `nbstripout` flagged as a new dev dependency | It runs only inside pre-commit's isolated env; no project-level install required |
| `openbbPlatformAsLLMTools.ipynb` still huge after strip | Conditional drop if post-strip > 500 KB (D2) |
| Stripping mangles metadata used by Colab / notebook tooling | `nbstripout` defaults preserve essential metadata; verify in QA step |

## 6. Out-of-scope follow-ups

- File a separate bd issue if any kept notebook fails to execute against the
  current `fmp_cached` provider during a future verification pass.
- Consider adding a CI job that runs `nbstripout --verify` on PRs (not in this
  scope, since pre-commit covers local).
