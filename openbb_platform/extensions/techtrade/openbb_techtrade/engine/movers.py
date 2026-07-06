"""Top-mover ranking engine: segment universe -> ranked MoverList (PRD §10, issue #70).

The third pipeline stage ranks each segment's candidate symbols into a
:class:`~openbb_techtrade.models.MoverList` of the day's top movers. Ranking is
look-ahead-free: the requested ``as_of`` is first snapped back to the most recent
trading session via ``exchange_calendars`` (offline, deterministic), so a weekend,
holiday, or partially-formed "today" never leaks a future bar into the ranking.

Four ranking metrics are supported (mirroring ``SegmentConfig.rank_metric``):
``pct_change``, ``volume``, ``gap``, and ``rel_volume``. Metric provenance depends
on which candidate-fetcher path is active (see :func:`_default_candidate_fetcher`):

* **Universe path** (post-bd-z7f) — every candidate is derived from OHLCV via
  :func:`compute_ohlcv_metrics`, so all four metric fields are always populated.
* **Discovery path** — ``pct_change`` and ``volume`` come straight off the
  discovery feed; ``gap`` and ``rel_volume`` are merged in from OHLCV history
  only when ``needs_ohlcv`` is set (metric ∈ ``{gap, rel_volume}``).

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

_logger = logging.getLogger(__name__)

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
    # R7.3 loud-empty: silently dropping candidates because the ranking
    # metric is None (e.g. discovery-feed rows with volume=null when caller
    # ranks by "volume") is a documented silent-degradation hazard. PR #325
    # review (silent-failure-hunter finding #3) reproduced this against the
    # captured discovery_gainers fixture where every row has volume=None →
    # metric="volume" silently returns MoverList(movers=[]). Emit a WARNING
    # when the collapse is total or severe (>= 50% of candidates dropped),
    # keeping the happy path silent per the "avoid noise" non-goal.
    dropped = len(candidates) - len(rankable)
    if candidates and (not rankable or dropped * 2 >= len(candidates)):
        _logger.warning(
            "rank_movers(segment=%s, metric=%s): dropped %d/%d candidates "
            "with missing %r — result may be empty or heavily thinned",
            segment,
            metric,
            dropped,
            len(candidates),
            metric,
        )
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

    pct_change = (last_close - prev_close) / prev_close if prev_close else 0.0
    gap = (last_open - prev_close) / prev_close if prev_close else 0.0

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

    Two paths depending on ``universe`` (bd OpenBBTechnical-z7f):

    * **Universe path** (``universe`` non-empty): iterate the provided symbol list
      and fetch recent daily OHLCV per symbol via
      ``obb.equity.price.historical(provider="fmp_cached")``; each candidate is
      built through :func:`compute_ohlcv_metrics`, which populates all four
      metric fields (``pct_change``, ``volume``, ``gap``, ``rel_volume``). This
      is the sector-scan path: the market-wide discovery feed almost never
      intersects a sector-ETF universe (e.g. XLK holds mega-cap tech while
      ``obb.equity.discovery.gainers/losers`` returns penny-stock movers), so
      going straight to the constituents is the only way to produce non-empty
      results.
    * **Discovery path** (``universe`` is ``None`` or empty): unions
      ``obb.equity.discovery.gainers``, ``.losers`` and ``.active`` by symbol
      (first occurrence wins). When ``needs_ohlcv`` is set, recent history is
      merged in via :func:`compute_ohlcv_metrics`. Preserved for callers that
      genuinely want the market-wide firehose.

    Every external call is guarded so a flaky source or symbol is skipped
    rather than aborting the whole fetch. ``openbb`` is imported lazily and
    all live calls use ``fmp_cached``.

    Parameters
    ----------
    as_of : date
        Resolved session date; bounds the OHLCV ``end_date`` to avoid look-ahead.
    calendar : str, optional
        Exchange-calendar code (accepted for a uniform fetcher signature; unused
        directly). Defaults to ``"XNYS"``.
    ohlcv_lookback : int, optional
        Number of trailing OHLCV bars to keep per symbol. Defaults to ``21``.
    needs_ohlcv : bool, optional
        On the discovery path, whether to fetch and merge OHLCV-derived metrics.
        Ignored on the universe path (which always fetches OHLCV). Defaults to
        ``False``.
    universe : list[str] | None, optional
        Sector-ETF constituent list (or any target symbol set). When provided
        and non-empty, activates the universe path. Defaults to ``None``.

    Returns
    -------
    list[dict]
        Candidate dicts keyed minimally by ``symbol`` plus available metric fields.
    """
    from openbb import obb

    if universe:
        return _fetch_universe_candidates(
            obb,
            universe,
            as_of=as_of,
            ohlcv_lookback=ohlcv_lookback,
        )

    candidates: dict[str, dict] = {}
    # PR #325 review (silent-failure-hunter finding #5): track raised vs
    # empty-but-not-raised discovery sources separately so ops can tell
    # "endpoint dead" from "no market movers today" from partial-outage.
    # Iter-2: also count null-symbol rows per source so a data-quality event
    # (FMP returns rows but every row has symbol=None during a symbol-
    # unification drift) is distinguishable from "endpoint returned []".
    raised_sources: list[str] = []
    empty_sources: list[str] = []
    null_symbol_count = 0
    for source in ("gainers", "losers", "active"):
        try:
            rows = _call_discovery(getattr(obb.equity.discovery, source))
        except Exception:  # noqa: BLE001, S112 - skip a flaky discovery source
            raised_sources.append(source)
            continue
        if not rows:
            empty_sources.append(source)
            continue
        for row in rows:
            symbol = getattr(row, "symbol", None)
            if not symbol:
                null_symbol_count += 1
                continue
            if symbol in candidates:
                continue
            candidates[symbol] = {
                "symbol": symbol,
                "pct_change": getattr(row, "percent_change", None),
                "volume": getattr(row, "volume", None),
            }

    # R7.3 loud-empty. Two warning triggers:
    #   * TOTAL: no candidates at all → raw feed is dead OR every row had
    #     symbol=None (data-quality event; the null_symbol_count field lets
    #     ops distinguish the two silent-failure signatures).
    #   * PARTIAL: any source raised or returned empty → caller may be
    #     silently under-sampled (e.g. losers-side moves missing from a
    #     pct_change ranking); PR #325 review (silent-failure-hunter #5)
    #     flagged this as a blind spot in the original 90e implementation
    #     which only warned on 100% failure.
    degraded = raised_sources or empty_sources
    if not candidates:
        _logger.warning(
            "discovery feed produced 0 candidates "
            "(raised=%s, empty=%s, null_symbols=%d, provider=fmp_cached, "
            "as_of=%s)",
            raised_sources or "[]",
            empty_sources or "[]",
            null_symbol_count,
            as_of.isoformat(),
        )
    elif degraded:
        _logger.warning(
            "discovery feed partially degraded: %d/3 sources produced rows "
            "(raised=%s, empty=%s, null_symbols=%d, provider=fmp_cached, "
            "as_of=%s) — ranking may be biased toward the healthy sources",
            3 - len(raised_sources) - len(empty_sources),
            raised_sources or "[]",
            empty_sources or "[]",
            null_symbol_count,
            as_of.isoformat(),
        )

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
                candidate.update(compute_ohlcv_metrics(symbol, bars))
            except Exception:  # noqa: BLE001, S112 - skip a symbol whose history fails
                continue

    return list(candidates.values())


def _fetch_universe_candidates(
    obb: object,
    universe: list[str],
    *,
    as_of: date,
    ohlcv_lookback: int,
) -> list[dict]:
    """Build mover candidates directly from OHLCV history for a symbol universe.

    Sector-scan path helper for :func:`_default_candidate_fetcher`. Fetches a
    short trailing daily-price window per symbol and folds each into a candidate
    via :func:`compute_ohlcv_metrics`, so every candidate carries all four
    metrics (``pct_change`` / ``volume`` / ``gap`` / ``rel_volume``). Per-symbol
    failures are caught and skipped so one broken ticker never aborts the batch.

    Parameters
    ----------
    obb : object
        The already-imported ``openbb`` module (passed in so the caller controls
        the lazy import).
    universe : list[str]
        Symbols to build candidates for; duplicates are collapsed.
    as_of : date
        Resolved session date; the OHLCV ``end_date`` upper bound.
    ohlcv_lookback : int
        Number of trailing bars to keep after fetch.

    Returns
    -------
    list[dict]
        One candidate dict per successfully-fetched symbol.

    Warnings
    --------
    Emits a ``logging.WARNING`` in three distinct silent-failure scenarios
    (PR #325 review, silent-failure-hunter findings #2 / #6):

    * **Falsy universe** — ``universe`` was non-empty but every entry was
      dropped as falsy (``None`` / ``""``). Points ops at the upstream
      holdings/screener fetcher rather than at OHLCV.
    * **Total OHLCV failure** — universe had usable symbols but every
      per-symbol fetch dropped (empty history or exception). Original
      bd-z7f-class silent failure.
    * **Partial degradation (>= 20% dropped)** — ranker will produce biased
      top-N because a substantial fraction of the requested universe never
      contributed a candidate. Threshold mirrors the "membership-count
      sanity" heuristic in :func:`~openbb_techtrade.engine.universe.validate_membership`.
    """
    start = (as_of - timedelta(days=ohlcv_lookback * 2 + 10)).isoformat()
    end = as_of.isoformat()
    seen: set[str] = set()
    out: list[dict] = []
    # PR #325 review (silent-failure-hunter finding #6): track per-symbol
    # skip reasons so a partial outage (e.g. 40/75 XLK symbols rate-limited)
    # emits a WARNING with counts instead of silently returning a biased
    # 35-candidate result. Distinguishes "endpoint returned empty" (bar-less
    # response) from "endpoint raised" (network/rate-limit/malformed).
    empty_history: list[str] = []
    failed_fetch: list[str] = []
    for symbol in universe:
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        try:
            history = obb.equity.price.historical(  # type: ignore[attr-defined]
                symbol=symbol,
                start_date=start,
                end_date=end,
                provider="fmp_cached",
            )
            bars = (history.results or [])[-ohlcv_lookback:]
            if not bars:
                empty_history.append(symbol)
                continue
            out.append(compute_ohlcv_metrics(symbol, bars))
        except Exception:  # noqa: BLE001, S112 - skip a symbol whose history fails
            failed_fetch.append(symbol)
            continue
    # R7.3 loud-empty. Two triggers:
    #   * TOTAL: universe had usable symbols, out empty → every symbol dropped
    #     (the original 90e trigger — the bd-z7f class silent failure).
    #   * PARTIAL: >= 20% of the processed universe dropped → callers ranking
    #     top-N are silently under-sampled and rankings are biased toward the
    #     symbols that survived. Chosen threshold matches the "membership-
    #     count sanity" heuristic in universe.validate_membership.
    # Iter-2 (code-reviewer F3 / silent-failure-hunter F2): guard on ``seen``
    # rather than ``universe`` so a caller passing an all-falsy universe
    # (e.g. ``["", None]`` from a drifted ETF-holdings response) does not
    # produce nonsensical "any of 0 universe symbols" warnings that would
    # send an ops investigator on a wild-goose chase looking for a provider
    # outage that isn't there. When ``seen`` is empty AND ``universe`` was
    # non-empty, the caller passed a garbage universe — log that separately.
    skipped = len(empty_history) + len(failed_fetch)
    if universe and not seen:
        _logger.warning(
            "universe scan received %d symbols but all were falsy after "
            "dedup (as_of=%s) — check the upstream holdings/screener "
            "fetcher, symbols may have drifted to None or ''",
            len(universe),
            as_of.isoformat(),
        )
    elif seen and not out:
        _logger.warning(
            "no OHLCV history returned for any of %d universe symbols "
            "(as_of=%s, provider=fmp_cached, empty_history=%d, failed=%d, "
            "first_failed=%s)",
            len(seen),
            as_of.isoformat(),
            len(empty_history),
            len(failed_fetch),
            failed_fetch[0] if failed_fetch else None,
        )
    elif seen and skipped * 5 >= len(seen):  # >= 20% skipped
        _logger.warning(
            "universe scan partially degraded: %d/%d symbols dropped "
            "(empty_history=%d, failed_fetch=%d, as_of=%s, "
            "provider=fmp_cached) — top-N ranking may be biased",
            skipped,
            len(seen),
            len(empty_history),
            len(failed_fetch),
            as_of.isoformat(),
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
    :func:`rank_movers`. The fetcher is always invoked as
    ``fetcher(as_of=session, calendar=calendar, needs_ohlcv=...)``; injected fakes
    must therefore accept ``**kwargs`` (tests use ``def fake(as_of, **kwargs)``).

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

    # Passed through so the live fetcher can go straight to per-symbol OHLCV on
    # the sector-scan path (bd OpenBBTechnical-z7f). Injected test fetchers use
    # ``**kwargs`` so this extra keyword is silently absorbed.
    candidates = fetcher(
        as_of=session,
        calendar=calendar,
        needs_ohlcv=metric in _OHLCV_METRICS,
        universe=universe,
    )

    if universe is not None:
        allowed = set(universe)
        pre_filter_count = len(candidates)
        candidates = [c for c in candidates if c.get("symbol") in allowed]
        # R7.3 loud-empty: a pre-filter non-empty candidate set collapsing to
        # zero after intersecting with the universe is the exact fingerprint
        # of bd OpenBBTechnical-z7f (discovery firehose does not intersect
        # sector-ETF holdings). Emit a WARNING with the arithmetic so any
        # future recurrence is one grep away.
        if pre_filter_count > 0 and not candidates:
            _logger.warning(
                "segment=%s: universe filter removed all candidates "
                "(pre_filter=%d, allowed=%d, intersection=0) — see bd z7f",
                config.segment,
                pre_filter_count,
                len(allowed),
            )

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
    failure also degrades to ``None`` so a thin or unreachable universe never
    aborts ranking. The resolution failure is logged at ``WARNING`` level with
    the exception type, source, and benchmark ETF (PR #325 review, silent-
    failure-hunter finding #2), so an operator can distinguish "sector
    legitimately empty" from "sector lookup broke and we're returning
    unfiltered market data". ``resolve_universe`` is imported lazily to keep
    module import light.

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
    except Exception as exc:  # noqa: BLE001 - degrade to no filter on resolution failure
        # R7.3 loud-empty: universe resolution failure silently degrades to
        # "no filter", which lets the discovery firehose (penny caps) flow
        # through labelled as the requested sector — the exact class of
        # silent failure bd z7f identified. Emit a WARNING so the operator
        # can distinguish "sector legitimately empty" from "sector lookup
        # broke and we're returning market-wide noise". Detected via PR #325
        # review (silent-failure-hunter finding #2).
        _logger.warning(
            "segment=%s: universe resolution failed (%s: %s); falling back "
            "to unfiltered candidates — results are NOT scoped to the "
            "segment (source=%s, benchmark_etf=%s)",
            config.segment,
            type(exc).__name__,
            exc,
            config.universe_source,
            config.benchmark_etf,
        )
        return None
