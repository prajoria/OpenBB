# `tools/pine/` — openbb-pine extension developer tooling

Helpers that live outside the extension package itself because they're
operator/CI tools, not runtime code. Each one is invoked from CI plus
runnable locally.

## Tools

| Script | Purpose | Invoked by |
|---|---|---|
| `verify_pynecore_license.py` | Verify the vendored PyneCore submodule's `NOTICE` / `LICENSE` match the pinned `.license_manifest.json`. | `.github/workflows/pynecore-license-check.yml` |
| `refresh_pynecore_manifest.py` | Refresh the manifest after a PyneCore bump. Requires `--confirm-license-reviewed`. | Manually after a submodule bump |
| `measure_wild_corpus_coverage.py` | Compute the PRD §3.4 coverage metric and render a PR comment. | `.github/workflows/wild-corpus-coverage.yml` |
| `crawl_wild_corpus.py` *(L0.4, planned)* | Produce `tests/wild_corpus/index.json` — the per-script fingerprint index that feeds the coverage tool. | Manually one-time per corpus refresh |

## `measure_wild_corpus_coverage.py` — semantics

The PRD's promise to the user is "existing Pine scripts run unedited"
(PRD §1.4). Without a measurement that turns "run unedited" into a
percentage we can't honestly assert progress toward §8.1's phase gates
(M1 ≥40%, M2 ≥70%, M3 ≥90%) or §12's 12-month success target (≥90%).

The tool reads two inputs:

1. **`tests/wild_corpus/index.json`** — the fingerprint index produced
   by `crawl_wild_corpus.py` (L0.4). Each entry carries the script's
   declared Pine version, the set of built-in identifiers it uses, the
   grammar features it touches, and a `source_visible` flag.
2. **`openbb_pine._coverage_manifest`** — three frozensets exported by
   the extension that name **what is implemented**:
   `PINE_VERSIONS_SUPPORTED`, `BUILTINS_IMPLEMENTED`,
   `FEATURES_IMPLEMENTED`.

A script "runs unedited" iff its declared Pine version is supported AND
every builtin it uses is in `BUILTINS_IMPLEMENTED` AND every grammar
feature it uses is in `FEATURES_IMPLEMENTED`. Source-not-visible scripts
are reported in a separate `unknown` bucket — the headline
`coverage_pct` is computed against `source_visible == true` scripts
only.

### Outputs

JSON to stdout (always):

```json
{
  "schema_version": 1,
  "status": "ok",
  "computed_at": "2026-...",
  "implemented_baseline": { ... },
  "corpus": {"total": 1000, "source_visible": 850, "source_not_visible": 150},
  "coverage": {"would_run_unedited": 0, "would_not_run": 850, "coverage_pct": 0.0, "unknown_pct": 15.0},
  "blockers": [
    {"identifier": "ta.sma", "kind": "builtin", "blocks_count": 320},
    ...
  ]
}
```

PR-comment markdown (with `--pr-comment-out PATH`): table of "this PR vs
main vs Δ" + top-5 blockers.

### CLI

```bash
# Plain measurement (JSON to stdout):
python tools/pine/measure_wild_corpus_coverage.py

# Full CI shape: write the PR comment with delta vs the saved main baseline.
python tools/pine/measure_wild_corpus_coverage.py \
    --baseline-json tools/pine/_baselines/wild_corpus_coverage.json \
    --pr-comment-out /tmp/wcc-comment.md
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Ran cleanly. This is a measurement, not a pass/fail — coverage going down does not exit non-zero by default. |
| 1 | Ran but with an error (malformed index, unparseable manifest, etc). |
| 2 | Only when `--fail-on-regression PCT` is passed: coverage dropped by more than `PCT` percentage points relative to the supplied baseline. |

### Race-tolerant behavior

The tool is designed to be installed in CI **before** L0.4's
`crawl_wild_corpus.py` produces its first index. When
`tests/wild_corpus/index.json` is missing:

* exit code is **0** (this is not a failure);
* JSON output carries `status: "skipped"`, `coverage_pct: null`, and a
  `reason` string pointing at the crawler;
* the PR comment surfaces the same message so reviewers can see the job
  ran intentionally.

Once L0.4 lands and the index appears, the tool starts producing real
numbers on the next PR without any further changes.

The implementation manifest is also loaded defensively: if
`openbb_pine._coverage_manifest` cannot be imported (e.g. the extension
isn't installed in the runner's venv) every implemented set is treated
as empty and the load failure is recorded in the JSON under
`implemented_baseline.manifest_status`.

## Baseline procedure

The delta column in the PR comment compares against the JSON saved at
`tools/pine/_baselines/wild_corpus_coverage.json`. This file is **owned
by the main-branch CI workflow**:

1. On every push to `main`, `wild-corpus-coverage.yml` runs the tool and
   uploads `wild_corpus_coverage.json` as a workflow artifact.
2. The same step also stages the file at
   `tools/pine/_baselines/wild_corpus_coverage.json` inside the runner.
   Committing this back to the branch is intentionally **out of scope**
   for the bot — a maintainer opens a periodic PR titled `"chore(pine):
   refresh wild-corpus baseline"` to rotate it in, so each baseline
   bump is human-acknowledged.
3. PR runs read the file via `git show origin/main:...` — falling back
   to an empty `{}` if it does not yet exist (Phase 0 first run).

This keeps the metric **transparent and reproducible** (you can always
compute today's number locally without waiting for CI) while keeping the
baseline **non-bot-controlled** (a tightening trend requires intent).
