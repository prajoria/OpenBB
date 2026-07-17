"""Engine sub-router: ``signals`` (PRD §9.2, §12.3, issue #75).

The signal face of ``obb.techtrade.*``. :func:`signals` runs the #74 confluence voting
engine over an explicit symbol set or a whole GICS segment under a named **preset**
(``trend_follow`` / ``mean_revert`` / ``breakout``) and returns ranked
:class:`~openbb_techtrade.models.MoverSignal` rows -- each carrying a composite score, a
direction, and per-indicator vote attribution. Auto-wired onto ``obb.techtrade.*`` by the
lazy sub-router include in ``techtrade_router._include_subrouters`` (which already lists
this module).

The command is **thin**: it maps its arguments to the pure
:func:`~openbb_techtrade.engine.signals.build_signals` orchestrator and wraps the result
in an ``OBBject``, exactly mirroring ``screener_router`` -> ``movers``. It returns a bare
``OBBject`` (no parametrized model) so the static package builder renders a valid,
importable return annotation -- see ``techtrade_router`` and
``package_builder.build_func_returns``. The conceptual ``list[MoverSignal]`` payload type
is documented in the command docstring.
"""

# from __future__ import annotations  # removed: breaks FastAPI OBBject resolution (#824)

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="", description="Compute ranked confluence trade signals.")


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="Score all IT-sector movers under the trend-follow preset.",
            parameters={"segment": "Information Technology"},
        ),
        APIEx(
            description="Score an explicit symbol set with mean-reversion tilt.",
            parameters={"symbols": ["AAPL", "MSFT"], "preset": "mean_revert"},
        ),
    ],
)
def signals(
    segment: str | None = None,
    symbols: list[str] | None = None,
    preset: str = "trend_follow",
    as_of: str | None = None,
) -> OBBject:
    """Compute ranked confluence signals for a symbol set or a GICS segment (PRD §12.3, issue #75).

    Scores either an explicit ``symbols`` set or a ``segment``'s ranked top movers with the
    #74 confluence engine under the named ``preset``, then ranks the results by signed score
    descending (most-long first) into a contiguous ``rank_in_segment``. Each returned signal
    carries the per-indicator votes -- with the preset's weight tilt visible in every
    ``vote.weight`` -- so the engine can always answer *"why long?"*. The requested ``as_of``
    is snapped back to the most recent trading session before scoring, so the result is
    always look-ahead-free.

    Parameters
    ----------
    segment : str | None, optional
        A single GICS sector name (e.g. ``"Information Technology"``) to resolve into its
        ranked top movers, or ``None`` to score an explicit ``symbols`` set. Defaults to
        ``None``.
    symbols : list[str] | None, optional
        Explicit instrument symbols to score; takes precedence over ``segment``. Defaults
        to ``None``.
    preset : str, optional
        Named confluence preset: ``"trend_follow"`` (default, the Q4 base) / ``"mean_revert"``
        / ``"breakout"``. Each re-tilts the same four indicator families toward a style.
    as_of : str | None, optional
        ISO date to score as of; snapped to the most recent session. Defaults to today when
        ``None``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[MoverSignal], ranked within the segment.
    """
    from openbb_techtrade.engine.signals import build_signals

    return OBBject(
        results=build_signals(symbols=symbols, segment=segment, preset=preset, as_of=as_of)
    )
