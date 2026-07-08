"""Top-mover ranking engine: segment universe -> ranked MoverList (PRD §10, issue #70).

The third pipeline stage ranks each segment's candidate symbols into a
:class:`~openbb_techtrade.models.MoverList` of the day's top movers. Ranking is
look-ahead-free: the requested ``as_of`` is first snapped back to the most recent
trading session via ``exchange_calendars`` (offline, deterministic), so a weekend,
holiday, or partially-formed "today" never leaks a future bar into the ranking.

Four ranking metrics are supported (mirroring ``SegmentConfig.rank_metric``):
``pct_change`` and ``volume`` come straight off the discovery feed, while ``gap``
and ``rel_volume`` are derived from recent OHLCV history via
:func:`compute_ohlcv_metrics`.

Every live data call sits behind an injectable ``candidate_fetcher`` seam so the
unit tests run fully offline with fakes (no API key, no network). ``openbb`` is
imported lazily inside the default fetcher only, keeping module import light.
``fmp_cached`` is the only provider used for live calls.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS, list_segments
from openbb_techtrade.models import Mover, MoverList, SegmentConfig

logger = logging.getLogger(__name__)

# The metrics ``rank_movers`` knows how to order candidates by (mirrors
# ``SegmentConfig.rank_metric``). ``gap`` / ``rel_volume`` require OHLCV history.
_VALID_METRICS: frozenset[str] = frozenset({"pct_change", "volume", "gap", "rel_volume"})
# Metrics that need recent OHLCV bars merged into each candidate before ranking.
_OHLCV_METRICS: frozenset[str] = frozenset({"gap", "rel_volume"})


def _as_float(value: object) -> float:
    """Coerce a possibly ``Decimal`` / ``int`` / ``None`` value to ``float``.

    Used to build a numeric sort key (the metric is negated for descending order)
    without disturbing the original candidate values, which may be ``Decimal``.

    Parameters
    ----------
    value : object
        A numeric-like value (``int``, ``float``, ``Decimal``) or ``None``.

    Returns
    -------
    float
        ``float(value)``, or ``0.0`` when ``value`` is ``None``.
    """
    if value is None:
        return 0.0
    return float(value)


def _get(row: object, key: str) -> object:
    """Read ``key`` from an OHLCV row exposing either dict keys or attributes.

    OHLCV rows arrive as provider data objects (attribute access) in the live path
    and as plain dicts in unit tests; this normalises both.

    Parameters
    ----------
    row : object
        A mapping or an object exposing ``open/high/low/close/volume``.
    key : str
        The field name to read.

    Returns
    -------
    object
        The field value, or ``None`` when the key / attribute is absent.
    """
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def resolve_session(as_of: date | str | None = None, calendar: str = "XNYS") -> date:
    """Snap a date back to the most recent trading session (no look-ahead).

    Resolves ``as_of`` to the latest session that is on or before it for the given
    exchange calendar, so weekends, holidays, and a not-yet-closed "today" all map
    to a real, completed session. ``exchange_calendars`` and ``pandas`` are imported
    lazily to keep module import light; the snap is fully offline and deterministic.

    Parameters
    ----------
    as_of : date | str | None, optional
        The requested date as a :class:`datetime.date` or ISO ``str``. Defaults to
        :meth:`datetime.date.today` when ``None``.
    calendar : str, optional
        Exchange-calendar code understood by ``exchange_calendars``. Defaults to
        ``"XNYS"`` (NYSE).

    Returns
    -------
    date
        The most recent session on or before ``as_of``.
    """
    import exchange_calendars as xcals
    import pandas as pd

    if as_of is None:
        as_of = date.today()
    cal = xcals.get_calendar(calendar)
    session = cal.date_to_session(pd.Timestamp(as_of), direction="previous")
    return session.date()


def rank_movers(
    segment: str,
    as_of: date,
    candidates: list[dict],
    *,
    metric: str = "pct_change",
    top_n: int = 10,
) -> MoverList:
    """Rank candidate symbols into a :class:`MoverList` (pure, no network).

    Candidates are ordered by ``candidate[metric]`` descending with a deterministic
    ascending-``symbol`` tie-break, truncated to ``top_n``, and assigned 1-based
    ranks. Candidates that lack the chosen ``metric`` key (or carry ``None`` for it)
    cannot be ranked and are excluded. The descriptive ``pct_change`` and ``volume``
    fields are always populated on each :class:`Mover`, even when ranking by ``gap``
    or ``rel_volume`` (the chosen metric value itself is encoded only by ``rank``).

    Parameters
    ----------
    segment : str
        Segment name the movers belong to.
    as_of : date
        Session date the ranking is for (already snapped by :func:`resolve_session`).
    candidates : list[dict]
        Candidate dicts, each with a ``"symbol"`` key plus whatever metric keys are
        relevant (``pct_change``, ``volume``, ``gap``, ``rel_volume``).
    metric : str, optional
        Metric to rank by; one of ``pct_change`` / ``volume`` / ``gap`` /
        ``rel_volume``. Defaults to ``"pct_change"``.
    top_n : int, optional
        Number of top movers to keep. Defaults to ``10``.

    Returns
    -------
    MoverList
        The ranked, truncated movers for ``segment`` on ``as_of``.

    Raises
    ------
    ValueError
        If ``metric`` is not one of the four supported ranking metrics.
    """
    if metric not in _VALID_METRICS:
        raise ValueError(
            f"Unknown rank metric {metric!r}; expected one of {sorted(_VALID_METRICS)}."
        )
    rankable = [c for c in candidates if c.get(metric) is not None]
    ordered = sorted(rankable, key=lambda c: (-_as_float(c[metric]), c["symbol"]))
    movers = [
        Mover(
            symbol=c["symbol"],
            pct_change=float(c.get("pct_change", 0.0) or 0.0),
            volume=Decimal(str(c.get("volume", 0) or 0)),
            rank=position,
        )
        for position, c in enumerate(ordered[:top_n], start=1)
    ]
    return MoverList(segment=segment, as_of=as_of, movers=movers)


def compute_ohlcv_metrics(symbol: str, ohlcv_rows: list) -> dict:
    """Derive ``pct_change`` / ``gap`` / ``rel_volume`` from recent OHLCV bars (pure).

    Computes the last bar's metrics relative to the prior bar(s): ``pct_change`` and
    ``gap`` reference the immediately-preceding close, while ``rel_volume`` compares
    the last bar's volume to the mean volume of every preceding bar. Rows may be
    dicts or attribute objects (resolved via :func:`_get`).

    Parameters
    ----------
    symbol : str
        The instrument symbol (echoed back into the result).
    ohlcv_rows : list
        Chronologically ascending OHLCV rows, each exposing ``open``, ``high``,
        ``low``, ``close`` and ``volume`` via dict key or attribute.

    Returns
    -------
    dict
        ``{"symbol", "pct_change", "gap", "rel_volume", "volume"}`` where ``volume``
        is the last bar's raw (numeric) volume. With fewer than two bars the ratio
        metrics are ``0.0`` and ``volume`` is the last bar's volume (or ``0``).
    """
    rows = list(ohlcv_rows)
    if len(rows) < 2:
        last_volume = _get(rows[-1], "volume") if rows else 0
        return {
            "symbol": symbol,
            "pct_change": 0.0,
            "gap": 0.0,
            "rel_volume": 0.0,
            "volume": last_volume if last_volume is not None else 0,
        }

    last, prev = rows[-1], rows[-2]
    last_open = _as_float(_get(last, "open"))
    last_close = _as_float(_get(last, "close"))
    prev_close = _as_float(_get(prev, "close"))
    last_volume_raw = _get(last, "volume")
    last_volume = _as_float(last_volume_raw)

    # bd-lw3 (Option B2): store pct_change and gap as HUMAN PERCENT (1.38
    # for a +1.38% move), NOT as a fraction (0.0138). Rationale:
    # Mover.pct_change is a techtrade-native presentation field consumed
    # by notebooks / exports / the Workspace widget — a human percent is
    # the least-surprising unit at that layer, and it makes display code
    # trivially correct (`f"{m.pct_change:+.2f}%"` renders as "+1.38%",
    # not "+0.01%"). The Mover model docstring pins this contract.
    #
    # INVARIANT: any future consumer that needs a fraction MUST divide
    # by 100 explicitly at the boundary. rel_volume is a ratio-of-volumes
    # (not a change ratio) and is NOT multiplied — see the model note.
    pct_change = ((last_close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    gap = ((last_open - prev_close) / prev_close * 100.0) if prev_close else 0.0

    prior_volumes = [_as_float(_get(r, "volume")) for r in rows[:-1]]
    mean_prior = sum(prior_volumes) / len(prior_volumes) if prior_volumes else 0.0
    rel_volume = last_volume / mean_prior if mean_prior else 0.0

    return {
        "symbol": symbol,
        "pct_change": pct_change,
        "gap": gap,
        "rel_volume": rel_volume,
        "volume": last_volume_raw if last_volume_raw is not None else 0,
    }


def _default_candidate_fetcher(
    as_of: date,
    *,
    calendar: str = "XNYS",
    ohlcv_lookback: int = 21,
    needs_ohlcv: bool = False,
    universe: list[str] | None = None,
) -> list[dict]:
    """Build live mover candidates (integration-only).

    bd-lw3 fix: when ``universe`` is provided, take the per-symbol OHLCV
    path for ALL metrics (not just gap/rel_volume) — this is R7.5
    "narrow-then-fan-out". Rationale: the discovery firehose only
    populates the top-50 gainers/losers/active market-wide, so an
    intersection with a sector universe collapses to whatever handful
    of names happen to be in both today (5-ish for XLK). Worse,
    ``EquityPerformanceData.volume`` is not populated by FMP so every
    discovery-sourced candidate silently carries ``volume=None`` →
    ``volume=0`` after coercion.

    Legacy behavior (no universe): union ``obb.equity.discovery.gainers``,
    ``.losers`` and ``.active`` by symbol (first occurrence wins).

    Parameters
    ----------
    as_of : date
        Resolved session date; bounds the OHLCV ``end_date`` to avoid look-ahead.
    calendar : str, optional
        Exchange-calendar code (accepted for a uniform fetcher signature; unused by
        the discovery feed). Defaults to ``"XNYS"``.
    ohlcv_lookback : int, optional
        Number of trailing OHLCV bars to keep per symbol. Defaults to ``21``.
    needs_ohlcv : bool, optional
        Whether to fetch and merge OHLCV-derived metrics on the discovery path.
        Ignored when ``universe`` is supplied (that path is always OHLCV-driven).
        Defaults to ``False``.
    universe : list[str] | None, optional
        When provided, bypass the discovery firehose and fetch per-symbol OHLCV
        for every universe member (bd-lw3 fix). ``needs_ohlcv`` is implicitly
        True on this path.

    Returns
    -------
    list[dict]
        Candidate dicts keyed minimally by ``symbol`` plus available metric fields.
    """
    from openbb import obb

    # bd-lw3: universe path — narrow-then-fan-out. Fetch per-symbol OHLCV
    # and derive real pct_change/volume/gap/rel_volume for the resolved
    # universe. Skip the discovery-firehose union entirely.
    if universe is not None:
        return _fetch_universe_candidates(
            universe, as_of,
            ohlcv_lookback=ohlcv_lookback,
            history_fetcher=lambda symbol, **kw: obb.equity.price.historical(
                symbol=symbol, provider="fmp_cached", **kw,
            ).results or [],
        )

    candidates: dict[str, dict] = {}
    for source in ("gainers", "losers", "active"):
        try:
            rows = _call_discovery(getattr(obb.equity.discovery, source))
        except Exception:  # noqa: BLE001, S112 - skip a flaky discovery source
            continue
        for row in rows:
            symbol = getattr(row, "symbol", None)
            if not symbol or symbol in candidates:
                continue
            # bd-lw3 Option B2: the discovery-path pct_change is stored as
            # a fraction by EquityPerformanceData; convert to percent so
            # Mover.pct_change contract is uniform across both paths.
            raw_pct = getattr(row, "percent_change", None)
            candidates[symbol] = {
                "symbol": symbol,
                "pct_change": raw_pct * 100.0 if raw_pct is not None else None,
                "volume": getattr(row, "volume", None),
            }

    if needs_ohlcv:
        for symbol, candidate in candidates.items():
            try:
                start = (as_of - timedelta(days=ohlcv_lookback * 2 + 10)).isoformat()
                history = obb.equity.price.historical(
                    symbol=symbol,
                    start_date=start,
                    end_date=as_of.isoformat(),
                    provider="fmp_cached",
                )
                bars = (history.results or [])[-ohlcv_lookback:]
                # Intentionally overwrites the discovery pct_change / volume with the
                # OHLCV-derived descriptive values that back gap / rel_volume ranking.
                # compute_ohlcv_metrics already returns pct_change as percent.
                candidate.update(compute_ohlcv_metrics(symbol, bars))
            except Exception:  # noqa: BLE001, S112 - skip a symbol whose history fails
                continue

    return list(candidates.values())


def _fetch_universe_candidates(
    universe: list[str],
    as_of: date,
    *,
    ohlcv_lookback: int = 21,
    history_fetcher: Callable[..., list] | None = None,
) -> list[dict]:
    """Per-constituent OHLCV → candidate dicts with REAL metrics (bd-lw3).

    Implements R7.5 narrow-then-fan-out for the movers pipeline: given a
    resolved universe, fetch per-symbol OHLCV history and derive real
    ``pct_change`` / ``volume`` / ``gap`` / ``rel_volume`` via
    :func:`compute_ohlcv_metrics`. Skips (with WARNING per R7.3) any
    symbol whose history fetch fails or returns empty — never silently
    ranks a symbol with zeros from a failed fetch.

    Parameters
    ----------
    universe : list[str]
        The resolved universe (e.g. XLK constituents for the
        Information Technology sector).
    as_of : date
        Resolved session date; bounds the OHLCV ``end_date``.
    ohlcv_lookback : int, optional
        Number of trailing bars to keep per symbol. Defaults to ``21``.
    history_fetcher : Callable, optional
        Injectable OHLCV fetcher for tests. Signature:
        ``fetcher(symbol, start_date=..., end_date=...) -> list[bar]``.
        When omitted the caller is expected to pass one (production
        callers wrap ``obb.equity.price.historical``).

    Returns
    -------
    list[dict]
        Candidate dicts (one per universe member with valid history).
        Each dict is the output of :func:`compute_ohlcv_metrics`.
    """
    if history_fetcher is None:
        raise ValueError(
            "_fetch_universe_candidates requires a history_fetcher "
            "(inject via _default_candidate_fetcher or test fake)."
        )

    out: list[dict] = []
    start_iso = (as_of - timedelta(days=ohlcv_lookback * 2 + 10)).isoformat()
    end_iso = as_of.isoformat()

    for symbol in universe:
        try:
            bars = history_fetcher(symbol, start_date=start_iso, end_date=end_iso)
        except Exception as exc:  # noqa: BLE001
            # R7.3 loud-empty: name the symbol AND the error so ops can
            # distinguish a broken symbol from a broken fetcher.
            logger.warning(
                "movers: OHLCV fetch failed for %s: %s — dropping from candidate pool",
                symbol, exc,
            )
            continue
        bars = list(bars or [])[-ohlcv_lookback:]
        if not bars:
            logger.warning(
                "movers: no OHLCV bars for %s (empty response) — dropping",
                symbol,
            )
            continue
        out.append(compute_ohlcv_metrics(symbol, bars))

    # iter-1 reviewer soft NIT: R7.3 aggregate loud-empty. Per-symbol
    # warnings scale with |universe| but a distant reader scanning logs
    # sees "many warnings about individual symbols" rather than "the
    # provider is down". Emit one summary line at the boundary so ops
    # can distinguish these two failure modes at a glance.
    if len(universe) > 0 and len(out) == 0:
        logger.warning(
            "movers: 0/%d candidates fetched from universe — check "
            "provider health (all per-symbol fetches failed or returned "
            "empty)",
            len(universe),
        )
    return out


def _call_discovery(fetch: Callable[..., object]) -> list:
    """Call a discovery endpoint via ``fmp_cached`` and return its results.

    Uses ``fmp_cached`` exclusively (the engine's only provider); a failure
    propagates to the caller, which skips that discovery source — mirroring the
    no-fallback contract of ``universe.py``'s default fetchers.

    Parameters
    ----------
    fetch : Callable[..., object]
        A bound ``obb.equity.discovery.*`` command.

    Returns
    -------
    list
        The endpoint's ``results`` list (empty when ``results`` is falsy).
    """
    result = fetch(provider="fmp_cached")
    return result.results or []


def build_mover_list(
    config: SegmentConfig,
    *,
    as_of: date | str | None = None,
    calendar: str = "XNYS",
    universe: list[str] | None = None,
    candidate_fetcher: Callable[..., list[dict]] | None = None,
    metric: str | None = None,
    top_n: int | None = None,
) -> MoverList:
    """Resolve and rank one segment's top movers (PRD §10, issue #70).

    Snaps ``as_of`` to a session, fetches candidates through the (injectable)
    ``candidate_fetcher``, optionally filters them to ``universe``, and ranks via
    :func:`rank_movers`. The fetcher is invoked as
    ``fetcher(as_of=session, calendar=calendar, needs_ohlcv=..., universe=universe)``;
    injected fakes must therefore accept ``**kwargs`` (tests use
    ``def fake(as_of, **kwargs)``). The ``universe`` kwarg was added in
    bd-lw3 so the fetcher can take the R7.5 narrow-then-fan-out path for
    ALL metrics (not just gap/rel_volume) — fakes that ignore ``universe``
    still work because ``build_mover_list`` post-filters as a safety net.
    Fakes that use strict keyword signatures (no ``**kwargs``) MUST accept
    ``universe`` to remain compatible.

    Parameters
    ----------
    config : SegmentConfig
        Segment configuration supplying the segment name and the default
        ``rank_metric`` / ``top_n``.
    as_of : date | str | None, optional
        Requested date, snapped to a session. Defaults to today when ``None``.
    calendar : str, optional
        Exchange-calendar code for session snapping. Defaults to ``"XNYS"``.
    universe : list[str] | None, optional
        When provided, candidates are filtered to symbols in this universe.
    candidate_fetcher : Callable[..., list[dict]] | None, optional
        Candidate-fetcher seam; defaults to the live :func:`_default_candidate_fetcher`.
    metric : str | None, optional
        Ranking metric override; falls back to ``config.rank_metric`` when ``None``.
    top_n : int | None, optional
        Top-N override; falls back to ``config.top_n`` when ``None``.

    Returns
    -------
    MoverList
        The ranked movers for ``config.segment`` on the resolved session.
    """
    session = resolve_session(as_of, calendar)
    metric = metric or config.rank_metric
    top_n = top_n if top_n is not None else config.top_n
    fetcher = candidate_fetcher or _default_candidate_fetcher

    # bd-lw3: pass universe through to the fetcher so it can take the
    # narrow-then-fan-out OHLCV path for ALL metrics (not just
    # gap/rel_volume). Prior code post-filtered candidates AFTER a
    # discovery-firehose fetch, silently collapsing the pool to
    # `universe ∩ discovery_top_150` (often < 10 for sector scans).
    candidates = fetcher(
        as_of=session,
        calendar=calendar,
        needs_ohlcv=metric in _OHLCV_METRICS,
        universe=universe,
    )

    # Post-filter kept as a safety net for injected test fetchers that
    # don't honor the universe kwarg. When the default fetcher runs and
    # universe was passed, this is a no-op (fetcher already restricted).
    if universe is not None:
        allowed = set(universe)
        candidates = [c for c in candidates if c.get("symbol") in allowed]

    return rank_movers(config.segment, session, candidates, metric=metric, top_n=top_n)


def list_movers(
    segment: str | None = None,
    *,
    metric: str = "pct_change",
    top_n: int = 10,
    as_of: date | str | None = None,
    calendar: str = "XNYS",
    universe_source: str = "etf_holdings",
    candidate_fetcher: Callable[..., list[dict]] | None = None,
    holdings_fetcher: Callable[[str], list[str]] | None = None,
    screener_fetcher: Callable[[str], list[str]] | None = None,
    constituents_map: dict[str, list[str]] | None = None,
    resolve_universe_filter: bool = True,
) -> list[MoverList]:
    """Rank top movers for one or all GICS segments (PRD §9.2, §10, issue #70).

    With ``segment`` given, ranks that single GICS sector; otherwise ranks all 11 in
    canonical :data:`GICS_SECTOR_ETFS` order. On the live path (no injected
    ``candidate_fetcher``) each segment's universe is resolved via
    :func:`~openbb_techtrade.engine.universe.resolve_universe` and used to filter the
    candidates; a resolution failure degrades to no filter. When a fake
    ``candidate_fetcher`` is injected (the unit path) no universe is resolved, keeping
    the offline tests hermetic.

    Parameters
    ----------
    segment : str | None, optional
        A single GICS sector to rank, or ``None`` for all 11. Defaults to ``None``.
    metric : str, optional
        Ranking metric applied to every segment. Defaults to ``"pct_change"``.
    top_n : int, optional
        Number of movers per segment. Defaults to ``10``.
    as_of : date | str | None, optional
        Requested date, snapped to a session per segment. Defaults to today.
    calendar : str, optional
        Exchange-calendar code for session snapping. Defaults to ``"XNYS"``.
    universe_source : str, optional
        How each segment's universe is resolved on the live path (``etf_holdings`` /
        ``constituent_list`` / ``screener``). Defaults to ``"etf_holdings"``.
    candidate_fetcher : Callable[..., list[dict]] | None, optional
        Candidate-fetcher seam forwarded to :func:`build_mover_list`; injected by
        tests. Defaults to the live fetcher when ``None``.
    holdings_fetcher : Callable[[str], list[str]] | None, optional
        ETF-holdings fetcher seam forwarded to ``resolve_universe`` on the live path.
    screener_fetcher : Callable[[str], list[str]] | None, optional
        Screener fetcher seam forwarded to ``resolve_universe`` on the live path.
    constituents_map : dict[str, list[str]] | None, optional
        Per-segment static symbol lists for the ``constituent_list`` source.
    resolve_universe_filter : bool, optional
        Whether to resolve and apply a universe filter on the live path. Defaults to
        ``True``.

    Returns
    -------
    list[MoverList]
        One :class:`MoverList` per target segment, in canonical order.

    Raises
    ------
    ValueError
        If ``segment`` is not ``None`` and not a known GICS sector.
    """
    if segment is not None and segment not in GICS_SECTOR_ETFS:
        raise ValueError(
            f"{segment!r} is not a known GICS sector; expected one of {list(GICS_SECTOR_ETFS)}."
        )

    configs = list_segments(universe_source=universe_source, rank_metric=metric, top_n=top_n)
    if segment is not None:
        configs = [config for config in configs if config.segment == segment]

    results: list[MoverList] = []
    for config in configs:
        universe = _resolve_filter_universe(
            config,
            candidate_fetcher=candidate_fetcher,
            resolve_universe_filter=resolve_universe_filter,
            holdings_fetcher=holdings_fetcher,
            screener_fetcher=screener_fetcher,
            constituents_map=constituents_map,
        )
        results.append(
            build_mover_list(
                config,
                as_of=as_of,
                calendar=calendar,
                universe=universe,
                candidate_fetcher=candidate_fetcher,
                metric=metric,
                top_n=top_n,
            )
        )
    return results


def _resolve_filter_universe(
    config: SegmentConfig,
    *,
    candidate_fetcher: Callable[..., list[dict]] | None,
    resolve_universe_filter: bool,
    holdings_fetcher: Callable[[str], list[str]] | None,
    screener_fetcher: Callable[[str], list[str]] | None,
    constituents_map: dict[str, list[str]] | None,
) -> list[str] | None:
    """Resolve a segment's universe for candidate filtering on the live path only.

    Returns ``None`` (no filter) unless filtering is enabled *and* the live
    candidate path is in use (no injected ``candidate_fetcher``); a resolution
    failure also degrades to ``None`` so a thin or unreachable universe never aborts
    ranking. ``resolve_universe`` is imported lazily to keep module import light.

    Parameters
    ----------
    config : SegmentConfig
        Segment whose universe is being resolved.
    candidate_fetcher : Callable[..., list[dict]] | None
        When non-``None`` (the unit path) no universe is resolved.
    resolve_universe_filter : bool
        Master switch for universe filtering.
    holdings_fetcher : Callable[[str], list[str]] | None
        ETF-holdings fetcher seam forwarded to ``resolve_universe``.
    screener_fetcher : Callable[[str], list[str]] | None
        Screener fetcher seam forwarded to ``resolve_universe``.
    constituents_map : dict[str, list[str]] | None
        Per-segment static symbol lists for the ``constituent_list`` source.

    Returns
    -------
    list[str] | None
        The resolved universe, or ``None`` to apply no filter.
    """
    if not (resolve_universe_filter and candidate_fetcher is None):
        return None

    from openbb_techtrade.engine.universe import resolve_universe

    constituents = constituents_map.get(config.segment) if constituents_map else None
    try:
        return resolve_universe(
            config,
            constituents=constituents,
            holdings_fetcher=holdings_fetcher,
            screener_fetcher=screener_fetcher,
        )
    except Exception:  # noqa: BLE001 - degrade to no filter on resolution failure
        return None
