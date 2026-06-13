"""HTML/PNG artifact export (component 07, §2 export).

:func:`export_html` renders a one-call `quantstats <https://github.com/ranaroussi/
quantstats>`_ HTML tear-sheet report from a **normalized return series**, writes it
under the configured ``export_dir`` (default ``Analysis/exports`` — the existing
fork export convention), and returns the saved **file path only**. That path is
what populates :attr:`~openbb_backtest.models.TearSheet.html_path`; the model never
embeds the (large) HTML/PNG blob.

Contract (see ``docs/designs/backtest-design/07-analytics.md`` §2):

- **No fallback:** unlike the metrics/tear-sheet layers, a report *is* the heavy
  library's output, so when quantstats is absent this raises an actionable
  :class:`ImportError` (naming the pip package) rather than degrading.
- **Lazy:** quantstats is imported only inside :func:`export_html`, so importing
  this module (and the pure :func:`_resolve_export_path`) needs no heavy deps.
- **Privacy:** the input returns pass through
  :func:`~openbb_backtest.analytics._common.assert_normalized` first, so only
  normalized returns are ever rendered — no dollar amounts / account / lot detail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pandas as pd

from openbb_backtest.analytics._common import assert_normalized, optional_import
from openbb_backtest.settings import DEFAULT_SETTINGS

#: Stem prefix for the deterministic, timestamped artifact file name.
_NAME_PREFIX = "tearsheet"
_TIMESTAMP_FMT = "%Y%m%d_%H%M%S"


def _quantstats() -> ModuleType:
    """Import quantstats or raise an actionable :class:`ImportError`.

    Export has no in-house fallback (the report *is* quantstats' output), so the
    absence of the library is a hard, actionable error naming the pip package.
    """
    return optional_import("quantstats")


def export_html(
    returns: pd.Series,
    *,
    export_dir: str | None = None,
    name: str | None = None,
    title: str = "Backtest Tear Sheet",
    timestamp: datetime | None = None,
) -> str:
    """Render a quantstats HTML report for ``returns`` and return its file path.

    Parameters
    ----------
    returns
        Normalized per-session float returns (validated by the privacy gate).
    export_dir
        Output directory; created if missing. Defaults to
        ``DEFAULT_SETTINGS.export_dir`` (``Analysis/exports``).
    name
        Optional file stem; an ``.html`` suffix is enforced. Defaults to a
        deterministic ``tearsheet_<YYYYMMDD_HHMMSS>.html`` from ``timestamp``.
    title
        Report title passed to quantstats.
    timestamp
        Timestamp used for the default file name; defaults to "now" (UTC).

    Returns
    -------
    str
        The path to the written HTML artifact (never the blob itself).
    """
    assert_normalized(returns)
    directory = export_dir if export_dir is not None else DEFAULT_SETTINGS.export_dir
    out_path = _resolve_export_path(name, directory, timestamp)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    qs = _quantstats()  # actionable ImportError when absent (no fallback)
    _write_report(qs, returns, out_path, title)
    return str(out_path)


def _resolve_export_path(
    name: str | None, export_dir: str, timestamp: datetime | None
) -> Path:
    """Compute the artifact path: ``<export_dir>/<name or timestamped>.html``.

    Pure and dependency-free (no quantstats), so it can be exercised — and the
    file name asserted deterministic — without importing any heavy library.
    """
    if name:
        stem = name[:-5] if name.endswith(".html") else name
    else:
        when = timestamp or datetime.now(timezone.utc)
        stem = f"{_NAME_PREFIX}_{when.strftime(_TIMESTAMP_FMT)}"
    return Path(export_dir) / f"{stem}.html"


def _write_report(qs: ModuleType, returns: pd.Series, out_path: Path, title: str) -> None:
    """Render the quantstats HTML report to ``out_path`` (the heavy seam).

    Isolated so unit tests can stub the actual render while still exercising the
    path-resolution, directory-creation and privacy logic of :func:`export_html`.
    Forces matplotlib's non-interactive ``Agg`` backend first: export writes a
    file (never shows a window), so this keeps the render headless-safe (no Tk).
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    qs.reports.html(returns, output=str(out_path), title=title)
