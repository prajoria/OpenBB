"""Scan all 11 GICS sectors and export the top plans to a 6-sheet Excel workbook.

Live run:

    .venv_win\\Scripts\\python.exe -m openbb_techtrade.examples.scan_to_excel

Requires:
- A configured ``fmp_cached`` API key in ``~/.openbb_platform/user_settings.json``
  (see the project README for the schema).
- ``openpyxl`` (ships with the bare ``openbb-techtrade`` install — no extra needed).

Optional:
- ``[xlsxwriter]`` extra (``pip install 'openbb-techtrade[xlsxwriter]'``) to use
  the alternative Excel engine (``engine="xlsxwriter"`` argument to ``export``).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def main(
    *,
    out: Path | str | None = None,
    metric: str = "pct_change",
    top_n: int = 5,
    preset: str = "trend_follow",
    risk: float = 0.01,
    candidate_fetcher=None,
    signal_fetcher=None,
    level_fetcher=None,
) -> str:
    """Run scan -> export, return the workbook path.

    Parameters
    ----------
    out
        Workbook output path. ``None`` (default) lets ``export`` pick its
        default ``Analysis/exports/techtrade_<date>.xlsx``.
    metric, top_n, preset, risk
        Forwarded to ``obb.techtrade.scan``.
    candidate_fetcher, signal_fetcher, level_fetcher
        Test seams. ``None`` (default) uses the live ``fmp_cached`` path.

    Returns
    -------
    str
        Absolute path to the written workbook.
    """
    from openbb import obb  # noqa: PLC0415 — lazy so module imports without `obb`

    # 1. Scan all 11 GICS sectors -> ranked, paper-filled trade plans.
    scan_kwargs = {"metric": metric, "top_n": top_n, "preset": preset, "risk": risk}
    if candidate_fetcher is not None:
        scan_kwargs["candidate_fetcher"] = candidate_fetcher
    if signal_fetcher is not None:
        scan_kwargs["signal_fetcher"] = signal_fetcher
    if level_fetcher is not None:
        scan_kwargs["level_fetcher"] = level_fetcher
    plans = obb.techtrade.scan(**scan_kwargs).results
    logger.info("scan returned %d plans", len(plans))

    # 2. Export to a 6-sheet Excel workbook (Recommendations / Levels / Reasoning
    #    / Orders / Fills / Summary). Includes the "research/paper — not investment
    #    advice" disclaimer banner on the Recommendations sheet.
    export_kwargs = {"plans": plans}
    if out is not None:
        export_kwargs["path"] = str(out)
    path = obb.techtrade.export(**export_kwargs).results
    logger.info("workbook written to: %s", path)
    return str(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
