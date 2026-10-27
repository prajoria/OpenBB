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
    ("portfolio_yfinance/08", "6-risk-metrics-hhi-effective-n-free-tier-sector"): (
        (_CONCENTRATION,),
        True,
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
    # These stages also do other local work: the SEC 13F fallback and SPY
    # regime statistics, and an end-to-end timing run over several engines.
    ("techtrade/01", "3-fundamentals-the-analysis-7-phase-pipeline"): (
        (_SINGLE_NAME,),
        True,
    ),
    ("portfolio/07", "5-the-monday-morning-routine-end-to-end"): (
        (_SINGLE_NAME,),
        True,
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
}

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
)
PRIVATE_TOOL_PREFIXES = ("portfolio_portfolio_", "portfolio_espp_")
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


def unused_bindings(manifests: list[dict]) -> list[tuple[str, str]]:
    """Return reviewed bindings whose stage no longer exists."""
    present = {(m["story_id"], s["id"]) for m in manifests for s in m["stages"]}
    return sorted(set(REVIEWED_BINDINGS) - present)


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
        if tool.startswith(ANALYSIS_TOOL_PREFIXES):
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
