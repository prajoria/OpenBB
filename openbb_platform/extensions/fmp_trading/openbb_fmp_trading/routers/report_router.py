"""Router for obb.fmp_trading.report and obb.fmp_trading.replay (P5.1/P5.3).

Bindings for the two post-session tools. Both return bare ``OBBject``
(per the Critical Design Constraint carried from Phase 1 — the static
package builder emits parametrized model names without importing them,
so any ``OBBject[X]`` return annotation causes a ``NameError`` on first
namespace access).

Read-only surface: neither ``report()`` nor ``replay()`` writes to
``state_store`` or touches ``broker.submit``. They're pure post-session
analysis. That's why Phase 5 does NOT expose them via MCP — the MCP
surface's read-only guarantee is currently defined at the "no
mutation" level; report/replay both write files (to the operator's
disk), which is a different privilege class. MCP exposure would need
a path-jail defense (deferred to a follow-up bead per design §6.5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="")


@router.command(methods=["POST"])
def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: str | None = None,
    include_agent_narrative: bool = True,
) -> OBBject:
    """Render session artifacts as MD + XLSX + JSON. PRD §4.6.

    Args:
        session_id: The session to render (typically ``s%Y%m%d%H%M%S``).
        format: Which formats to emit — ``md``, ``xlsx``, ``json``, or ``all``.
        output_dir: Target directory as a string (converted to Path).
            Defaults to ``Analysis/exports/daytrade_<date>/``.
        include_agent_narrative: When True and the journal has an
            EndOfDayReportEvent with briefing_md_content, use that
            verbatim for the MD path.

    Returns:
        Bare ``OBBject`` whose ``results`` is a ``ReportManifest.model_dump()``.
    """
    from openbb_fmp_trading.reporting.report import report as _report

    manifest = _report(
        session_id=session_id,
        format=format,
        output_dir=Path(output_dir) if output_dir else None,
        include_agent_narrative=include_agent_narrative,
    )
    return OBBject(results=manifest.model_dump(mode="json"))


@router.command(methods=["POST"])
def replay(
    journal_path: str,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> OBBject:
    """Deterministic journal reconstruction. PRD §4.1.

    P5.3 wires the actual implementation. This binding just delegates.

    Args:
        journal_path: On-disk NDJSON journal to replay.
        from_tick: 0-based tick index to start from (inclusive).
        to_tick: 0-based tick index to stop before (exclusive); None = all.

    Returns:
        Bare ``OBBject`` whose ``results`` is a ``ReplayResult.model_dump()``.
    """
    from openbb_fmp_trading.reporting.replay import replay as _replay

    result = _replay(
        Path(journal_path),
        from_tick=from_tick,
        to_tick=to_tick,
    )
    return OBBject(results=result.model_dump(mode="json"))
