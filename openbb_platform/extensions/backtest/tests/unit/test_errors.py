"""Unit tests for the backtest error hierarchy (component 09.1).

All backtest errors subclass OpenBB's :class:`OpenBBError` so the router surfaces
them as standard platform errors. :class:`OptionalDependencyError` must carry an
*actionable* pip-install hint, and :class:`EngineSelectionError` must name the
offending engine alongside the valid choices.

See ``docs/designs/backtest-design/09-api-surface.md`` §2.
"""

from __future__ import annotations

import pytest


def test_backtest_error_subclasses_openbb_error():
    from openbb_backtest.errors import BacktestError
    from openbb_core.app.model.abstract.error import OpenBBError

    assert issubclass(BacktestError, OpenBBError)


def test_optional_dependency_error_subclasses_backtest_error():
    from openbb_backtest.errors import BacktestError, OptionalDependencyError

    assert issubclass(OptionalDependencyError, BacktestError)


def test_engine_selection_error_subclasses_backtest_error():
    from openbb_backtest.errors import BacktestError, EngineSelectionError

    assert issubclass(EngineSelectionError, BacktestError)


def test_optional_dependency_error_has_actionable_pip_message():
    from openbb_backtest.errors import OptionalDependencyError

    err = OptionalDependencyError("zipline-reloaded", feature="the event-driven engine")
    msg = str(err)
    assert "zipline-reloaded" in msg
    assert "pip install" in msg
    assert "the event-driven engine" in msg


def test_optional_dependency_error_extra_install_target():
    from openbb_backtest.errors import OptionalDependencyError

    err = OptionalDependencyError("numba", extra="event")
    # When an extras group is given, the hint points at the package extra.
    assert "openbb-backtest[event]" in str(err)
    assert err.dependency == "numba"


def test_engine_selection_error_lists_available_choices():
    from openbb_backtest.errors import EngineSelectionError

    err = EngineSelectionError("turbo", available=["auto", "vectorized", "event"])
    msg = str(err)
    assert "turbo" in msg
    assert "vectorized" in msg and "event" in msg
    assert err.requested == "turbo"


def test_errors_are_raisable_and_catchable_as_openbb_error():
    from openbb_backtest.errors import EngineSelectionError
    from openbb_core.app.model.abstract.error import OpenBBError

    with pytest.raises(OpenBBError):
        raise EngineSelectionError("bogus", available=["auto"])
