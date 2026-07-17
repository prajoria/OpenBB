"""Engine sub-router: ``segments`` and ``movers`` (PRD §9.2, §10).

The segment face of ``obb.techtrade.*``. :func:`segments` lists the supported GICS
segments and their (placeholder) resolved universes as :class:`SegmentConfig`
rows; :func:`movers` ranks the day's top movers per segment as
:class:`~openbb_techtrade.models.MoverList` rows (issue #70). Both commands are
auto-wired onto ``obb.techtrade.*`` by the lazy sub-router include in
``techtrade_router._include_subrouters``.

Each command returns a bare ``OBBject`` (no parametrized model) so the static
package builder renders a valid, importable return annotation — see
``techtrade_router`` and ``package_builder.build_func_returns``. The conceptual
``list[SegmentConfig]`` / ``list[MoverList]`` payload types are documented in the
command docstrings.
"""

# from __future__ import annotations  # removed: breaks FastAPI OBBject resolution (#824)

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="", description="List supported GICS segments and universes.")


@router.command(
    methods=["GET"],
    examples=[
        APIEx(parameters={}),
        APIEx(
            description="Rank by volume; keep top 5 per segment.",
            parameters={"rank_metric": "volume", "top_n": 5},
        ),
    ],
)
def segments(
    universe_source: str = "etf_holdings",
    rank_metric: str = "pct_change",
    top_n: int = 10,
) -> OBBject:
    """List supported GICS segments and their (placeholder) resolved universes.

    Parameters
    ----------
    universe_source : str, optional
        How each segment universe is resolved (``etf_holdings`` /
        ``constituent_list`` / ``screener``). Defaults to ``"etf_holdings"``.
    rank_metric : str, optional
        Metric used to rank movers within a segment (``pct_change`` / ``volume``
        / ``gap`` / ``rel_volume``). Defaults to ``"pct_change"``.
    top_n : int, optional
        Number of top movers to keep per segment. Defaults to ``10``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[SegmentConfig], one per GICS sector.
    """
    from openbb_techtrade.engine.screener import list_segments

    return OBBject(
        results=list_segments(
            universe_source=universe_source,
            rank_metric=rank_metric,
            top_n=top_n,
        )
    )


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="All 11 sectors, default pct_change ranking.",
            parameters={},
        ),
        APIEx(
            description="Just Information Technology, top 5 by volume.",
            parameters={
                "segment": "Information Technology",
                "metric": "volume",
                "top_n": 5,
            },
        ),
    ],
)
def movers(
    segment: str | None = None,
    metric: str = "pct_change",
    top_n: int = 10,
    as_of: str | None = None,
) -> OBBject:
    """Rank the day's top movers for one or all GICS segments (PRD §10, issue #70).

    Ranks a single GICS sector when ``segment`` is given, or all 11 sectors in
    canonical order when ``segment`` is ``None``. The requested ``as_of`` is snapped
    back to the most recent trading session before ranking, so the result is always
    look-ahead-free.

    Parameters
    ----------
    segment : str | None, optional
        A single GICS sector name (e.g. ``"Information Technology"``) to rank, or
        ``None`` to rank all 11 sectors. Defaults to ``None``.
    metric : str, optional
        Metric used to rank movers within each segment (``pct_change`` / ``volume``
        / ``gap`` / ``rel_volume``). Defaults to ``"pct_change"``.
    top_n : int, optional
        Number of top movers to keep per segment. Defaults to ``10``.
    as_of : str | None, optional
        ISO date to rank as of; snapped to the most recent session. Defaults to
        today when ``None``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[MoverList], one per target segment.
    """
    from openbb_techtrade.engine.movers import list_movers

    return OBBject(
        results=list_movers(segment=segment, metric=metric, top_n=top_n, as_of=as_of)
    )
