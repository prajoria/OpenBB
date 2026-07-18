"""Router for obb.fmp_trading.report and obb.fmp_trading.replay (P5.1/P5.3).

Bindings for the two post-session tools. Both return bare ``OBBject``
(per the Critical Design Constraint carried from Phase 1 — the static
package builder emits parametrized model names without importing them,
so any ``OBBject[X]`` return annotation causes a ``NameError`` on first
namespace access).

Security posture (security-review round 1 fold-in for findings #1 + #2):

* ``report()`` output_dir is JAILED under a configurable reports root
  (see ``reporting.report._reports_root``). Overwrites require the
  explicit ``overwrite=True`` flag.
* ``replay()`` accepts a ``session_id`` (server-side path resolution
  via ``session_journal_path`` — includes path-traversal guards from
  P5.0) rather than a raw filesystem path. This removes the arbitrary-
  file-read attack surface entirely. The ``journal_path`` parameter
  is deliberately NOT exposed on the router — operators who need to
  point at an arbitrary journal file can import
  ``openbb_fmp_trading.reporting.replay.replay`` directly at their
  own risk.

Read-only surface: neither ``report()`` nor ``replay()`` writes to
``state_store`` or touches ``broker.submit``. They're pure post-session
analysis. That's why Phase 5 does NOT expose them via MCP — the MCP
surface's read-only guarantee is currently defined at the "no
mutation" level; ``report()`` writes files (to the operator's disk)
even after jailing, which is a different privilege class.
"""

# from __future__ import annotations  # removed: breaks FastAPI OBBject resolution (#824)

from pathlib import Path
from typing import Literal

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="")


@router.command(
    methods=["POST"],
    examples=[
        APIEx(
            description="Render all formats for a specific session.",
            parameters={"session_id": "s20260101120000"},
        ),
        APIEx(
            description="Render only XLSX; skip the LLM narrative.",
            parameters={
                "session_id": "s20260101120000",
                "format": "xlsx",
                "include_agent_narrative": False,
            },
        ),
    ],
)
def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: str | None = None,
    include_agent_narrative: bool = True,
    overwrite: bool = False,
) -> OBBject:
    """Render session artifacts as MD + XLSX + JSON. PRD §4.6.

    Args:
        session_id: The session to render (typically ``s%Y%m%d%H%M%S``).
        format: Which formats to emit — ``md``, ``xlsx``, ``json``, or ``all``.
        output_dir: Target directory as a string (converted to Path).
            MUST resolve inside the reports jail (see
            ``FMP_TRADING_REPORTS_ROOT`` env var, default
            ``Analysis/exports/``). Defaults to
            ``<reports_root>/daytrade_<date>/``.
        include_agent_narrative: When True and the journal has an
            EndOfDayReportEvent with briefing_md_content, use that
            verbatim for the MD path.
        overwrite: Default False — refuses to clobber existing files.
            Pass True to regenerate.

    Returns:
        Bare ``OBBject`` whose ``results`` is a ``ReportManifest.model_dump()``.
    """
    from openbb_fmp_trading.reporting.report import report as _report

    manifest = _report(
        session_id=session_id,
        format=format,
        output_dir=Path(output_dir) if output_dir else None,
        include_agent_narrative=include_agent_narrative,
        overwrite=overwrite,
    )
    return OBBject(results=manifest.model_dump(mode="json"))


@router.command(
    methods=["POST"],
    examples=[
        APIEx(
            description="Full replay of a specific session.",
            parameters={"session_id": "s20260101120000"},
        ),
        APIEx(
            description="Replay only the first 100 ticks.",
            parameters={
                "session_id": "s20260101120000",
                "from_tick": 0,
                "to_tick": 100,
            },
        ),
    ],
)
def replay(
    session_id: str,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> OBBject:
    """Deterministic journal reconstruction by session_id. PRD §4.1.

    Security note (finding #2): this router deliberately takes
    ``session_id`` — not a raw ``journal_path`` — so the journal path
    is derived server-side via the P5.0 traversal-guarded resolver.
    Operators who need to point at an arbitrary journal file can call
    ``openbb_fmp_trading.reporting.replay.replay`` directly in Python.

    Args:
        session_id: The session to replay (typically ``s%Y%m%d%H%M%S``).
        from_tick: 0-based tick index to start from (inclusive).
        to_tick: 0-based tick index to stop before (exclusive); None = all.

    Returns:
        Bare ``OBBject`` whose ``results`` is a ``ReplayResult.model_dump()``.
    """
    from openbb_fmp_trading.reporting.journal_reader import session_journal_path
    from openbb_fmp_trading.reporting.replay import replay as _replay

    journal_path = session_journal_path(session_id)
    result = _replay(
        journal_path,
        from_tick=from_tick,
        to_tick=to_tick,
    )
    return OBBject(results=result.model_dump(mode="json"))
