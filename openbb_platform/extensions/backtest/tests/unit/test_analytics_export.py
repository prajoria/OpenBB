"""Unit tests for ``analytics/export.py`` (component 07, §2 export).

Covers :func:`export_html`, which renders a one-call quantstats HTML tear-sheet
report from a normalized return series, writes it under the configured
``export_dir`` (default ``Analysis/exports``), and returns the **file path only**
(to populate :attr:`TearSheet.html_path`) — never an embedded blob.

The *real* quantstats render is heavy (matplotlib, full report) and lives in
``tests/integration/test_analytics_export_integration.py`` (importorskip). These
unit tests instead exercise the path / privacy / lazy-import contract by stubbing
the render seam, so they stay fast and dependency-light. Unlike the metrics/tear
sheet layers, export has **no fallback**: quantstats is required, and its absence
must raise an actionable :class:`ImportError`.

See ``docs/designs/backtest-design/07-analytics.md`` §2 and
``openbb_backtest.settings.DEFAULT_SETTINGS.export_dir``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_BACKTEST_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_TS = datetime(2021, 1, 4, 9, 30, 0, tzinfo=timezone.utc)


def _returns(n: int = 30) -> pd.Series:
    idx = pd.date_range("2021-01-04", periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(0)
    vals = rng.normal(0.0005, 0.01, n)
    vals[0] = 0.0
    return pd.Series(vals, index=idx, name="returns")


def _stub_render(monkeypatch) -> None:
    """Replace the quantstats render seam with a tiny placeholder writer."""
    import openbb_backtest.analytics.export as e

    def _fake(qs, returns, out_path, title):  # noqa: ARG001
        out_path.write_text("<html><body>stub</body></html>", encoding="utf-8")

    monkeypatch.setattr(e, "_quantstats", lambda: object())
    monkeypatch.setattr(e, "_write_report", _fake)


# ---- happy path (render stubbed) -----------------------------------------


def test_export_html_writes_file_and_returns_path(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    path = export_html(_returns(), export_dir=str(tmp_path), timestamp=_TS)

    assert isinstance(path, str)
    assert os.path.isfile(path)
    # Deterministic timestamped name under export_dir.
    assert os.path.basename(path) == "tearsheet_20210104_093000.html"
    assert os.path.dirname(os.path.abspath(path)) == str(tmp_path)


def test_export_html_creates_export_dir_if_missing(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    nested = tmp_path / "deep" / "exports"
    assert not nested.exists()
    path = export_html(_returns(), export_dir=str(nested), timestamp=_TS)
    assert nested.is_dir()
    assert os.path.isfile(path)


def test_export_html_deterministic_name_from_timestamp(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    a = export_html(_returns(), export_dir=str(tmp_path), timestamp=_TS)
    b = export_html(_returns(), export_dir=str(tmp_path), timestamp=_TS)
    assert os.path.basename(a) == os.path.basename(b)


def test_export_html_returns_path_not_blob(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    path = export_html(_returns(), export_dir=str(tmp_path), timestamp=_TS)
    # The return value is the path string, not the file contents (no embedded blob).
    blob = Path(path).read_text(encoding="utf-8")
    assert path != blob
    assert "<html" not in path
    assert path.endswith(".html")
    assert os.path.isfile(path)


def test_custom_name_is_honored_and_gets_html_suffix(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    path = export_html(
        _returns(), export_dir=str(tmp_path), name="myreport", timestamp=_TS
    )
    assert os.path.basename(path) == "myreport.html"


# ---- privacy gate --------------------------------------------------------


def test_export_html_rejects_non_normalized_returns(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    dollars = pd.Series(
        [100000.0, 101000.0, 99990.0],
        index=pd.date_range("2021-01-04", periods=3, freq="D", tz="UTC"),
    )
    with pytest.raises(ValueError):
        export_html(dollars, export_dir=str(tmp_path), timestamp=_TS)


def test_export_html_rejects_decimal_returns(tmp_path, monkeypatch):
    from openbb_backtest.analytics.export import export_html

    _stub_render(monkeypatch)
    decimals = pd.Series([Decimal("0.01"), Decimal("-0.02")])
    with pytest.raises((TypeError, ValueError)):
        export_html(decimals, export_dir=str(tmp_path), timestamp=_TS)


# ---- quantstats required (no fallback) -----------------------------------


def test_export_html_raises_actionable_importerror_when_quantstats_absent(
    tmp_path, monkeypatch
):
    from openbb_backtest.analytics.export import export_html

    # Force quantstats to be unavailable; export has NO fallback, so it must
    # raise an actionable ImportError naming the pip package.
    monkeypatch.setitem(sys.modules, "quantstats", None)
    with pytest.raises(ImportError) as exc:
        export_html(_returns(), export_dir=str(tmp_path), timestamp=_TS)
    message = str(exc.value)
    assert "quantstats" in message
    assert "pip install" in message


# ---- lazy-import guard ---------------------------------------------------


def test_export_module_imports_with_heavy_deps_absent():
    """Importing the module + the pure path resolver must need no heavy deps."""
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_BACKTEST_ROOT!r})
        for m in ("quantstats", "pyfolio", "ffn", "numba"):
            sys.modules[m] = None
        from datetime import datetime, timezone
        import openbb_backtest.analytics.export as e
        p = e._resolve_export_path(None, "out_dir", datetime(2021, 1, 4, 9, 30, tzinfo=timezone.utc))
        assert p.name == "tearsheet_20210104_093000.html"
        print("OK", p.name)
        """
    )
    # Fixed self-authored script via the current interpreter — the S603 precondition.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK tearsheet_20210104_093000.html" in result.stdout


# ---------------------------------------------------------------------------
# Path-traversal defenses (bd-cwer, closes h1u8 / m7q4)
# ---------------------------------------------------------------------------


def test_resolve_export_path_rejects_parent_traversal(tmp_path):
    """``name='../evil'`` must not escape ``export_dir``.

    Regression test for OpenBBTechnical-h1u8 / m7q4: prior code let a
    caller-supplied ``name`` with ``..`` segments resolve outside the
    approved export directory, giving quantstats an arbitrary write path.
    """
    from openbb_backtest.analytics.export import _resolve_export_path
    from openbb_core.app.paths import PathTraversalError

    with pytest.raises(PathTraversalError):
        _resolve_export_path("../evil", str(tmp_path), _TS)


def test_resolve_export_path_rejects_absolute_name(tmp_path):
    """Absolute-path ``name`` overrides ``export_dir`` under naive Path join — reject."""
    from openbb_backtest.analytics.export import _resolve_export_path
    from openbb_core.app.paths import PathTraversalError

    absolute = "/tmp/evil" if os.name != "nt" else "C:/Windows/evil"
    with pytest.raises(PathTraversalError):
        _resolve_export_path(absolute, str(tmp_path), _TS)


def test_resolve_export_path_rejects_windows_drive_relative(tmp_path):
    """Windows drive-relative ``C:evil`` bypasses ``is_absolute()`` — safe_join rejects."""
    from openbb_backtest.analytics.export import _resolve_export_path
    from openbb_core.app.paths import PathTraversalError

    if os.name != "nt":
        pytest.skip("drive-relative paths are Windows-specific")
    with pytest.raises(PathTraversalError):
        _resolve_export_path("C:evil", str(tmp_path), _TS)


def test_resolve_export_path_creates_export_dir_if_missing(tmp_path):
    """The ``export_dir`` doesn't have to exist yet — safe_join tolerates it via mkdir."""
    from openbb_backtest.analytics.export import _resolve_export_path

    fresh_dir = tmp_path / "not_yet"
    fresh_dir.mkdir()
    out = _resolve_export_path("myreport", str(fresh_dir), _TS)
    assert out == (fresh_dir / "myreport.html").resolve()


def test_resolve_export_path_default_name_still_works(tmp_path):
    """When ``name=None``, the timestamp-derived default is composed via safe_join."""
    from openbb_backtest.analytics.export import _resolve_export_path

    out = _resolve_export_path(None, str(tmp_path), _TS)
    assert out.name == "tearsheet_20210104_093000.html"
    assert out.parent == tmp_path.resolve()
