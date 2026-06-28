"""Integration tests for ``analytics/export.py`` against real ``quantstats``.

These perform an actual quantstats one-call HTML render (heavy: pulls matplotlib
and builds a full report), so they are skipped via ``importorskip`` when quantstats
is not installed. They assert the artifact is genuinely written to disk and that
:func:`export_html` returns its path. The path/privacy/lazy-import contract is
covered by the fast unit suite (render stubbed).

Marked ``integration`` so ``-m "not integration"`` excludes them.

See ``docs/designs/backtest-design/07-analytics.md`` §2.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("quantstats")

pytestmark = pytest.mark.integration


def _returns(n: int = 120) -> pd.Series:
    idx = pd.date_range("2021-01-04", periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(3)
    vals = rng.normal(0.0006, 0.011, n)
    vals[0] = 0.0
    return pd.Series(vals, index=idx, name="returns")


def test_export_html_renders_real_report(tmp_path):
    from openbb_backtest.analytics.export import export_html

    path = export_html(_returns(), export_dir=str(tmp_path))
    assert os.path.isfile(path)
    assert path.endswith(".html")
    # A real quantstats report is a non-trivial HTML document.
    contents = Path(path).read_text(encoding="utf-8")
    assert len(contents) > 1000
    assert "<html" in contents.lower()


def test_export_html_under_default_export_dir(tmp_path, monkeypatch):
    from openbb_backtest.analytics import export as e
    from openbb_backtest.analytics.export import export_html

    # Point the default at a temp dir so we don't litter Analysis/exports.
    monkeypatch.setattr(e.DEFAULT_SETTINGS, "export_dir", str(tmp_path))
    path = export_html(_returns())
    assert os.path.isfile(path)
    assert os.path.dirname(os.path.abspath(path)) == str(tmp_path)
