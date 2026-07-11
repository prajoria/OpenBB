"""strategies_router.run_byo — bd-250 (mirrors bd-4d0 run() facade for BYO records).

D5 §8.2 — /pine/strategies/run_byo takes caller-supplied OHLCV records
(list[dict]) instead of provider parameters. Mirrors the facade-split
pattern established by bd-0e9.11 (indicators_router.run_byo).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from openbb_pine.routers.strategies_router import run_byo


def _run_async(coro):
    return asyncio.run(coro)


_STRAT_SRC = '//@version=6\nstrategy("s")\nplot(close)\n'
_IND_SRC = '//@version=6\nindicator("i")\nplot(close)\n'
_REC = [
    {"date": "2024-01-01", "open": 100.0, "high": 101.0, "low": 99.0,
     "close": 100.5, "volume": 1000},
]


def test_run_byo_converts_records_and_dispatches():
    """run_byo converts records -> df, then calls _compile_and_run with the df."""
    fake_df = MagicMock()
    fake_result = MagicMock()
    fake_result.extra = {"script_type": "strategy"}
    with patch(
        "openbb_pine.routers.strategies_router._byo_records_to_dataframe",
        return_value=fake_df,
    ) as mock_conv, patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ) as mock_car:
        result = _run_async(run_byo(source=_STRAT_SRC, records=_REC))
    mock_conv.assert_called_once()
    mock_car.assert_called_once()
    call_kwargs = mock_car.call_args.kwargs
    assert call_kwargs.get("provider_or_data") is fake_df
    assert result is fake_result


def test_run_byo_raises_pt099_when_source_is_indicator():
    """Same PT099 gate as run() — indicator source rejected here."""
    from openbb_pine.errors import PineTypeError

    fake_df = MagicMock()
    fake_result = MagicMock()
    fake_result.extra = {"script_type": "indicator"}
    with patch(
        "openbb_pine.routers.strategies_router._byo_records_to_dataframe",
        return_value=fake_df,
    ), patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ):
        with pytest.raises(PineTypeError) as exc:
            _run_async(run_byo(source=_IND_SRC, records=_REC))
    assert exc.value.rule == "PT099"
    assert "strategy" in str(exc.value).lower()


def test_run_byo_applies_strategy_params():
    """strategy_params dict is forwarded via _apply_strategy_params."""
    fake_df = MagicMock()
    fake_result = MagicMock()
    fake_result.extra = {"script_type": "strategy"}
    with patch(
        "openbb_pine.routers.strategies_router._byo_records_to_dataframe",
        return_value=fake_df,
    ), patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ), patch(
        "openbb_pine.routers.strategies_router._apply_strategy_params"
    ) as mock_asp:
        _run_async(
            run_byo(
                source=_STRAT_SRC,
                records=_REC,
                strategy_params={"initial_capital": 25000},
            )
        )
    mock_asp.assert_called_once()
    call_args = mock_asp.call_args
    assert call_args[0][0] is fake_result
    assert call_args[0][1] == {"initial_capital": 25000}


def test_run_byo_passes_tz_and_symbol_to_helpers():
    """tz threads into _byo_records_to_dataframe; symbol threads into _compile_and_run."""
    fake_df = MagicMock()
    fake_result = MagicMock()
    fake_result.extra = {"script_type": "strategy"}
    with patch(
        "openbb_pine.routers.strategies_router._byo_records_to_dataframe",
        return_value=fake_df,
    ) as mock_conv, patch(
        "openbb_pine.routers.strategies_router._compile_and_run",
        return_value=fake_result,
    ) as mock_car:
        _run_async(
            run_byo(
                source=_STRAT_SRC,
                records=_REC,
                symbol="CUSTOM",
                tz="America/New_York",
            )
        )
    conv_kwargs = mock_conv.call_args.kwargs
    assert conv_kwargs.get("tz") == "America/New_York"
    car_kwargs = mock_car.call_args.kwargs
    assert car_kwargs.get("symbol") == "CUSTOM"
