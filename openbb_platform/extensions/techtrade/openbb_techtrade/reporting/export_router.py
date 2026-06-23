"""Reporting sub-router: ``export`` -> 6-sheet recommendation workbook (PRD §14.3, issue #81).

The export face of ``obb.techtrade.*``. :func:`export` is the thin command wrapper around
:func:`~openbb_techtrade.reporting.excel_export.export`: it normalizes the ``plans`` payload (accepts
either fully-validated :class:`~openbb_techtrade.models.TradePlan` instances or plain dicts
round-tripped from JSON / the REST layer), forwards the optional ``path`` / ``engine`` kwargs
(which override the underlying ``ExportConfig`` defaults per design Q-D), and returns the written
file path inside a bare ``OBBject``.

The command is **thin**: route validation lives in the pure exporter; no I/O / pandas / openpyxl
imports live here. The module is auto-wired onto ``obb.techtrade.*`` by the lazy sub-router include
in :func:`openbb_techtrade.techtrade_router._include_subrouters` (which already lists this module).

Note: this module deliberately does **not** use ``from __future__ import annotations``. ``export``
takes a ``plans: list[TradePlan]`` model parameter, and the static package builder must see the real
:class:`TradePlan` class (not a stringized annotation) to emit its import into the generated
package -- mirroring the ``plan_router.orders`` convention.
"""

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_techtrade.models import ExportConfig, TradePlan

router = Router(prefix="", description="Write the 6-sheet recommendation workbook (PRD §14.3).")


@router.command(methods=["POST"])
def export(
    plans: list[TradePlan],
    path: str | None = None,
    engine: str = "openpyxl",
) -> OBBject:
    """Write the 6-sheet recommendation workbook to disk (PRD §14.3, issue #81).

    Renders ``plans`` as a polished, deterministic ``.xlsx`` workbook with six sheets
    (``Recommendations`` / ``Levels`` / ``Reasoning`` / ``Orders`` / ``Fills`` / ``Summary``),
    a compliance disclaimer on the Recommendations sheet (locked by PRD §20 Q9), conditional
    formatting (color-coded Action, R:R data bar, score color scale, etc.), and a frozen + filterable
    header row. Rows are sorted by ``segment`` → ``conviction`` → ``action`` → ``symbol`` so the
    workbook is byte-stable for identical inputs (design L6).

    Money / quantities stay :class:`~decimal.Decimal` end-to-end; cells store the unrounded
    ``float(Decimal)`` and Excel ``number_format`` controls display rounding only -- the model value
    is always the source of truth (design Q-E / L9). The only datetime cell is the deterministic
    :class:`~openbb_techtrade.models.Fill` ``timestamp`` (#78 Q-F session-close localization), never
    a wall-clock; the filename date is the run's ``as_of`` (design L4).

    Parameters
    ----------
    plans : list[TradePlan]
        Paper-filled trade plans -- typically the output of :func:`obb.techtrade.scan` (#79) or
        :func:`obb.techtrade.plan` (#77). Each plan carries the ``recommendation``, ``signal.votes``,
        ``orders``, and ``simulated_fills`` that feed the six sheets. An empty list yields a
        header-only workbook (still containing the disclaimer).
    path : str | None, optional
        Explicit output path. Overrides the ``ExportConfig`` default of
        ``Analysis/exports/techtrade_<as_of>.xlsx`` (design L4 / Q-F). The parent directory is
        auto-created. A same-as-of run overwrites silently (deterministic, re-runnable artifact).
    engine : str, optional
        Workbook engine: ``"openpyxl"`` (default, core dependency, full conditional formatting,
        design L1 / Q-B B1) or ``"xlsxwriter"`` (optional, lazy-imported, best-effort richer
        formatting -- no parity guarantee).

    Returns
    -------
    OBBject
        OBBject whose ``results`` is the absolute ``str`` path of the written workbook.
    """
    from openbb_techtrade.reporting.excel_export import export as _export

    cfg = ExportConfig(path=path, engine=engine)
    return OBBject(results=_export(plans, config=cfg))
