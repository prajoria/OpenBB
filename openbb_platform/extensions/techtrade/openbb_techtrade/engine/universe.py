"""Segment universe resolver: GICS segment -> concrete symbol universe (PRD §10, §20 Q3).

The second pipeline stage turns each :class:`~openbb_techtrade.models.SegmentConfig`
(produced by the GICS segment map, issue #68) into a concrete list of constituent
tickers. Three universe sources are supported, switchable per segment via
``SegmentConfig.universe_source`` and reflecting the PRD §20 Q3 decision:

* ``etf_holdings`` (default) -- expand the segment's benchmark sector-SPDR ETF into
  its live holdings via ``obb.etf.holdings`` (``fmp_cached``).
* ``constituent_list`` -- use a caller-supplied static list of symbols.
* ``screener`` -- query ``obb.equity.screener`` (``fmp_cached``) filtered to the
  segment's sector.

Every live data call sits behind an injectable fetcher parameter so the unit tests
run fully offline with fakes (no API key, no network). ``openbb`` is imported lazily
inside the default fetchers only, keeping module import light. Resolved universes are
checked for a plausible membership count (PRD §10 "membership-count sanity").
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS, list_segments
from openbb_techtrade.models import SegmentConfig

# GICS sector name -> FMP equity-screener ``sector`` literal (PRD §10, §20 Q3).
# Used by the live screener default to translate a canonical GICS segment into the
# sector token understood by ``obb.equity.screener`` (fmp_cached). Keys mirror
# :data:`GICS_SECTOR_ETFS` exactly.
_GICS_TO_FMP_SECTOR: dict[str, str] = {
    "Information Technology": "technology",
    "Financials": "financial_services",
    "Energy": "energy",
    "Health Care": "healthcare",
    "Consumer Discretionary": "consumer_cyclical",
    "Consumer Staples": "consumer_defensive",
    "Industrials": "industrials",
    "Materials": "basic_materials",
    "Real Estate": "real_estate",
    "Utilities": "utilities",
    "Communication Services": "communication_services",
}


def _clean_symbols(symbols: Iterable[str | None]) -> list[str]:
    """Drop falsy symbols and de-duplicate, preserving first-seen order.

    Parameters
    ----------
    symbols : Iterable[str | None]
        Raw constituent symbols as returned by a fetcher; may contain ``None`` or
        empty strings (cash / unmapped holding rows) and duplicates.

    Returns
    -------
    list[str]
        The non-empty symbols in first-seen order, each appearing once.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for symbol in symbols:
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        cleaned.append(symbol)
    return cleaned


def _default_holdings_fetcher(etf_symbol: str) -> list[str]:
    """Fetch an ETF's constituent symbols via ``obb.etf.holdings`` (fmp_cached).

    This is the live default for ``universe_source == "etf_holdings"``. ``openbb`` is
    imported lazily so importing this module never pulls in the platform.

    Parameters
    ----------
    etf_symbol : str
        Benchmark ETF symbol to expand (e.g. ``"XLK"``).

    Returns
    -------
    list[str]
        Constituent symbols, with cash / unmapped (``None``) rows filtered out.
    """
    from openbb import obb

    result = obb.etf.holdings(symbol=etf_symbol, provider="fmp_cached")
    rows = result.results or []
    return [row.symbol for row in rows if getattr(row, "symbol", None)]


def _default_screener_fetcher(segment: str) -> list[str]:
    """Fetch a segment's symbols via ``obb.equity.screener`` (fmp_cached).

    Live default for ``universe_source == "screener"``. The GICS segment name is
    translated to the FMP screener ``sector`` token via :data:`_GICS_TO_FMP_SECTOR`
    before querying. ``openbb`` is imported lazily.

    Parameters
    ----------
    segment : str
        GICS sector name (must be one of :data:`GICS_SECTOR_ETFS`).

    Returns
    -------
    list[str]
        Symbols returned by the sector-filtered screener.

    Raises
    ------
    ValueError
        If ``segment`` is not a known GICS sector with a screener mapping.
    """
    if segment not in GICS_SECTOR_ETFS:
        raise ValueError(
            f"{segment!r} is not a known GICS sector; cannot resolve a screener universe."
        )
    fmp_sector = _GICS_TO_FMP_SECTOR[segment]
    from openbb import obb

    result = obb.equity.screener(sector=fmp_sector, provider="fmp_cached")
    rows = result.results or []
    return [row.symbol for row in rows if getattr(row, "symbol", None)]


def validate_membership(segment: str, universe: list[str], min_members: int = 5) -> None:
    """Assert a resolved universe is non-empty and has a plausible member count.

    Implements the PRD §10 "membership-count sanity" check.

    Parameters
    ----------
    segment : str
        Segment the universe belongs to (named in the error for diagnosis).
    universe : list[str]
        Resolved constituent symbols.
    min_members : int, optional
        Minimum plausible member count. Defaults to ``5``.

    Raises
    ------
    ValueError
        If ``universe`` has fewer than ``min_members`` symbols.
    """
    if len(universe) < min_members:
        raise ValueError(
            f"Segment {segment!r} resolved to an implausible universe of "
            f"{len(universe)} symbol(s); expected at least {min_members}."
        )


def resolve_universe(
    config: SegmentConfig,
    *,
    constituents: list[str] | None = None,
    holdings_fetcher: Callable[[str], list[str]] | None = None,
    screener_fetcher: Callable[[str], list[str]] | None = None,
    min_members: int = 5,
) -> list[str]:
    """Resolve a single segment to a concrete, validated symbol universe (PRD §10, §20 Q3).

    The resolution strategy is driven by ``config.universe_source``:

    * ``"etf_holdings"`` -- expand ``config.benchmark_etf`` via ``holdings_fetcher``
      (defaults to the live ``obb.etf.holdings`` fetcher). Requires a benchmark ETF.
    * ``"constituent_list"`` -- return the caller-supplied ``constituents``.
    * ``"screener"`` -- query ``screener_fetcher`` for ``config.segment`` (defaults to
      the live ``obb.equity.screener`` sector filter).

    The resolved list is de-duplicated (first-seen order, falsy symbols dropped) and
    passed through :func:`validate_membership`.

    Parameters
    ----------
    config : SegmentConfig
        Segment configuration carrying the source, segment name, and benchmark ETF.
    constituents : list[str] | None, optional
        Static symbol list, required when ``universe_source == "constituent_list"``.
    holdings_fetcher : Callable[[str], list[str]] | None, optional
        ETF-holdings fetcher seam; injected by tests. Defaults to the live
        ``fmp_cached`` fetcher when ``None`` and actually needed.
    screener_fetcher : Callable[[str], list[str]] | None, optional
        Screener fetcher seam; injected by tests. Defaults to the live ``fmp_cached``
        screener when ``None`` and actually needed.
    min_members : int, optional
        Minimum plausible member count for the sanity check. Defaults to ``5``.

    Returns
    -------
    list[str]
        The resolved, de-duplicated, sanity-checked symbol universe.

    Raises
    ------
    ValueError
        If a required input is missing (no benchmark ETF for ``etf_holdings``, empty
        ``constituents`` for ``constituent_list``), the source is unknown, or the
        resolved universe fails the membership-count sanity check.
    """
    source = config.universe_source

    if source == "etf_holdings":
        if not config.benchmark_etf:
            raise ValueError(
                f"Segment {config.segment!r} uses etf_holdings but has no benchmark_etf set."
            )
        fetcher = holdings_fetcher or _default_holdings_fetcher
        raw = fetcher(config.benchmark_etf)
    elif source == "constituent_list":
        if not constituents:
            raise ValueError(
                f"Segment {config.segment!r} uses constituent_list but no constituents were provided."
            )
        raw = list(constituents)
    elif source == "screener":
        fetcher = screener_fetcher or _default_screener_fetcher
        raw = fetcher(config.segment)
    else:  # Defensive: SegmentConfig's Literal should prevent reaching here.
        raise ValueError(f"Unknown universe_source {source!r} for segment {config.segment!r}.")

    universe = _clean_symbols(raw)
    # A caller-supplied constituent_list reflects deliberate intent, so the
    # membership-count sanity floor (which guards against implausibly thin ETF /
    # screener expansions) is relaxed to "must be non-empty" for that source.
    effective_min = 1 if source == "constituent_list" else min_members
    validate_membership(config.segment, universe, min_members=effective_min)
    return universe


def resolve_all_segments(
    holdings_fetcher: Callable[[str], list[str]] | None = None,
    *,
    universe_source: str = "etf_holdings",
    constituents_map: dict[str, list[str]] | None = None,
    screener_fetcher: Callable[[str], list[str]] | None = None,
    min_members: int = 5,
) -> dict[str, list[str]]:
    """Resolve every GICS sector to its universe (PRD §10 "all 11 sectors resolve").

    Builds one :class:`SegmentConfig` per GICS sector via :func:`list_segments` and
    resolves each through :func:`resolve_universe`, returning a sector-name -> universe
    mapping. With an injected fake ``holdings_fetcher`` this runs fully offline.

    Parameters
    ----------
    holdings_fetcher : Callable[[str], list[str]] | None, optional
        ETF-holdings fetcher seam forwarded to :func:`resolve_universe`.
    universe_source : str, optional
        Universe source applied to every segment. Defaults to ``"etf_holdings"``.
    constituents_map : dict[str, list[str]] | None, optional
        Per-segment static symbol lists, used when ``universe_source`` is
        ``"constituent_list"`` (looked up by segment name).
    screener_fetcher : Callable[[str], list[str]] | None, optional
        Screener fetcher seam forwarded to :func:`resolve_universe`.
    min_members : int, optional
        Minimum plausible member count per segment. Defaults to ``5``.

    Returns
    -------
    dict[str, list[str]]
        Mapping of each GICS sector name (keys equal :data:`GICS_SECTOR_ETFS`) to its
        resolved, sanity-checked universe.
    """
    resolved: dict[str, list[str]] = {}
    for config in list_segments(universe_source=universe_source):
        constituents = constituents_map.get(config.segment) if constituents_map else None
        resolved[config.segment] = resolve_universe(
            config,
            constituents=constituents,
            holdings_fetcher=holdings_fetcher,
            screener_fetcher=screener_fetcher,
            min_members=min_members,
        )
    return resolved
