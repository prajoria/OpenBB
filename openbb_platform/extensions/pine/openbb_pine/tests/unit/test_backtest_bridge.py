"""Tests for :mod:`openbb_pine.runtime.backtest_bridge` (#590).

The bridge is the soft-dep integration point between Pine strategy runs
and ``openbb-backtest``'s analytics layer. D5 §6.1 is the ground-truth
spec:

* Consume: ``openbb-backtest`` is optional. When installed, we hand off
  strategy results to its ``ingest_pine_strategy`` for KPI analytics
  cross-referencing.
* When ``openbb-backtest`` is NOT installed, we no-op and append a
  once-per-call warning to ``result.extra["warnings"]`` (D5 §6.1 text is
  ``setdefault("warnings", []).append(...)`` — per-call, not de-duplicated;
  see PR #(TBD) for the design decision).
* When the result is NOT a strategy (e.g. an indicator result routed
  through the wrong seam), no-op silently — no import attempt, no warning.

Deferred to #589 (the shape adapter): the actual payload translation
from ``strategy_result.extra["stats"]/["orders"]`` into openbb-backtest's
``BacktestResult`` model. #590 only ships the guard + call-site wiring;
#589 fills in ``ingest_pine_strategy``'s payload contract.
"""

from __future__ import annotations

import sys

import pytest
from openbb_core.app.model.obbject import OBBject


def _make_strategy_result(**extra_overrides: object) -> OBBject:
    """Build a minimal OBBject with the shape a strategy run produces.

    The bridge only reads ``result.extra`` — no fields other than
    ``script_type`` (guard) and ``warnings`` (append target) are
    consulted at #590 scope. The stub payload in ``extra["stats"]`` and
    ``extra["orders"]`` are there so any smoke test of the happy-path
    hand-off has something plausible-shaped to look at.
    """
    extra: dict[str, object] = {
        "script_type": "strategy",
        "stats": {"initial_capital": 100_000.0, "final_equity": 105_000.0},
        "orders": [],
    }
    extra.update(extra_overrides)
    obj = OBBject(results=None)
    obj.extra = extra
    return obj


# ---------------------------------------------------------------------------
# Import-guard behavior — openbb_backtest NOT installed
# ---------------------------------------------------------------------------


def test_maybe_export_no_op_when_openbb_backtest_missing(monkeypatch):
    """When ``openbb_backtest`` cannot be imported, the bridge appends a
    warning to ``extra['warnings']`` and returns without raising.

    Simulates the absent-dep case by setting ``sys.modules['openbb_backtest']``
    to ``None`` — the import machinery's convention for "this module was
    tried and cannot be imported" (see :pep:`328`). This is more robust
    than mocking ``builtins.__import__`` because it exercises the exact
    ``from openbb_backtest.analytics import ingest_pine_strategy`` path
    the bridge uses.
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    # Force the import to fail regardless of whether openbb_backtest is
    # actually installed in this venv.
    monkeypatch.setitem(sys.modules, "openbb_backtest", None)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", None)

    result = _make_strategy_result()
    ret = maybe_export_to_backtest(result)

    assert ret is None, "bridge should return None (side-effect only)"
    warnings = result.extra.get("warnings", [])
    assert len(warnings) == 1
    assert "openbb-backtest" in warnings[0]
    assert "install" in warnings[0].lower()


def test_maybe_export_warning_message_shape(monkeypatch):
    """The warning message must be human-readable AND point at the docs
    section that explains how to install and use the integration.

    Per D5 §6.1: the exact wording is *"openbb-backtest not installed —
    install it to enable KPI analytics cross-referencing. See README
    §Analytics integration."*
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    monkeypatch.setitem(sys.modules, "openbb_backtest", None)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", None)

    result = _make_strategy_result()
    maybe_export_to_backtest(result)

    msg = result.extra["warnings"][0]
    # Diagnostic sanity: names the missing package AND points at docs.
    assert "openbb-backtest" in msg
    assert "not installed" in msg or "install" in msg.lower()
    # D5 says "See README §Analytics integration." — a docs pointer must
    # be present so a user hitting this warning knows where to look.
    assert "README" in msg or "docs" in msg.lower() or "Analytics" in msg


def test_maybe_export_preserves_existing_warnings_when_appending(monkeypatch):
    """If ``extra['warnings']`` already has entries (e.g. from an
    earlier step in the pipeline), the bridge appends to the list
    rather than replacing it.
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    monkeypatch.setitem(sys.modules, "openbb_backtest", None)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", None)

    result = _make_strategy_result(warnings=["earlier: something else"])
    maybe_export_to_backtest(result)

    warnings = result.extra["warnings"]
    assert len(warnings) == 2
    assert warnings[0] == "earlier: something else"
    assert "openbb-backtest" in warnings[1]


def test_maybe_export_creates_warnings_list_when_absent(monkeypatch):
    """When ``extra['warnings']`` is missing entirely, the bridge must
    create the list via ``setdefault`` — never crash on missing key.

    D5 §6.1 uses ``setdefault("warnings", []).append(...)`` explicitly.
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    monkeypatch.setitem(sys.modules, "openbb_backtest", None)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", None)

    result = _make_strategy_result()
    # Explicitly ensure 'warnings' is NOT in extra
    result.extra.pop("warnings", None)
    assert "warnings" not in result.extra

    maybe_export_to_backtest(result)
    assert "warnings" in result.extra
    assert len(result.extra["warnings"]) == 1


# ---------------------------------------------------------------------------
# Non-strategy guard — the bridge must silently no-op for indicator results
# ---------------------------------------------------------------------------


def test_maybe_export_short_circuits_on_indicator_result(monkeypatch):
    """A result with ``script_type != "strategy"`` (e.g. an indicator
    result routed to this seam by mistake) must silently no-op — no
    import attempt, no warning.

    Rationale: only strategy runs produce trade lists / equity curves.
    An indicator result has nothing openbb-backtest can consume, so the
    warning would be misleading (blaming a missing openbb-backtest for
    the absence of data that never existed).
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    # If the bridge attempted the import, this monkeypatch would trigger
    # the warning path; the test would then see a warning appended and
    # fail its assertion.
    monkeypatch.setitem(sys.modules, "openbb_backtest", None)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", None)

    result = _make_strategy_result(script_type="indicator")
    ret = maybe_export_to_backtest(result)

    assert ret is None
    assert (
        result.extra.get("warnings", []) == []
    ), "bridge should NOT append a warning for non-strategy results"


def test_maybe_export_short_circuits_when_script_type_missing(monkeypatch):
    """No ``script_type`` at all → treat as non-strategy → no-op.

    We assume-strategy only when the caller has explicitly stamped
    ``script_type='strategy'``. Anything else is out of the bridge's
    jurisdiction.
    """
    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    monkeypatch.setitem(sys.modules, "openbb_backtest", None)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", None)

    result = _make_strategy_result()
    result.extra.pop("script_type", None)

    maybe_export_to_backtest(result)
    assert result.extra.get("warnings", []) == []


# ---------------------------------------------------------------------------
# Happy path — openbb_backtest IS installed
# ---------------------------------------------------------------------------


def test_maybe_export_calls_ingest_pine_strategy_when_available(monkeypatch):
    """When ``openbb_backtest.analytics.ingest_pine_strategy`` is
    importable, the bridge calls it with the strategy_result and does
    NOT append a warning.

    Uses a synthetic ``openbb_backtest.analytics`` module (with a
    tracking mock ``ingest_pine_strategy``) planted in ``sys.modules``
    so the test does not depend on the real ``openbb-backtest`` package
    being installed.
    """
    import types

    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    called_with: list[object] = []

    def _fake_ingest(res: object) -> None:
        called_with.append(res)

    fake_analytics = types.ModuleType("openbb_backtest.analytics")
    fake_analytics.ingest_pine_strategy = _fake_ingest  # type: ignore[attr-defined]
    fake_pkg = types.ModuleType("openbb_backtest")
    fake_pkg.analytics = fake_analytics  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "openbb_backtest", fake_pkg)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", fake_analytics)

    result = _make_strategy_result()
    maybe_export_to_backtest(result)

    assert called_with == [result], (
        "ingest_pine_strategy should be called exactly once with the " "OBBject result"
    )
    assert (
        result.extra.get("warnings", []) == []
    ), "no warning should be appended on the happy path"


def test_maybe_export_does_not_swallow_ingest_pine_strategy_errors(monkeypatch):
    """If ``ingest_pine_strategy`` itself raises (a real bug in the
    downstream analytics layer, NOT a missing-dep case), the exception
    should propagate.

    Silently swallowing a real downstream failure would violate CLAUDE.md
    R7.3 (loud empties) — the caller needs to see the exception to
    diagnose. Only the ``ImportError`` case (dep genuinely absent) is
    absorbed by the bridge.
    """
    import types

    from openbb_pine.runtime.backtest_bridge import maybe_export_to_backtest

    class DownstreamBug(RuntimeError):
        pass

    def _broken_ingest(res: object) -> None:
        raise DownstreamBug("simulated openbb-backtest internal error")

    fake_analytics = types.ModuleType("openbb_backtest.analytics")
    fake_analytics.ingest_pine_strategy = _broken_ingest  # type: ignore[attr-defined]
    fake_pkg = types.ModuleType("openbb_backtest")
    fake_pkg.analytics = fake_analytics  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "openbb_backtest", fake_pkg)
    monkeypatch.setitem(sys.modules, "openbb_backtest.analytics", fake_analytics)

    result = _make_strategy_result()
    with pytest.raises(DownstreamBug, match="simulated"):
        maybe_export_to_backtest(result)
