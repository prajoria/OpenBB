"""strategies_router.run flip from 501 to real (bd-4d0).

Mirrors the facade-split pattern from bd-0e9.11 (indicators_router.run).
D5 §8.1.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from openbb_pine.routers.strategies_router import run


def _run_async(coro):
    return asyncio.run(coro)


_STRAT_SRC = '//@version=6\nstrategy("s")\nplot(close)\n'
_IND_SRC = '//@version=6\nindicator("i")\nplot(close)\n'


def test_run_dispatches_to_compile_and_run():
    """Non-501 code path: run() calls _compile_and_run and returns its OBBject."""
    fake_result = MagicMock()
    fake_result.extra = {"script_type": "strategy", "stats": {"net_profit": 0.0}}
    with patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ) as mock_car, patch(
        "openbb_pine.routers.strategies_router.resolve_provider"
    ) as mock_rp:
        result = _run_async(run(source=_STRAT_SRC))
    mock_rp.assert_called_once()
    mock_car.assert_called_once()
    assert result is fake_result


def test_run_raises_pt099_when_source_is_indicator():
    """If the compiled source's script_type isn't 'strategy', reject with PT099."""
    from openbb_pine.errors import PineTypeError

    fake_result = MagicMock()
    fake_result.extra = {"script_type": "indicator"}
    with patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ), patch("openbb_pine.routers.strategies_router.resolve_provider"):
        with pytest.raises(PineTypeError) as exc:
            _run_async(run(source=_IND_SRC))
    assert exc.value.rule == "PT099"
    assert "strategy" in str(exc.value).lower()


def test_run_applies_strategy_params():
    """strategy_params dict is forwarded via _apply_strategy_params."""
    fake_result = MagicMock()
    fake_result.extra = {"script_type": "strategy"}
    with patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ), patch("openbb_pine.routers.strategies_router.resolve_provider"), patch(
        "openbb_pine.routers.strategies_router._apply_strategy_params"
    ) as mock_asp:
        _run_async(
            run(source=_STRAT_SRC, strategy_params={"initial_capital": 50000})
        )
    mock_asp.assert_called_once()
    call_args = mock_asp.call_args
    assert call_args[0][0] is fake_result
    assert call_args[0][1] == {"initial_capital": 50000}


def test_run_no_longer_raises_501_or_not_implemented():
    """Regression: flip from 501 stub — run must reach _compile_and_run, not raise."""
    from pyne_compiler.errors.base import PineStrategyNotYetImplementedError

    fake_result = MagicMock()
    fake_result.extra = {"script_type": "strategy"}
    with patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ), patch("openbb_pine.routers.strategies_router.resolve_provider"):
        try:
            result = _run_async(run(source=_STRAT_SRC))
        except PineStrategyNotYetImplementedError:  # pragma: no cover - regression
            pytest.fail(
                "strategies_router.run still raises PineStrategyNotYetImplementedError"
            )
    assert result is fake_result
