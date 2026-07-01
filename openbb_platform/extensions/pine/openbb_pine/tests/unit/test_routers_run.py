"""Tests for :mod:`openbb_pine.routers.run_router` and ``strategies_router``.

Post-flip (bead 0e9.5.61) — /pine/run now calls the real compile → execute
chain. Tests mock ``run_compiled`` so they stay hermetic (no FMP key
required, no real network). Real end-to-end integration lives at
``tests/integration/test_pine_run_e2e.py``.

/pine/strategies/run still returns HTTP 501 at M1 (strategies land at M2
per PRD §3.2).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from openbb_core.app.model.obbject import OBBject

from openbb_pine.errors import (
    PineDataValidationError,
    PineProviderError,
    PineStrategyNotYetImplementedError,
)
from openbb_pine.routers._models import PineByoData


def _run_async(coro):
    return asyncio.run(coro)


_TRIVIAL_SRC = "//@version=6\nindicator(\"BB\")\nplot(close)\n"


def _fake_obbject() -> OBBject:
    """Minimal OBBject the mocked run_compiled returns."""
    return OBBject(
        results=[],
        extra={
            "alerts": [],
            "orders": [],
            "attribution": "Powered by PyneSys (https://pynesys.io)",
            "compile_cache_hit": False,
            "exec_ms": 42,
            "provider_used": "fmp_cached",
            "bars_consumed": 0,
        },
    )


# ---------------------------------------------------------------------------
# /pine/run — real compile+execute path (mocked runtime)
# ---------------------------------------------------------------------------


def test_run_valid_fmp_request_reaches_run_compiled():
    """Valid FMP request flows through compile_pine + run_compiled to OBBject."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        mock_run.return_value = _fake_obbject()
        result = _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))

    assert isinstance(result, OBBject)
    assert mock_run.called
    kwargs = mock_run.call_args.kwargs
    # provider_or_data is the provider string in this path
    assert kwargs["provider_or_data"] == "fmp"
    assert kwargs["symbol"] == "AAPL"


def test_run_returns_obbject_with_attribution_and_extra_keys():
    """OBBject carries D2 §6.1 .extra keys (surface #1 attribution path)."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        mock_run.return_value = _fake_obbject()
        result = _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))

    assert "attribution" in result.extra
    assert "PyneSys" in result.extra["attribution"]
    for key in ("alerts", "orders", "compile_cache_hit", "exec_ms",
                "provider_used", "bars_consumed"):
        assert key in result.extra


def test_run_fmp_cached_provider_flows_through():
    """``fmp_cached`` reaches run_compiled with that provider name."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        mock_run.return_value = _fake_obbject()
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp_cached", symbol="AAPL"))

    assert mock_run.call_args.kwargs["provider_or_data"] == "fmp_cached"


def test_run_byo_records_materialises_to_dataframe():
    """BYO records payload becomes pd.DataFrame threaded into run_compiled."""
    import pandas as pd
    from openbb_pine.routers.run_router import run

    records = [
        {"date": "2024-01-02T00:00:00Z", "open": 184.1, "high": 186.4,
         "low": 183.9, "close": 185.6, "volume": 52341900},
        {"date": "2024-01-03T00:00:00Z", "open": 185.6, "high": 187.0,
         "low": 184.2, "close": 186.8, "volume": 48200100},
    ]
    data = PineByoData(format="records", records=records)

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        mock_run.return_value = _fake_obbject()
        _run_async(run(source=_TRIVIAL_SRC, data=data, symbol="PRIVATE"))

    passed = mock_run.call_args.kwargs["provider_or_data"]
    assert isinstance(passed, pd.DataFrame)
    assert list(passed.columns) == ["open", "high", "low", "close", "volume"]
    assert len(passed) == 2
    assert passed.index.tz is not None  # tz-aware per BYODataProvider schema


def test_run_byo_parquet_url_not_yet_wired():
    """Non-records BYO formats raise PineDataValidationError at M1 per PRD §4.10."""
    from openbb_pine.routers.run_router import run

    data = PineByoData(format="parquet_url", url="https://example/x.parquet")
    with pytest.raises(PineDataValidationError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, data=data, symbol="X"))
    assert "records" in str(ei.value)
    assert "parquet_url" in str(ei.value)


def test_run_byo_empty_records_raises():
    """Empty records list is a schema defect — caught at PineByoData model layer."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as ei:
        PineByoData(format="records", records=[])
    assert "non-empty" in str(ei.value).lower() or "records" in str(ei.value).lower()


def test_run_byo_missing_date_column_raises():
    """Records without a date column are rejected."""
    from openbb_pine.routers.run_router import run

    data = PineByoData(format="records", records=[{"close": 1.0}])
    with pytest.raises(PineDataValidationError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, data=data, symbol="X"))
    assert "date" in str(ei.value).lower()


def test_run_non_fmp_provider_raises_pine_provider_error_first():
    """Non-FMP names MUST raise PineProviderError BEFORE hitting compile_pine.

    Clients see the structured FMP-only message instead of a downstream
    compile/exec error that masks the user's provider mistake.
    """
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        with pytest.raises(PineProviderError) as ei:
            _run_async(run(source=_TRIVIAL_SRC, provider="yahoo", symbol="AAPL"))
    # run_compiled must NOT have been called
    assert not mock_run.called
    msg = str(ei.value).lower()
    assert "fmp" in msg
    assert "yahoo" in msg


def test_run_without_provider_or_data_raises_validation_error():
    """At least one of provider+symbol or data must be set."""
    from openbb_pine.routers.run_router import run

    with pytest.raises((ValueError, Exception)) as ei:
        _run_async(run(source=_TRIVIAL_SRC))
    cls_name = type(ei.value).__name__
    assert cls_name in ("ValueError", "ValidationError")


def test_run_provider_without_symbol_raises_validation_error():
    from openbb_pine.routers.run_router import run

    with pytest.raises((ValueError, Exception)) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp"))
    cls_name = type(ei.value).__name__
    assert cls_name in ("ValueError", "ValidationError")


def test_run_iso_dates_parsed_to_utc_datetimes():
    """`start`/`end` ISO strings become tz-aware UTC datetimes for run_compiled."""
    from datetime import datetime, timezone as tz
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        mock_run.return_value = _fake_obbject()
        _run_async(run(
            source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL",
            start="2024-01-01", end="2024-12-31",
        ))

    kw = mock_run.call_args.kwargs
    assert isinstance(kw["start"], datetime)
    assert isinstance(kw["end"], datetime)
    assert kw["start"].tzinfo == tz.utc
    assert kw["end"].tzinfo == tz.utc


def test_run_threads_params_and_timeout_through():
    """`params` and `timeout_s` reach run_compiled."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run:
        mock_run.return_value = _fake_obbject()
        _run_async(run(
            source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL",
            params={"length": 20}, timeout_s=15,
        ))
    kw = mock_run.call_args.kwargs
    assert kw["params"] == {"length": 20}
    assert kw["timeout_s"] == 15


# ---------------------------------------------------------------------------
# /pine/strategies/run — 501 always at M1 (unchanged)
# ---------------------------------------------------------------------------


def test_strategies_run_raises_501_always_m1():
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))
    assert "M2" in str(ei.value)
    assert "0e9.5.6" in str(ei.value)


def test_strategies_run_501_even_with_byo_data():
    from openbb_pine.routers.strategies_router import run

    data = PineByoData(format="records", records=[{"close": 1.0}])
    with pytest.raises(PineStrategyNotYetImplementedError):
        _run_async(run(source=_TRIVIAL_SRC, data=data))


def test_strategies_run_501_even_with_no_provider_or_data():
    """M1 strategies router does not validate input shape; always 501."""
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError):
        _run_async(run(source=_TRIVIAL_SRC))


def test_strategies_run_501_carries_strategy_params():
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError):
        _run_async(
            run(
                source=_TRIVIAL_SRC,
                provider="fmp",
                symbol="AAPL",
                strategy_params={"initial_capital": 100_000},
            )
        )


# ---------------------------------------------------------------------------
# Route registration — OpenAPI surface locks
# ---------------------------------------------------------------------------


def test_run_router_registers_run_route():
    from openbb_pine.routers.run_router import router

    paths = {r.path for r in router.api_router.routes}
    assert "/run" in paths


def test_strategies_router_registers_run_route_under_strategies():
    from openbb_pine.routers.strategies_router import router

    paths = {r.path for r in router.api_router.routes}
    assert "/strategies/run" in paths
