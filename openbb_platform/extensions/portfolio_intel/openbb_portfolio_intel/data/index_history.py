"""Index-constituent history refresh + cache (#543).

PRD §14.2 dependency for Brinson attribution — the Brinson-Fachler math
(#559) needs to know **what was in the benchmark on each historical
date** so it can compute per-sector returns for the benchmark side of
the attribution decomposition.

This module ships:

1. A **thin refresh wrapper** over ``obb.index.constituents(historical=
   True, provider="fmp_cached")`` that walks a fixed list of indices
   and caches the results in-memory (persistent cache is #516's
   scope).
2. A **point-in-time reconstitution helper** that answers "what was
   in SP500 on date D?" by folding the historical adds/removes plus
   the current membership.
3. A **nightly refresh entry point** (``refresh_all()``) that a
   scheduler can call to keep the local cache current.

## Scope + gaps

- **fmp_cached supports sp500, dowjones, nasdaq today** — verified live
  during this issue's work; 503 sp500 rows + 1523 historical rows on
  probe.
- **IWM (Russell 2000) and ACWI (MSCI ACWI) are NOT in fmp_cached** —
  the query params ``Literal["dowjones","sp500","nasdaq"]``. Filed as
  ``area:fmp-cached-gap`` follow-up; this module raises ``ValueError``
  on those symbols today. Downstream #559 uses sp500 as its default
  benchmark, so this doesn't block Brinson from shipping.
- **Persistent cache (#516) is out of scope.** In-memory only for
  this cut; a follow-up wires it into ``portfolio_intel_cache``.
- **No survivorship-bias correction.** Historical constituents include
  removed names (per FMP `historical-*-constituent` semantics), so
  point-in-time reconstitution is survivorship-free by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from threading import Lock
from typing import Any, Literal

# Indices fmp_cached exposes today. Extend when the fmp-cached-gap
# follow-up ships IWM + ACWI.
SUPPORTED_INDICES: tuple[str, ...] = ("sp500", "dowjones", "nasdaq")

# Index symbols mentioned in PRD §14.2 but not yet available in
# fmp_cached — attempting to refresh these raises ValueError with a
# pointer to the gap issue.
UNSUPPORTED_INDICES: tuple[str, ...] = ("iwm", "acwi")

IndexSymbol = Literal["sp500", "dowjones", "nasdaq"]


@dataclass(frozen=True)
class ConstituentRow:
    """One row of the constituent snapshot (current or historical).

    Shape matches the fields we actually use downstream — the fmp_cached
    response has more fields (cik, founded, headquarter) but Brinson
    only needs (symbol, sector, date_added, removed_symbol, date,
    reason).
    """

    symbol: str
    sector: str | None
    date_added: date | None
    removed_symbol: str | None
    event_date: date | None
    reason: str | None


@dataclass
class IndexHistorySnapshot:
    """In-memory cache for one (index_symbol, fetched-at) tuple.

    ``current`` is the current-membership rollcall (symbols in the
    index today, with their sector). ``historical`` is the
    add/remove event log — a chronological sequence of changes.

    Together, ``current`` + ``historical`` let ``point_in_time`` (below)
    reconstitute membership as of any past date without survivorship
    bias.
    """

    index_symbol: str
    fetched_at: date
    current: list[ConstituentRow] = field(default_factory=list)
    historical: list[ConstituentRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# In-memory cache (thread-safe)
# ---------------------------------------------------------------------------

_CACHE: dict[str, IndexHistorySnapshot] = {}
_CACHE_LOCK = Lock()


def _fetch_constituents(index_symbol: str, historical: bool) -> list[dict[str, Any]]:
    """Fetch from ``obb.index.constituents``. Seam: unit tests patch this.

    Returns a list of ``.model_dump()`` dicts so tests can build
    fixtures without importing the OpenBB model classes.
    """
    from openbb import obb  # pylint: disable=import-outside-toplevel

    resp = obb.index.constituents(
        index_symbol, provider="fmp_cached", historical=historical
    )
    return [r.model_dump() for r in resp.results]


def _row_from_dict(raw: dict[str, Any]) -> ConstituentRow:
    """Coerce a fmp_cached response row → our narrow ConstituentRow."""
    return ConstituentRow(
        symbol=str(raw.get("symbol") or ""),
        sector=raw.get("sector"),
        date_added=(
            raw.get("date_added") if isinstance(raw.get("date_added"), date) else None
        ),
        removed_symbol=raw.get("removed_symbol"),
        event_date=raw.get("date") if isinstance(raw.get("date"), date) else None,
        reason=raw.get("reason"),
    )


def refresh(index_symbol: str, *, today: date) -> IndexHistorySnapshot:
    """Refresh the cache for one index and return the snapshot.

    Parameters
    ----------
    index_symbol
        One of :data:`SUPPORTED_INDICES`. Raises ``ValueError`` on
        anything else (including :data:`UNSUPPORTED_INDICES`, with a
        pointer to the fmp-cached-gap issue).
    today
        The refresh date. Passed in (not derived) so this function is
        deterministic and testable.

    Returns
    -------
    IndexHistorySnapshot
        Immutable-ish (dataclass) snapshot. Also written to the
        module-level cache under ``index_symbol``.
    """
    idx = index_symbol.lower()
    if idx in UNSUPPORTED_INDICES:
        raise ValueError(
            f"{idx!r} is documented in PRD §14.2 but not yet available in "
            "fmp_cached. File under `area:fmp-cached-gap` before consumers "
            "can use it (#543)."
        )
    if idx not in SUPPORTED_INDICES:
        raise ValueError(
            f"{idx!r} is not a supported index. " f"Supported: {SUPPORTED_INDICES}."
        )

    warnings: list[str] = []

    try:
        current_raw = _fetch_constituents(idx, historical=False)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"current fetch failed for {idx}: {type(exc).__name__}: {exc}")
        current_raw = []

    try:
        historical_raw = _fetch_constituents(idx, historical=True)
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f"historical fetch failed for {idx}: {type(exc).__name__}: {exc}"
        )
        historical_raw = []

    snapshot = IndexHistorySnapshot(
        index_symbol=idx,
        fetched_at=today,
        current=[_row_from_dict(r) for r in current_raw],
        historical=[_row_from_dict(r) for r in historical_raw],
        warnings=warnings,
    )
    with _CACHE_LOCK:
        _CACHE[idx] = snapshot
    return snapshot


def refresh_all(*, today: date) -> dict[str, IndexHistorySnapshot]:
    """Refresh every supported index. Nightly-job entry point.

    Per-index failures do not abort the walk — each snapshot's
    ``warnings`` carries the reason, matching the posture used by
    the events / smart-money routes.
    """
    return {idx: refresh(idx, today=today) for idx in SUPPORTED_INDICES}


def get_snapshot(index_symbol: str) -> IndexHistorySnapshot | None:
    """Return the cached snapshot for ``index_symbol``, or None."""
    return _CACHE.get(index_symbol.lower())


def clear_cache() -> None:
    """Clear the in-memory cache. Used by tests + a manual reset."""
    with _CACHE_LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Point-in-time reconstitution
# ---------------------------------------------------------------------------


def point_in_time(snapshot: IndexHistorySnapshot, as_of: date) -> set[str]:
    """Reconstitute index membership as of ``as_of``.

    Algorithm (survivorship-free):

    1. Start with the current membership (``snapshot.current``).
    2. Walk the historical adds/removes in reverse chronological order:
       for every event whose ``date`` is AFTER ``as_of`` (i.e. the
       event hadn't happened yet at that time), undo it:
         - if a symbol was added after ``as_of``, remove it from the set.
         - if a symbol was removed after ``as_of``, add it back to the set.
    3. Return the resulting set of symbols.

    Complexity: O(N_history) — linear pass. Callers who need the
    reconstituted set for many dates should batch through the history
    once and materialize per-date sets themselves.

    Parameters
    ----------
    snapshot
        A cached snapshot from :func:`refresh` / :func:`refresh_all`.
    as_of
        The historical date to reconstitute for.

    Returns
    -------
    set[str]
        Set of symbols that were index members on ``as_of``.
    """
    if as_of > snapshot.fetched_at:
        raise ValueError(
            f"as_of {as_of} is after snapshot.fetched_at {snapshot.fetched_at}; "
            "cannot reconstitute future membership."
        )
    members = {row.symbol for row in snapshot.current if row.symbol}
    for event in snapshot.historical:
        # An event applies at event.event_date. If event.event_date > as_of,
        # the event hadn't happened yet at as_of — undo it.
        event_date = event.event_date
        if event_date is None or event_date <= as_of:
            continue
        if event.symbol:
            members.discard(event.symbol)
        if event.removed_symbol:
            members.add(event.removed_symbol)
    return members
