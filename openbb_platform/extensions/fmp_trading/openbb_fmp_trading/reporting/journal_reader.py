"""Journal reading + shared metrics helper (P5.0 / D6).

The single source of truth for two questions:

  1. Where does session_id map to on disk? -> :func:`session_journal_path`
  2. How do we turn a stream of JournalEvents into SessionMetrics?
     -> :func:`compute_metrics_from_events` (shared with PostCloseAgentTurn)

Both ``report()`` and ``replay()`` — and the P3.2 post-close narrator
path that was already computing metrics inline — call these functions.
No duplicated event-tallying logic anywhere else in the extension.

Uses ``openbb_core_journal.JournalReader`` (verified P5.0 Step 0) as the
sole NDJSON parser. Note: ``JournalReader.stream()`` **silently skips**
malformed lines (logs at WARN). That's the shipped Phase 1 contract; we
don't try to change it here. If callers need strict parsing they can
open the file and parse lines themselves.

Security (review S4): :func:`session_journal_path` rejects path-
traversal attempts BEFORE touching disk (denies ``/``, ``\``, ``..``,
``:``, leading ``.``, empty), then re-asserts ``resolved.is_relative_to
(root)`` AFTER resolution to catch Windows drive-relative or symlink
attacks the character blocklist missed.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from openbb_fmp_trading.models.report import SessionMetrics

logger = logging.getLogger(__name__)

# All journals live here unless the operator overrides. Matches the
# on-disk layout the JournalWriter uses today (Phase 1 J2).
DEFAULT_JOURNAL_ROOT = Path.home() / ".openbb_platform" / "fmp_trading" / "journals"

# Substrings rejected in session_id path resolution.
# ``:`` rejected per review S4 — Windows drive-relative names like
# ``C:foo`` bypass root when joined with pathlib.
_FORBIDDEN_SUBSTRINGS = ("/", "\\", "..", ":")


def session_journal_path(session_id: str, root: Path | None = None) -> Path:
    """Resolve ``session_id`` -> on-disk path with path-traversal guards.

    Rejects (before touching disk):

    * empty ``session_id``
    * starts with ``.``
    * contains ``/`` or ``\\`` or ``..`` or ``:``

    After resolution: assert the resolved path is inside ``root``. Belt
    and suspenders — the character list should catch it first, but the
    ``is_relative_to`` check is the actual security invariant.

    Args:
        session_id: identifier from ``IntradaySession`` (typically
            ``s%Y%m%d%H%M%S``).
        root: journal root (defaults to :data:`DEFAULT_JOURNAL_ROOT`).

    Returns:
        ``<root>/<session_id>.ndjson``, guaranteed to be inside root.

    Raises:
        ValueError: on any of the pre-resolution or post-resolution
            checks failing.
    """
    if not session_id or session_id.startswith("."):
        raise ValueError(f"invalid session_id: {session_id!r}")
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in session_id:
            raise ValueError(
                f"invalid session_id (contains {bad!r}): {session_id!r}"
            )
    resolved_root = root or DEFAULT_JOURNAL_ROOT
    candidate = resolved_root / f"{session_id}.ndjson"
    # Post-resolution check (S4). is_relative_to is Python 3.9+; the
    # extension floor is 3.10 (per pyproject.toml) so this is available.
    try:
        candidate.resolve().relative_to(resolved_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"session_id {session_id!r} resolves outside journal root — "
            "likely a Windows drive-relative or symlink attack"
        ) from exc
    return candidate


def read_journal_file(path: Path) -> Iterable:
    """Yield JournalEvent objects from an NDJSON file, in write order.

    Delegates to ``openbb_core_journal.JournalReader.stream()``. Per that
    shipped contract:

    * Malformed lines are skipped and logged at WARN (not raised).
    * :class:`~openbb_core_journal.SchemaVersionError` propagates on a
      future-versioned event.
    * ``FileNotFoundError`` propagates on missing files (opens fails).
    """
    from openbb_core_journal import JournalReader

    yield from JournalReader(Path(path)).stream()


def read_session_events(session_id: str, root: Path | None = None) -> Iterable:
    """Yield events for a ``session_id`` — thin shim over
    :func:`read_journal_file` with :func:`session_journal_path` resolution."""
    yield from read_journal_file(session_journal_path(session_id, root=root))


def compute_metrics_from_events(events) -> SessionMetrics:
    """Extract SessionMetrics from an event iterable.

    Extracted from ``PostCloseAgentTurn._compute_metrics_from_journal``
    (P3.2). Same core logic; both callers import from here now so
    there's exactly one place to fix if the metrics rollup changes shape.

    Behavior (with review-fold-in for finding #4 pnl_source + #6 cost drag):

    * ``FillEvent`` counted; ``realized_pnl`` summed from fill payloads (Decimal).
    * ``FillEvent`` ``commission`` + ``slippage`` aggregated (review finding #6).
    * ``OrderEvent`` counted.
    * ``VetoEvent`` counted, aggregated by ``gate`` (falls back to ``reason_code``).
    * ``SessionEndEvent.payload.realized_pnl`` OVERRIDES the fill-summed value
      AND sets ``pnl_source='authoritative_session_end'`` — the operator
      can see whether the number is authoritative or reconstructed.
    * If no ``SessionEndEvent`` + we saw at least one fill:
      ``pnl_source='summed_from_fills'`` (reconstructed — may disagree
      with true tally if the session was truncated).
    * If no fills and no ``session_end``: ``pnl_source='empty'``.
    """
    veto_counts: dict[str, int] = {}
    fill_count = 0
    order_count = 0
    realized_pnl_from_fills = Decimal("0")
    total_commissions = Decimal("0")
    total_slippage = Decimal("0")
    authoritative_pnl: Decimal | None = None

    for e in events:
        et = getattr(e, "event_type", None)
        payload = getattr(e, "payload", {}) or {}
        if et == "order":
            order_count += 1
        elif et == "fill":
            fill_count += 1
            fp = payload.get("realized_pnl")
            if fp is not None:
                try:
                    realized_pnl_from_fills += Decimal(str(fp))
                except (TypeError, ValueError, InvalidOperation) as exc:
                    # bd-9nd.11: WARN so a bad row surfaces in logs.
                    # Silent swallow was hard to trace during P&L
                    # reconciliation ("why does the summed_from_fills
                    # source not match the fill count?").
                    logger.warning(
                        "compute_metrics: skipping unparseable "
                        "realized_pnl=%r on fill event at ts=%s (%s)",
                        fp, getattr(e, "ts", "?"), exc,
                    )
            # Review finding #6: aggregate cost drag
            comm = payload.get("commission")
            if comm is not None:
                try:
                    total_commissions += Decimal(str(comm))
                except (TypeError, ValueError, InvalidOperation) as exc:
                    logger.warning(
                        "compute_metrics: skipping unparseable "
                        "commission=%r on fill event at ts=%s (%s)",
                        comm, getattr(e, "ts", "?"), exc,
                    )
            slip = payload.get("slippage")
            if slip is not None:
                try:
                    total_slippage += Decimal(str(slip))
                except (TypeError, ValueError, InvalidOperation) as exc:
                    logger.warning(
                        "compute_metrics: skipping unparseable "
                        "slippage=%r on fill event at ts=%s (%s)",
                        slip, getattr(e, "ts", "?"), exc,
                    )
        elif et == "veto":
            gate = payload.get("gate") or payload.get("reason_code") or "unknown"
            veto_counts[gate] = veto_counts.get(gate, 0) + 1
        elif et == "session_end":
            rp = payload.get("realized_pnl")
            if rp is not None:
                try:
                    authoritative_pnl = Decimal(str(rp))
                except (TypeError, ValueError, InvalidOperation) as exc:
                    # session_end is authoritative — losing this to a
                    # parse error means we silently fall back to
                    # 'summed_from_fills' with no signal. WARN loudly.
                    logger.warning(
                        "compute_metrics: session_end realized_pnl=%r "
                        "at ts=%s unparseable (%s); falling back to "
                        "summed_from_fills",
                        rp, getattr(e, "ts", "?"), exc,
                    )

    # Provenance: review finding #4 — operator sees WHICH source produced
    # the number so a "we crashed mid-session" report doesn't look like a
    # "we're at zero" report.
    if authoritative_pnl is not None:
        realized_pnl = authoritative_pnl
        pnl_source: str = "authoritative_session_end"
    elif fill_count > 0:
        realized_pnl = realized_pnl_from_fills
        pnl_source = "summed_from_fills"
    else:
        realized_pnl = Decimal("0")
        pnl_source = "empty"

    return SessionMetrics(
        realized_pnl=realized_pnl,
        pnl_source=pnl_source,
        total_commissions=total_commissions,
        total_slippage=total_slippage,
        veto_counts_by_gate=veto_counts,
        fill_count=fill_count,
        order_count=order_count,
    )


__all__ = [
    "DEFAULT_JOURNAL_ROOT",
    "compute_metrics_from_events",
    "read_journal_file",
    "read_session_events",
    "session_journal_path",
]
