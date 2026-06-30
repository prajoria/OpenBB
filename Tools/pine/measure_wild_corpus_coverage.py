#!/usr/bin/env python3
"""Measure wild-corpus coverage and emit JSON + PR-comment markdown.

This is the L0.5 deliverable for the openbb-pine extension (PRD §3.4 +
§8.1 + §12). It reads two inputs:

1. ``tests/wild_corpus/index.json`` -- the per-script fingerprint index
   produced by ``tools/pine/crawl_wild_corpus.py`` (L0.4). Each script
   entry carries:

   * ``pine_version`` -- integer (5, 6, ...)
   * ``builtins_used`` -- list of fully-qualified identifiers
   * ``features_used`` -- list of grammar features
   * ``source_visible`` -- bool; false for closed/private scripts whose
     source we could not fingerprint (counted as ``unknown``).

   A missing index is **not** a failure -- the tool emits a "skipped"
   status with ``coverage_pct: null`` and exits 0. This is the race-
   tolerant path while L0.4 lands.

2. ``openbb_platform/extensions/pine/openbb_pine/_coverage_manifest.py``
   -- the implemented-feature manifest (three frozensets). At Phase 0
   every set is empty, so baseline = 0%. The module is imported lazily;
   if ``openbb_pine`` isn't installed (L0.2 race), every set is treated
   as empty.

A script "runs unedited" iff its declared Pine version is supported AND
every builtin it uses is implemented AND every grammar feature it uses
is implemented. Source-not-visible scripts go in a separate ``unknown``
bucket -- the headline ``coverage_pct`` is computed against
``source_visible == true`` scripts only.

Outputs:

* JSON to stdout (always) -- machine-readable.
* Markdown to ``--pr-comment-out PATH`` (if supplied) -- human-readable
  with the delta-vs-main column.

Exit codes:

* 0 -- ran cleanly (regardless of the coverage number; this is a
  measurement tool, not a pass/fail).
* 1 -- ran but with an error (malformed index, unparseable manifest).
* 2 -- explicit regression beyond ``--fail-on-regression PCT`` (only
  when that flag is supplied AND coverage dropped by more than that
  number of percentage points from baseline).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_PATH = REPO_ROOT / "tests" / "wild_corpus" / "index.json"
DEFAULT_BASELINE_PATH = (
    REPO_ROOT / "tools" / "pine" / "_baselines" / "wild_corpus_coverage.json"
)

SCHEMA_VERSION = 1

# Closed vocabulary of grammar features the wild-corpus indexer records.
# Mirrors _coverage_manifest.py's docstring. Kept here for the "skipped"
# baseline payload so consumers see the same shape regardless of state.
KNOWN_FEATURES: tuple[str, ...] = (
    "request.security",
    "library",
    "drawings",
    "strategy",
    "indicator",
)


# --- Manifest loading ----------------------------------------------------


def _load_implemented_baseline() -> dict[str, Any]:
    """Read the three frozensets from openbb_pine._coverage_manifest.

    Defensive: if the module is not importable (L0.2 hasn't published it
    yet, or the extension is not on sys.path during a CI dry-run), treat
    every set as empty and record the import failure in the baseline so
    a consumer can tell "empty by design" from "empty by accident".
    """
    try:
        # Always re-import freshly so tests that mutate the module see the
        # latest values.
        module = importlib.import_module("openbb_pine._coverage_manifest")
        importlib.reload(module)
        versions = sorted(getattr(module, "PINE_VERSIONS_SUPPORTED", frozenset()))
        builtins = frozenset(getattr(module, "BUILTINS_IMPLEMENTED", frozenset()))
        features = frozenset(getattr(module, "FEATURES_IMPLEMENTED", frozenset()))
        manifest_status = "loaded"
    except (ImportError, ModuleNotFoundError) as exc:
        versions, builtins, features = [], frozenset(), frozenset()
        manifest_status = f"not_importable: {exc}"

    return {
        "manifest_status": manifest_status,
        "pine_versions": list(versions),
        "builtins": builtins,
        "features": sorted(features),
        # The headline JSON section keeps a count rather than dumping every
        # builtin -- once the implemented set grows past Phase 0 the full
        # list is too long for a PR comment.
        "builtins_count": len(builtins),
    }


# --- Index loading + per-script verdict ---------------------------------


# Mapping from L0.4's `features_used` boolean keys to the canonical feature
# vocabulary that the manifest's FEATURES_IMPLEMENTED records. PRD §3.4
# names the features; L0.4's README (tests/wild_corpus/README.md) names
# the keys. The two are linked HERE so neither side has to know about the
# other.
FEATURE_KEY_TO_NAME: dict[str, str] = {
    "uses_request_security": "request.security",
    "uses_library_directive": "library",
    "uses_drawings": "drawings",
    "uses_strategy_directive": "strategy",
    "uses_indicator_directive": "indicator",
}


def _load_index(path: Path) -> list[dict[str, Any]]:
    """Load the wild-corpus index; return the list of script entries.

    The L0.4 crawler produces a JSON ARRAY (one object per script). For
    backward compatibility with earlier drafts and inline test fixtures
    we also accept the shape ``{"scripts": [...]}`` — the bag of script
    dicts is what we actually care about.
    """
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        scripts = data
    elif isinstance(data, dict) and isinstance(data.get("scripts"), list):
        scripts = data["scripts"]
    else:
        raise ValueError(
            "wild-corpus index must be a JSON array OR an object with a "
            f"'scripts' array; got {type(data).__name__}"
        )
    if not all(isinstance(s, dict) for s in scripts):
        raise ValueError("wild-corpus index contains non-object entries")
    return scripts


def _normalize_features(raw: Any) -> set[str]:
    """Normalize ``features_used`` into a set of canonical feature names.

    Accepts both L0.4's dict-of-flags (the real shape) and a plain list of
    canonical names (the test-fixture shape). Returns ``set()`` for None
    or for any input shape we don't recognize -- the caller treats this
    as "no features used", which is the safe default for the coverage gate.
    """
    if raw is None:
        return set()
    if isinstance(raw, list):
        # Test-fixture / explicit-vocabulary shape: ["indicator", ...].
        return {f for f in raw if isinstance(f, str)}
    if isinstance(raw, dict):
        used: set[str] = set()
        for key, name in FEATURE_KEY_TO_NAME.items():
            value = raw.get(key)
            if isinstance(value, bool) and value:
                used.add(name)
        # `uses_input_array` is an int counter, not a gate — ignore.
        return used
    return set()


def _script_would_run(
    script: dict[str, Any],
    pine_versions: frozenset[int],
    builtins: frozenset[str],
    features: frozenset[str],
) -> tuple[bool, list[tuple[str, str]]]:
    """Decide whether one script "runs unedited" and list its blockers.

    Returns (verdict, blockers). ``blockers`` is a list of
    ``(identifier, kind)`` pairs describing every unimplemented thing
    the script references. We collect ALL blockers, not just the first,
    so the top-blockers tally is accurate.
    """
    blockers: list[tuple[str, str]] = []

    version = script.get("pine_version")
    if version not in pine_versions:
        # Pine versions are aggregated as a synthetic identifier so they
        # appear in the blockers list alongside builtins/features.
        blockers.append((f"pine_v{version}", "pine_version"))

    used_builtins = set(script.get("builtins_used") or [])
    for b in sorted(used_builtins - builtins):
        blockers.append((b, "builtin"))

    used_features = _normalize_features(script.get("features_used"))
    for f in sorted(used_features - features):
        blockers.append((f, "feature"))

    return (not blockers, blockers)


# --- Coverage computation -----------------------------------------------


def compute_coverage(
    index: dict[str, Any] | list[dict[str, Any]],
    implemented: dict[str, Any],
    top_blockers: int = 30,
) -> dict[str, Any]:
    """Aggregate per-script verdicts into the JSON payload.

    Accepts either the L0.4 list-shape index or the legacy dict-with-
    ``scripts`` shape (kept for inline test fixtures). The headline
    metric (``coverage_pct``) is over source-visible scripts only;
    source-not-visible scripts get reported in a separate ``unknown``
    bucket.
    """
    pine_versions = frozenset(implemented["pine_versions"])
    builtins = implemented["builtins"]
    features = frozenset(implemented["features"])

    if isinstance(index, dict):
        scripts = index.get("scripts") or []
    else:
        scripts = index
    total = len(scripts)
    blocker_counter: Counter[tuple[str, str]] = Counter()

    source_visible = 0
    would_run = 0
    would_not = 0
    unknown = 0

    for script in scripts:
        if not script.get("source_visible", True):
            unknown += 1
            continue
        source_visible += 1
        verdict, blockers = _script_would_run(script, pine_versions, builtins, features)
        if verdict:
            would_run += 1
        else:
            would_not += 1
            for ident_kind in blockers:
                blocker_counter[ident_kind] += 1

    if source_visible == 0:
        coverage_pct: float = 0.0
    else:
        coverage_pct = round(would_run * 100.0 / source_visible, 2)

    unknown_pct = round(unknown * 100.0 / total, 2) if total else 0.0

    top = [
        {"identifier": ident, "kind": kind, "blocks_count": count}
        for (ident, kind), count in blocker_counter.most_common(top_blockers)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "computed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "implemented_baseline": {
            "pine_versions": list(implemented["pine_versions"]),
            "builtins_count": implemented["builtins_count"],
            "features": list(implemented["features"]),
            "manifest_status": implemented["manifest_status"],
        },
        "corpus": {
            "total": total,
            "source_visible": source_visible,
            "source_not_visible": unknown,
        },
        "coverage": {
            "would_run_unedited": would_run,
            "would_not_run": would_not,
            "coverage_pct": coverage_pct,
            "unknown_pct": unknown_pct,
        },
        "blockers": top,
    }


def skipped_payload(reason: str, implemented: dict[str, Any]) -> dict[str, Any]:
    """Payload returned when the index file is missing or empty."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "skipped",
        "reason": reason,
        "computed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "coverage_pct": None,
        "implemented_baseline": {
            "pine_versions": list(implemented["pine_versions"]),
            "builtins_count": implemented["builtins_count"],
            "features": list(implemented["features"]),
            "manifest_status": implemented["manifest_status"],
        },
    }


# --- PR-comment rendering -----------------------------------------------


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def _fmt_delta(current: float | None, baseline: float | None) -> str:
    if current is None or baseline is None:
        return "—"
    delta = current - baseline
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.2f} pp"


def render_pr_comment(payload: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    """Render the markdown PR comment for the sticky-comment action."""
    if payload["status"] == "skipped":
        baseline_status = (
            "no baseline available — running for the first time."
            if not baseline
            else "baseline retained from previous run."
        )
        return (
            "## Wild-corpus coverage — PR check\n\n"
            "**Status:** skipped — " + payload["reason"] + "\n\n"
            "The measurement tool ran cleanly but had nothing to measure. "
            "Once `tools/pine/crawl_wild_corpus.py` (L0.4) produces "
            "`tests/wild_corpus/index.json`, this comment will switch to a "
            "real coverage number.\n\n"
            f"_{baseline_status}_\n\n"
            "Measured by `tools/pine/measure_wild_corpus_coverage.py`.\n"
        )

    cur_cov = payload["coverage"]["coverage_pct"]
    cur_un = payload["coverage"]["unknown_pct"]
    cur_run = payload["coverage"]["would_run_unedited"]
    cur_vis = payload["corpus"]["source_visible"]
    cur_unk = payload["corpus"]["source_not_visible"]

    if baseline and baseline.get("status") == "ok":
        base_cov = baseline["coverage"]["coverage_pct"]
        base_un = baseline["coverage"]["unknown_pct"]
        base_run = baseline["coverage"]["would_run_unedited"]
        base_vis = baseline["corpus"]["source_visible"]
        base_unk = baseline["corpus"]["source_not_visible"]
        delta_cov = _fmt_delta(cur_cov, base_cov)
        base_run_cell = f"{base_run} / {base_vis} ({_fmt_pct(base_cov)})"
        base_unk_cell = f"{base_unk} ({_fmt_pct(base_un)})"
    else:
        delta_cov = "—"
        base_run_cell = "—"
        base_unk_cell = "—"

    lines: list[str] = [
        "## Wild-corpus coverage — PR check",
        "",
        "| | This PR | main | Δ |",
        "|---|---:|---:|---:|",
        (
            f"| Scripts that would run unedited "
            f"| **{cur_run} / {cur_vis}** (**{_fmt_pct(cur_cov)}**) "
            f"| {base_run_cell} "
            f"| {delta_cov} |"
        ),
        (
            f"| Unknown (source not visible) "
            f"| {cur_unk} ({_fmt_pct(cur_un)}) "
            f"| {base_unk_cell} "
            f"| — |"
        ),
        "",
    ]

    blockers = payload.get("blockers") or []
    if blockers:
        lines.append(
            "**Top 5 blockers** (unimplemented identifiers blocking the most scripts):"
        )
        for i, b in enumerate(blockers[:5], start=1):
            lines.append(
                f"{i}. `{b['identifier']}` ({b['kind']}) — blocks {b['blocks_count']} scripts"
            )
        lines.append("")
    else:
        lines.append(
            "_No blockers — every source-visible script in the corpus runs unedited._"
        )
        lines.append("")

    lines.extend(
        [
            "PRD targets: M1 ≥40%, M2 ≥70%, M3 ≥90%.",
            (
                "Measured by `tools/pine/measure_wild_corpus_coverage.py` "
                f"against `tests/wild_corpus/index.json` "
                f"(~{cur_vis} source-visible scripts)."
            ),
            "",
        ]
    )
    return "\n".join(lines)


# --- Baseline loading ----------------------------------------------------


def _load_baseline(path: Path | None) -> dict[str, Any] | None:
    """Load a saved baseline (may be missing or malformed; treat as None)."""
    if path is None:
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


# --- CLI entry point ----------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for ``measure_wild_corpus_coverage``."""
    parser = argparse.ArgumentParser(
        description=(
            "Compute openbb-pine wild-corpus coverage from "
            "tests/wild_corpus/index.json and "
            "openbb_pine._coverage_manifest. Emits JSON to stdout."
        )
    )
    parser.add_argument(
        "--index-path",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help=(
            "Path to the wild-corpus index JSON. "
            f"Defaults to {DEFAULT_INDEX_PATH.relative_to(REPO_ROOT)}."
        ),
    )
    parser.add_argument(
        "--pr-comment-out",
        type=Path,
        default=None,
        help="If supplied, write the human-readable markdown PR comment to this path.",
    )
    parser.add_argument(
        "--baseline-json",
        type=Path,
        default=None,
        help=(
            "Optional path to a previously-saved coverage JSON (typically the "
            "main-branch baseline). Used to compute the delta column in the PR "
            "comment. Missing or unreadable file is treated as 'no baseline'."
        ),
    )
    parser.add_argument(
        "--top-blockers",
        type=int,
        default=30,
        help="How many top blockers to include in the JSON payload (default 30).",
    )
    parser.add_argument(
        "--fail-on-regression",
        type=float,
        default=None,
        metavar="PCT",
        help=(
            "If supplied, exit 2 when coverage_pct drops by more than this many "
            "percentage points from the baseline. Otherwise this tool always "
            "exits 0 on success regardless of the coverage number."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the measurement tool; return the documented exit code."""
    args = build_arg_parser().parse_args(argv)

    implemented = _load_implemented_baseline()

    if not args.index_path.exists():
        payload = skipped_payload(
            f"wild_corpus/index.json absent — run tools/pine/crawl_wild_corpus.py first "
            f"(expected at {args.index_path})",
            implemented,
        )
        baseline = _load_baseline(args.baseline_json)
        print(json.dumps(payload, indent=2, sort_keys=True))  # noqa: T201 - CLI tool
        if args.pr_comment_out is not None:
            args.pr_comment_out.parent.mkdir(parents=True, exist_ok=True)
            args.pr_comment_out.write_text(
                render_pr_comment(payload, baseline), encoding="utf-8"
            )
        return 0

    try:
        index = _load_index(args.index_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(  # noqa: T201 - CLI tool
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "error",
                    "error": f"failed to load index {args.index_path}: {exc}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    payload = compute_coverage(index, implemented, top_blockers=args.top_blockers)
    baseline = _load_baseline(args.baseline_json)

    print(json.dumps(payload, indent=2, sort_keys=True))  # noqa: T201 - CLI tool

    if args.pr_comment_out is not None:
        args.pr_comment_out.parent.mkdir(parents=True, exist_ok=True)
        args.pr_comment_out.write_text(
            render_pr_comment(payload, baseline), encoding="utf-8"
        )

    # Regression gating is opt-in. The default workflow is measurement, not
    # enforcement -- a coverage regression should be visible in the PR
    # comment but should not block CI unless the caller explicitly asked.
    if (
        args.fail_on_regression is not None
        and baseline
        and baseline.get("status") == "ok"
    ):
        cur = payload["coverage"]["coverage_pct"]
        base = baseline["coverage"]["coverage_pct"]
        if base - cur > args.fail_on_regression:
            print(  # noqa: T201 - CLI tool
                f"REGRESSION: coverage dropped from {base:.2f}% to {cur:.2f}% "
                f"(> {args.fail_on_regression:.2f} pp tolerance)",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
