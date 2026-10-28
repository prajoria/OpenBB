"""Build the notebook story manifests and capability catalog (#2212, N02).

Derives one ``StoryManifest`` per notebook from its source-only inventory and
writes them, with a ``CapabilityCatalog``, under
``openbb_platform/extensions/agents/openbb_agents/notebook_guide/stories/``.

- Each ``##`` Markdown section is a stage; cells before the first section form
  a ``setup`` stage. Stages depend on the previous stage (ordered mapping).
- ``obb.*`` calls map to available ``platform:<tool>`` capabilities, pinned by
  the SHA-256 of the tool's input schema on a real ``portfolio-ops`` server.
- Notebook-local engines, state, artifacts, jobs, paper and provider internals
  map to planned ``story:*`` capabilities owned by their N-task issues. A
  numbered section that only computes locally needs ``story:analytics``.

Rerun after a notebook changes, review the diff, and commit the result:

    python scripts/build_story_manifests.py
"""

# pylint: disable=import-outside-toplevel,wrong-import-position

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "openbb_platform" / "extensions" / "agents"))

from scripts.notebook_story_inventory import (  # noqa: E402
    NotebookSource,
    inventory_notebooks,
)

STORIES_DIR = (
    REPO_ROOT
    / "openbb_platform"
    / "extensions"
    / "agents"
    / "openbb_agents"
    / "notebook_guide"
    / "stories"
)

# Planned capabilities: (access, owning issue, summary).
PLANNED: dict[str, tuple[str, int, str]] = {
    "story:analytics": (
        "analysis",
        2215,
        "Notebook-local calculations and engines exposed through owned adapters (N05).",
    ),
    "story:state": (
        "analysis",
        2216,
        "Typed story state and cross-chapter handoffs instead of pickle files (N06).",
    ),
    "story:artifacts": (
        "artifact",
        2217,
        "Bounded chart, table, report and XLSX artifacts (N07).",
    ),
    "story:jobs": (
        "analysis",
        2218,
        "Backtest, tuning and replay through existing durable jobs (N08).",
    ),
    "story:paper": (
        "paper",
        2219,
        "Portfolio and TechTrade paper actions in an approved sandbox (N09).",
    ),
    "story:provider_modes": (
        "provider_read",
        2220,
        "Provider variants, recording and truthful cache semantics (N10).",
    ),
    "story:binding_review": (
        "analysis",
        2214,
        "Behaviour whose MCP binding must be decided during readiness review (N04).",
    ),
}

# Import prefix -> planned capability. Longest matching prefix wins.
IMPORT_CAPABILITIES: dict[str, str] = {
    "pickle": "story:state",
    "_nb_render": "story:artifacts",
    "html": "story:artifacts",
    "openpyxl": "story:artifacts",
    "_nport_lookthrough": "story:analytics",
    "stock_analysis": "story:analytics",
    "openbb_regime": "story:analytics",
    "openbb_portfolio_intel.analytics": "story:analytics",
    "openbb_portfolio_intel.models": "story:analytics",
    "openbb_portfolio_intel.paper": "story:paper",
    "openbb_sec.utils.thirteen_f_index": "story:analytics",
    "openbb_fmp_cached.models.institutional_ownership": "story:analytics",
    "openbb_techtrade.engine": "story:analytics",
    "openbb_techtrade.execution": "story:paper",
    "openbb_techtrade.validation": "story:jobs",
    "openbb_techtrade.tuning": "story:jobs",
    "openbb_techtrade.examples": "story:jobs",
    "openbb_backtest": "story:jobs",
    "openbb_yfinance": "story:provider_modes",
    "openbb_cboe": "story:provider_modes",
    "openbb_sec": "story:provider_modes",
    "openbb_fmp_cached": "story:provider_modes",
    "openbb_fmp": "story:provider_modes",
    "yfinance": "story:provider_modes",
    # Reviewed in N04 (#2214): the notebook previews the operator's local
    # positions DB. The agent may only use the Portfolio adapter's sanitized
    # snapshot read, and the stage is optional because the notebook skips it
    # when the importer is not installed.
    "portfolio_snapshot_importer": "platform:portfolio_portfolio_snapshots",
}

_EFFECTIVE = "platform:story_basket_effective_positions"
_SECTORS = "platform:story_basket_sector_view"
_CONCENTRATION = "platform:story_concentration"
_CONSTRUCTION = "platform:story_construction_targets"
_SINGLE_NAME = "platform:story_single_name_analysis"
_BRINSON = "platform:story_brinson_attribution"
_WHATIF = "platform:story_whatif_diff"
_TRADES = "platform:story_candidate_trades"
_WEATHER = "platform:story_market_weather"
_INSTITUTIONAL = "platform:story_institutional_summary"
_PLANS = "platform:story_actionable_plans"
_PNL = "platform:story_round_trip_pnl"
_REPLAY = "platform:story_replay_recommendations"
_CONFIG = "platform:story_indicator_config"
_STATE = "story:state"
_MODES = "story:provider_modes"
_PAPER = "story:paper"
# Reviewed in N05a (#2313): stages whose notebook-local x-ray math the server
# computes. (story_id, stage_id) -> (tools, residual). ``residual`` keeps
# story:analytics when part of the stage still has no tool: the free-tier
# chapters' hand-maintained issuer-to-sector map is not a server tool.
REVIEWED_BINDINGS: dict[tuple[str, str], tuple[tuple[str, ...], bool]] = {
    ("portfolio/03", "3-the-x-ray-look-through-via-sec-n-port-obb-etf"): (
        (_EFFECTIVE,),
        False,
    ),
    ("portfolio/03", "4-sector-pie-with-look-through-the-pivot"): ((_SECTORS,), False),
    ("portfolio/03", "5-hhi-effective-n-two-numbers-to-quote-from-now"): (
        (_CONCENTRATION,),
        False,
    ),
    ("portfolio/03", "7-concentration-obb-portfolio-intel-risk-concent"): (
        (_CONCENTRATION,),
        False,
    ),
    ("portfolio/03", "8-portfolio-construction-turning-the-x-ray-into"): (
        (_CONSTRUCTION,),
        False,
    ),
    ("portfolio_yfinance/03", "3-the-x-ray-sec-n-port-look-through"): (
        (_EFFECTIVE,),
        False,
    ),
    ("portfolio_yfinance/03", "5-hhi-effective-n-the-two-numbers-to-quote"): (
        (_CONCENTRATION,),
        False,
    ),
    ("portfolio_yfinance/03", "7-concentration-top-k-weights-single-name-kill-s"): (
        (_CONCENTRATION,),
        False,
    ),
    ("portfolio/08", "5-basket-x-ray-look-through-via-sec-n-port"): (
        (_EFFECTIVE,),
        False,
    ),
    ("portfolio/08", "6-risk-metrics-hhi-effective-n-sector-view"): (
        (_SECTORS, _CONCENTRATION),
        False,
    ),
    ("portfolio/08", "10a-the-self-maintained-alternative-five-etfs-on"): (
        (_EFFECTIVE,),
        False,
    ),
    ("portfolio_yfinance/08", "5-basket-x-ray-sec-n-port-look-through"): (
        (_EFFECTIVE,),
        False,
    ),
    # The free-tier sector map half of this stage is a provider mode (N10).
    ("portfolio_yfinance/08", "6-risk-metrics-hhi-effective-n-free-tier-sector"): (
        (_CONCENTRATION, "story:provider_modes"),
        False,
    ),
    # Reviewed in N05b (#2314): the seven-phase pipeline. portfolio/02 runs it
    # and renders each phase; the regime overlay and the bad-symbol
    # loud-empty demonstration are the same tool with other inputs.
    **{
        ("portfolio/02", stage): ((_SINGLE_NAME,), False)
        for stage in (
            "0-why-start-with-one-name",
            "1-phase-1-company",
            "2-phase-2-fundamentals",
            "3-phase-3-technicals",
            "4-phase-4-valuation",
            "5-phase-5-risk",
            "6-phase-6-peer-relative",
            "7-phase-7-composite-decision",
            "8-regime-overlay-same-symbol-hostile-regime",
            "12-loud-empty-demonstration",
        )
    },
    ("portfolio/08", "7-single-name-spot-check-analysis-7-phase-on-the"): (
        (_SINGLE_NAME,),
        False,
    ),
    # Reviewed in N05c (#2315): the what-if and attribution chapter in both
    # provider variants.
    **{
        (story, stage): (tools, False)
        for story, stage, tools in (
            (
                "portfolio/05",
                "2-the-three-candidate-trades-in-english-first",
                (_TRADES,),
            ),
            (
                "portfolio/05",
                "3-what-if-diff-pr-905-https-github-com-prajoria",
                (_WHATIF,),
            ),
            ("portfolio/05", "4-reading-a-what-if", (_WHATIF,)),
            (
                "portfolio/05",
                "5-brinson-attribution-where-did-my-returns-come",
                (_BRINSON,),
            ),
            (
                "portfolio_yfinance/05",
                "2-the-three-candidate-trades-in-english-first",
                (_TRADES,),
            ),
            (
                "portfolio_yfinance/05",
                "3-what-if-diff-weight-space-arithmetic-free-only",
                (_WHATIF,),
            ),
            (
                "portfolio_yfinance/05",
                "4-brinson-fachler-attribution-synthetic-referenc",
                (_BRINSON,),
            ),
            # The smart-money rollup is already a Platform tool; its labelled
            # fixture fallback and the worked examples only illustrate the
            # signal's shape, so they need no capability.
            ("portfolio/04", "4-smart-money-rollup-obb-portfolio-intel-smart-m", ()),
            ("portfolio/04", "5-reading-a-single-name-signal", ()),
            (
                "portfolio_yfinance/04",
                "6-composite-smart-money-reading-fixture-per-stor",
                (),
            ),
        )
    },
    # Reviewed in N05d (#2316): the TechTrade chapters 1-6. Dependency
    # probes are setup and static decision tables or code templates are
    # narrative (no capability); stages that only format a Platform tool's
    # report (validate, tune) need nothing beyond that tool; the workbook
    # finder reads exported files, so it needs the artifacts bridge.
    **{
        (story, stage): (tools, False)
        for story, stage, tools in (
            ("techtrade/01", "1-environment-setup", (_INSTITUTIONAL,)),
            # The pipeline (N05b) plus the 13F summary and SPY market weather.
            (
                "techtrade/01",
                "3-fundamentals-the-analysis-7-phase-pipeline",
                (_SINGLE_NAME, _WEATHER, _INSTITUTIONAL),
            ),
            ("techtrade/02", "5-quick-look-ranking", (_PLANS,)),
            ("techtrade/02", "6-filter-to-today-s-actionable-list", (_PLANS,)),
            (
                "techtrade/02",
                "7-why-does-each-setup-look-good-the-audit-trail",
                (_PLANS,),
            ),
            ("techtrade/02", "10-variation-change-the-risk-knob", (_PLANS,)),
            ("techtrade/03", "1-setup-probe", ()),
            ("techtrade/03", "6-realized-p-l-on-the-simulated-path", (_PNL,)),
            ("techtrade/04", "1-setup-probe-the-soft-dep-check", ()),
            ("techtrade/04", "5-look-at-the-individual-folds", ()),
            ("techtrade/04", "9-now-what-the-decision-table", ()),
            ("techtrade/05", "1-soft-dep-probe-setup", ()),
            ("techtrade/05", "2-the-default-config-baseline", (_CONFIG,)),
            ("techtrade/05", "4-the-current-state-of-techtrade-tuned-json", (_CONFIG,)),
            ("techtrade/05", "6-read-the-tuningreport", ()),
            ("techtrade/05", "7-what-did-tuneta-actually-propose", (_CONFIG,)),
            ("techtrade/05", "9-bypassing-the-auto-load", (_CONFIG,)),
            ("techtrade/05", "10-tuning-multiple-sectors-the-patient-path", ()),
            ("techtrade/06", "1-setup-find-a-workbook-to-audit", ("story:artifacts",)),
            ("techtrade/06", "3-replay-against-actual-forward-bars", (_REPLAY,)),
            ("techtrade/06", "4-summary-statistics", (_REPLAY,)),
            ("techtrade/06", "5-breakdown-by-conviction", (_REPLAY,)),
            ("techtrade/06", "6-the-journal-entry", (_REPLAY,)),
            ("techtrade/06", "7-the-deviation-log-manual", ()),
        )
    },
    # Reviewed in N05e (#2321): what was left under story:analytics needs no
    # new analytics adapter. Environment probes and illustrations run
    # nothing; baskets are run state; recording and free-tier sector maps are
    # provider modes (N10); the paper engine's fills are paper (N09); the
    # exported CSV is an artifact (N07); the timing loops only orchestrate
    # tools their stages already bind.
    **{
        (story, stage): (tools, False)
        for story, stage, tools in (
            *(
                (f"portfolio_yfinance/0{chapter}", "0-before-we-run-anything", ())
                for chapter in range(1, 9)
            ),
            ("portfolio/02", "11-reproducibility-discipline", ()),
            (
                "portfolio_yfinance/03",
                "8-silent-failure-guard-reader-facing-example",
                (),
            ),
            ("techtrade/09", "1-the-validated-plan-from-t4", ()),
            ("portfolio/01", "5-the-through-line-basket", (_STATE,)),
            ("portfolio_yfinance/01", "5-the-through-line-basket", (_STATE,)),
            ("portfolio/03", "1-load-the-basket", (_STATE,)),
            ("portfolio_yfinance/03", "1-load-the-basket", (_STATE,)),
            ("portfolio/04", "2-load-the-basket", (_STATE,)),
            ("portfolio_yfinance/04", "1-load-the-basket", (_STATE,)),
            ("portfolio/08", "4-the-15-etf-basket-table-rationale", (_STATE,)),
            (
                "portfolio_yfinance/08",
                "4-the-16-etf-variant-a-basket-table-rationale",
                (_STATE,),
            ),
            (
                "portfolio/08",
                "9-fortress-swap-bring-your-own-reference-basket",
                (_STATE,),
            ),
            (
                "portfolio_yfinance/08",
                "9-fortress-swap-bring-your-own-reference-basket",
                (_STATE,),
            ),
            ("portfolio/07", "2-scrape-record-the-framework", (_MODES,)),
            (
                "portfolio_yfinance/07",
                "1-scrape-record-freshness-spot-check-optional",
                (_MODES,),
            ),
            (
                "portfolio_yfinance/03",
                "2-naive-sector-view-free-tier-no-look-through",
                (_MODES,),
            ),
            (
                "portfolio_yfinance/03",
                "4-sector-view-with-look-through-the-free-tier-pi",
                (_MODES,),
            ),
            (
                "techtrade/07",
                "5-inspecting-the-csv-fidelity-basket-trading-for",
                ("story:artifacts",),
            ),
            *(
                ("techtrade/08", stage, (_PAPER,))
                for stage in (
                    "4-record-a-full-fill-on-order-1-filled",
                    "5-partial-fill-on-order-2-partial-then-filled",
                    "7-fifo-realized-p-l-a-two-lot-close",
                    "8-loud-rejection-matrix",
                    "9-persistence-across-process-restart",
                )
            ),
            *(
                ("techtrade/09", stage, (_PAPER,))
                for stage in (
                    "4-print-the-operator-s-type-this-at-fidelity-che",
                    "6-simulate-the-operator-s-fidelity-workflow",
                    "7-position-p-l-after-the-fills",
                    "8-partial-close-scenario-take-profit-on-msft",
                    "9-end-of-day-review",
                )
            ),
            # It runs the single-name pipeline among the tools it times.
            (
                "portfolio/07",
                "5-the-monday-morning-routine-end-to-end",
                (_SINGLE_NAME,),
            ),
            (
                "portfolio_yfinance/07",
                "3-timed-end-to-end-run-optional-how-long-does-tr",
                (),
            ),
        )
    },
}

# Planned capabilities whose bridge has shipped, and the tools that serve
# them. Run state (N06, #2216) is the story registry's run tools.
DELIVERED: dict[str, tuple[str, ...]] = {
    "story:state": ("platform:story_run_get", "platform:story_run_checkpoint"),
}

_REPORT = "platform:story_artifact_report"
_TT_WORKBOOK = "platform:story_artifact_techtrade_workbook"
_ART_LIST = "platform:story_artifact_list"
_ART_READ = "platform:story_artifact_read"
# Reviewed in N07 (#2217): the artifact tools each stage needs in place of
# story:artifacts. Every stage that still carries story:artifacts must be
# listed. An empty tuple means the stage renders a panel or prepares the
# notebook's state directory and needs no tool: run state and artifacts live
# server-side.
ARTIFACT_BINDINGS: dict[tuple[str, str], tuple[str, ...]] = {
    **{
        (story, stage): ()
        for story, stage in (
            ("portfolio/01", "0-before-we-run-anything"),
            ("portfolio/01", "6-from-synthetic-basket-to-real-portfolio-option"),
            ("portfolio/02", "0-why-start-with-one-name"),
            ("portfolio/03", "where-we-are-in-sam-s-story"),
            ("portfolio/04", "where-we-are-in-sam-s-story"),
            ("portfolio/05", "where-we-are-in-sam-s-story"),
            ("portfolio/07", "where-we-are-in-sam-s-story"),
            ("portfolio/08", "where-this-notebook-fits"),
        )
    },
    # It loads the basket portfolio/05 left in run state.
    ("portfolio/06", "where-we-are-in-sam-s-story"): (_STATE,),
    # The capstones compose one HTML report from earlier chapters' results.
    ("portfolio/07", "5-the-monday-morning-routine-end-to-end"): (_REPORT,),
    ("portfolio_yfinance/07", "2-end-to-end-reunion-compose-the-track-b-html-re"): (
        _REPORT,
    ),
    # The morning workbook is the TechTrade export, written into the run.
    ("techtrade/01", "4-technical-setup-the-techtrade-engine"): (
        _TT_WORKBOOK,
        _ART_READ,
    ),
    ("techtrade/02", "8-export-to-excel-the-morning-artifact"): (
        _TT_WORKBOOK,
        _ART_READ,
    ),
    # The audit finds an earlier run's workbook, then loads its sheets.
    ("techtrade/06", "1-setup-find-a-workbook-to-audit"): (_ART_LIST,),
    ("techtrade/06", "2-load-the-recommendations"): (_ART_READ,),
    # The paper sink's CSV and workbook are read back; writing them is N09.
    ("techtrade/07", "5-inspecting-the-csv-fidelity-basket-trading-for"): (_ART_READ,),
    ("techtrade/07", "6-the-6-sheet-xlsx-workbook"): (_ART_READ,),
    ("techtrade/09", "3-write-the-artifact"): (_ART_READ,),
}
# A bound artifact tool replaces the platform tool the notebook called.
SUPERSEDED_BY = {"platform:techtrade_export": _TT_WORKBOOK}

KIND_BY_CAPABILITY = {
    "story:paper": "paper",
    "story:jobs": "job",
    "story:artifacts": "artifact",
    "story:state": "state",
}
KIND_PRIORITY = ["paper", "job", "analysis", "retrieval", "artifact", "state"]
STATE_LOADS = re.compile(r"pickle\.loads?\(|\.read_text\(|\.read_bytes\(")
STATE_NAMES = re.compile(r"notebook_state|basket|\bSTATE\b|\bstate\b")
ANALYSIS_TOOL_PREFIXES = (
    "portfolio_intel_",
    "techtrade_",
    "backtest_",
    "story_basket_",
    "story_concentration",
    "story_construction_",
    "story_single_name_",
    "story_brinson_",
    "story_whatif_",
    "story_candidate_",
    "story_market_weather",
    "story_institutional_",
    "story_actionable_",
    "story_round_trip_",
    "story_replay_",
    "story_indicator_",
    "story_run_",
)
PRIVATE_TOOL_PREFIXES = ("portfolio_portfolio_", "portfolio_espp_")
ARTIFACT_TOOL_PREFIXES = ("story_artifact_",)
# Imports whose stage is an opt-in personal-data step, never mandatory.
OPTIONAL_IMPORTS = frozenset({"portfolio_snapshot_importer"})
_HEADING = re.compile(r"^##\s+(.+?)\s*$")


def _imported_capability(module: str) -> str | None:
    matches = [
        prefix
        for prefix in IMPORT_CAPABILITIES
        if module == prefix or module.startswith(prefix + ".")
    ]
    return IMPORT_CAPABILITIES[max(matches, key=len)] if matches else None


def _slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")
    base = base or "stage"
    slug, counter = base, 2
    while slug in used:
        slug, counter = f"{base}-{counter}", counter + 1
    used.add(slug)
    return slug


def _sections(source: NotebookSource, cells: list[dict]) -> list[dict]:
    sections: list[dict] = [{"title": "Setup", "positions": [], "numbered": False}]
    for reference in source.cells:
        cell = cells[reference.position - 1]
        text = (
            "".join(cell["source"])
            if isinstance(cell["source"], list)
            else cell["source"]
        )
        if reference.cell_type == "markdown":
            heading = next(
                (
                    m.group(1)
                    for line in text.splitlines()
                    if (m := _HEADING.match(line))
                ),
                None,
            )
            if heading is not None:
                sections.append(
                    {
                        "title": heading.strip("# ").strip(),
                        "positions": [],
                        "numbered": bool(re.match(r"\d", heading)),
                    }
                )
        sections[-1]["positions"].append(reference.position)
    return [s for s in sections if s["positions"]]


def _capability_kind(name: str) -> str:
    if name in KIND_BY_CAPABILITY:
        return KIND_BY_CAPABILITY[name]
    if name.startswith("platform:"):
        tool = name.split(":", 1)[1]
        if tool.startswith(ARTIFACT_TOOL_PREFIXES):
            return "artifact"
        return "analysis" if tool.startswith(ANALYSIS_TOOL_PREFIXES) else "retrieval"
    return "analysis"


def _stage_needs(
    source: NotebookSource, cells: list[dict], positions: list[int], numbered: bool
) -> tuple[list[str], str, bool]:
    by_position = {reference.position: reference for reference in source.cells}
    capabilities: set[str] = set()
    has_code = reads_state = False
    for position in positions:
        reference = by_position[position]
        if reference.cell_type != "code":
            continue
        has_code = True
        capabilities.update(
            "platform:" + call[4:].replace(".", "_")
            for call in reference.calls
            if call.startswith("obb.")
        )
        for module in reference.imports:
            mapped = _imported_capability(module)
            if mapped:
                capabilities.add(mapped)
        cell = cells[position - 1]
        text = (
            "".join(cell["source"])
            if isinstance(cell["source"], list)
            else cell["source"]
        )
        if STATE_LOADS.search(text) and STATE_NAMES.search(text):
            reads_state = True
        # Classified defects are reviewed (narrative-in-code needs nothing);
        # only an unclassified parse failure still needs a binding decision.
        if any(
            d.position == position and d.classification is None
            for d in source.diagnostics
        ):
            capabilities.add("story:binding_review")
    if not has_code:
        return [], "narrative", False
    if not capabilities and numbered:
        capabilities.add("story:analytics")
    if not capabilities:
        return [], "setup", reads_state
    return sorted(capabilities), _stage_kind(capabilities), reads_state


def _stage_kind(capabilities: set[str]) -> str:
    if not capabilities:
        return "narrative"
    kinds = {_capability_kind(c) for c in capabilities}
    return next(k for k in KIND_PRIORITY if k in kinds)


def _apply_binding(story_id: str, stage_id: str, capabilities: list[str]) -> list[str]:
    binding = REVIEWED_BINDINGS.get((story_id, stage_id))
    if binding is None:
        return capabilities
    tools, residual = binding
    bound = set(capabilities) | set(tools)
    if not residual:
        bound.discard("story:analytics")
    return sorted(bound)


def _bind_artifacts(story_id: str, stage_id: str, capabilities: list[str]) -> list[str]:
    if "story:artifacts" not in capabilities:
        return capabilities
    tools = ARTIFACT_BINDINGS.get((story_id, stage_id))
    if tools is None:
        raise SystemExit(
            f"{story_id} {stage_id} needs story:artifacts but has no reviewed"
            " artifact binding"
        )
    bound = (set(capabilities) - {"story:artifacts"}) | set(tools)
    bound -= {old for old, new in SUPERSEDED_BY.items() if new in bound}
    return sorted(bound)


def _resolve_delivered(capabilities: list[str]) -> list[str]:
    resolved: set[str] = set()
    for name in capabilities:
        resolved.update(DELIVERED.get(name, (name,)))
    return sorted(resolved)


def unused_bindings(manifests: list[dict]) -> list[tuple[str, str]]:
    """Return reviewed bindings whose stage no longer exists."""
    present = {(m["story_id"], s["id"]) for m in manifests for s in m["stages"]}
    return sorted((set(REVIEWED_BINDINGS) | set(ARTIFACT_BINDINGS)) - present)


def _is_optional(source: NotebookSource, positions: list[int]) -> bool:
    wanted = set(positions)
    return any(
        module.split(".")[0] in OPTIONAL_IMPORTS
        for cell in source.cells
        if cell.position in wanted
        for module in cell.imports
    )


def build_manifest(source: NotebookSource, previous_story: str | None) -> dict:
    """Derive one manifest dictionary from a notebook's inventory."""
    notebook = json.loads(
        (REPO_ROOT / "notebooks" / source.path).read_text(encoding="utf-8")
    )
    cells = notebook["cells"]
    used: set[str] = set()
    stages: list[dict] = []
    limitations = [
        "Stages follow the notebook's section order; data dependencies within a "
        "story are modelled as an ordered chain until N04 binds exact outputs.",
    ]
    for section in _sections(source, cells):
        capabilities, kind, reads_state = _stage_needs(
            source, cells, section["positions"], section["numbered"]
        )
        stage_id = _slug(section["title"], used)
        reviewed = _apply_binding(source.story_id, stage_id, capabilities)
        reviewed = _bind_artifacts(source.story_id, stage_id, reviewed)
        if reviewed != capabilities:
            capabilities, kind = reviewed, _stage_kind(set(reviewed))
        inputs = []
        if reads_state and previous_story is not None:
            inputs.append(
                {
                    "name": "prior_state",
                    "from_story": previous_story,
                    "output": "story_state",
                }
            )
        outputs = (
            ["story_state"] if "story:state" in capabilities else [f"{stage_id}-result"]
        )
        capabilities = _resolve_delivered(capabilities)
        stages.append(
            {
                "id": stage_id,
                "title": section["title"],
                "kind": kind,
                "cells": section["positions"],
                "depends_on": [stages[-1]["id"]] if stages else [],
                "capabilities": capabilities,
                "inputs": inputs,
                "outputs": outputs,
                "optional": _is_optional(source, section["positions"]),
            }
        )
    if any(stage["inputs"] for stage in stages):
        limitations.append(
            "Cross-chapter state is attributed to the previous chapter; N06 binds "
            "the exact state keys."
        )
    if source.diagnostics:
        limitations.append(
            "Source diagnostics (classified ones need no capability): "
            + ", ".join(
                f"cell {d.position} ({d.classification or d.kind})"
                for d in source.diagnostics
            )
        )
    return {
        "schema_version": 1,
        "story_id": source.story_id,
        "family": source.family,
        "variant": source.variant,
        "notebook_path": f"notebooks/{source.path}",
        "source_sha256": source.source_sha256,
        "stages": stages,
        "acceptance_cases": [f"{source.story_id}:fixture", f"{source.story_id}:replay"],
        "limitations": limitations,
    }


async def _tool_schemas(names: set[str]) -> dict[str, str]:
    from openbb_core.api.rest_api import app
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings

    settings = MCPSettings.model_validate(
        {
            "api_prefix": "/api/v1",
            "capability_profile": "portfolio-ops",
            "default_tool_categories": ["all"],
            "default_skills_dir": None,
        }
    )
    server = create_mcp_server(settings, app, auth=("catalog-builder", "x" * 32))
    schemas = {}
    for tool in await server.list_tools():
        if tool.name in names:
            canonical = json.dumps(
                tool.parameters or {}, sort_keys=True, separators=(",", ":")
            )
            schemas[tool.name] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    missing = names - set(schemas)
    if missing:
        raise SystemExit(f"tools not emitted by portfolio-ops: {sorted(missing)}")
    return schemas


def build_catalog(manifests: list[dict]) -> dict:
    """Pin every referenced platform tool and list the planned capabilities."""
    referenced = {
        name
        for manifest in manifests
        for stage in manifest["stages"]
        for name in stage["capabilities"]
    }
    tools = {
        name.split(":", 1)[1] for name in referenced if name.startswith("platform:")
    }
    schemas = asyncio.run(_tool_schemas(tools))
    entries: dict[str, dict] = {}
    for tool in sorted(tools):
        if tool.startswith(ARTIFACT_TOOL_PREFIXES):
            access = "artifact"
        elif tool.startswith(ANALYSIS_TOOL_PREFIXES):
            access = "analysis"
        elif tool.startswith(PRIVATE_TOOL_PREFIXES):
            access = "private_read"
        else:
            access = "provider_read"
        entries[f"platform:{tool}"] = {
            "status": "available",
            "ref": {
                "server": "platform",
                "tool": tool,
                "schema_sha256": schemas[tool],
                "access": access,
            },
        }
    for name, (access, issue, summary) in sorted(PLANNED.items()):
        if name in referenced:
            entries[name] = {
                "status": "planned",
                "access": access,
                "owner_issue": issue,
                "summary": summary,
            }
    return {"schema_version": 1, "entries": entries}


def main() -> int:
    """Regenerate manifests and the catalog from the tracked notebooks."""
    sources = inventory_notebooks(REPO_ROOT / "notebooks")
    previous: dict[str, str] = {}
    manifests = []
    for source in sources:
        folder = source.story_id.split("/")[0]
        manifests.append(build_manifest(source, previous.get(folder)))
        previous[folder] = source.story_id
    stale = unused_bindings(manifests)
    if stale:
        raise SystemExit(f"reviewed bindings match no stage: {stale}")
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        path = STORIES_DIR / (manifest["story_id"].replace("/", "__") + ".json")
        path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    catalog = build_catalog(manifests)
    (STORIES_DIR / "capability_catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    summary = f"wrote {len(manifests)} manifests and {len(catalog['entries'])} catalog entries"
    print(summary)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
