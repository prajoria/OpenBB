"""Engine sub-router: ``segments`` (PRD §9.2).

The segment face of ``obb.techtrade.*``. :func:`segments` lists the supported GICS
segments and their (placeholder) resolved universes as :class:`SegmentConfig`
rows. It is auto-wired onto ``obb.techtrade.*`` by the lazy sub-router include in
``techtrade_router._include_subrouters``.

The command returns a bare ``OBBject`` (no parametrized model) so the static
package builder renders a valid, importable return annotation — see
``techtrade_router`` and ``package_builder.build_func_returns``. The conceptual
``list[SegmentConfig]`` payload type is documented in the command docstring.
"""

from __future__ import annotations

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="", description="List supported GICS segments and universes.")


@router.command(methods=["GET"])
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
