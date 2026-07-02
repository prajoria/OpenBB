"""Tests for :mod:`openbb_pine.routers.run_router` and ``strategies_router``.

Facade-split per bead 0e9.11 (smoke test 0e9.9 STEP 4 finding): the single
``/pine/run`` endpoint was split into ``/pine/run`` (provider-only) and
``/pine/run_byo`` (BYO records-only) to sidestep openbb-core ``@validate``
``Union[list, dict, DataFrame, Data, …]`` coercion that rejected the
``data`` param's ``None`` default.

Tests mock ``run_compiled`` + ``compile_pine`` so they stay hermetic
(no FMP key required, no real network). Real end-to-end integration lives
at ``tests/integration/test_pine_run_e2e.py``.

/pine/strategies/run still returns HTTP 501 at M1 (strategies land at M2
per PRD §3.2).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from openbb_core.app.model.obbject import OBBject

from openbb_pine.errors import (
    PineDataValidationError,
    PineProviderError,
    PineStrategyNotYetImplementedError,
)


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


def _mock_compiled():
    """Minimal CompiledModule-like object compile_pine returns."""
    m = MagicMock()
    m.source = "# fake compiled"
    m.sha = "deadbeef" * 8
    m.pine_version = 6
    m.compiler_version = "0.1.0"
    m.builtins_used = frozenset({"close", "plot"})
    m.security_contexts = None
    m.cache_status = "hit"
    return m


# ---------------------------------------------------------------------------
# /pine/run — provider mode
# ---------------------------------------------------------------------------


def test_run_valid_fmp_request_reaches_run_compiled():
    """Valid FMP request flows through compile_pine + run_compiled to OBBject."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        result = _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))

    assert isinstance(result, OBBject)
    assert mock_run.called
    kw = mock_run.call_args.kwargs
    assert kw["provider_or_data"] == "fmp"
    assert kw["symbol"] == "AAPL"


def test_run_returns_obbject_with_attribution_and_extra_keys():
    """OBBject carries D2 §6.1 .extra keys (surface #1 attribution path)."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
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

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp_cached", symbol="AAPL"))

    assert mock_run.call_args.kwargs["provider_or_data"] == "fmp_cached"


def test_run_default_provider_is_fmp_cached():
    """Default provider = 'fmp_cached' per PRD §16.1 recommendation."""
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run(source=_TRIVIAL_SRC))
    assert mock_run.call_args.kwargs["provider_or_data"] == "fmp_cached"


def test_run_non_fmp_provider_raises_pine_provider_error_first():
    """Non-FMP names MUST raise PineProviderError BEFORE hitting compile_pine.

    Clients see the structured FMP-only message instead of a downstream
    compile/exec error that masks the user's provider mistake.
    """
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        with pytest.raises(PineProviderError) as ei:
            _run_async(run(source=_TRIVIAL_SRC, provider="yahoo", symbol="AAPL"))
    assert not mock_run.called
    assert not mock_compile.called
    msg = str(ei.value).lower()
    assert "fmp" in msg
    assert "yahoo" in msg


def test_run_iso_dates_pass_through_to_run_compiled():
    """`start`/`end` ISO strings become tz-aware UTC datetimes for run_compiled."""
    from datetime import datetime, timezone as tz
    from openbb_pine.routers.run_router import run

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
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

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run(
            source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL",
            params={"length": 20}, timeout_s=15,
        ))
    kw = mock_run.call_args.kwargs
    assert kw["params"] == {"length": 20}
    assert kw["timeout_s"] == 15


# ---------------------------------------------------------------------------
# /pine/run_byo — BYO records mode
# ---------------------------------------------------------------------------


def _sample_records(n: int = 3) -> list[dict]:
    return [
        {"date": f"2024-01-{2+i:02d}T00:00:00Z", "open": 100.0 + i, "high": 101.0 + i,
         "low": 99.0 + i, "close": 100.5 + i, "volume": 1_000_000}
        for i in range(n)
    ]


def test_run_byo_records_materialises_to_dataframe():
    """BYO records list becomes pd.DataFrame threaded into run_compiled."""
    import pandas as pd
    from openbb_pine.routers.run_router import run_byo

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run_byo(source=_TRIVIAL_SRC, records=_sample_records(3), symbol="X"))

    passed = mock_run.call_args.kwargs["provider_or_data"]
    assert isinstance(passed, pd.DataFrame)
    assert list(passed.columns) == ["open", "high", "low", "close", "volume"]
    assert len(passed) == 3
    assert passed.index.tz is not None


def test_run_byo_default_symbol_is_byo():
    """Symbol defaults to 'BYO' when not specified."""
    from openbb_pine.routers.run_router import run_byo

    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run_byo(source=_TRIVIAL_SRC, records=_sample_records(3)))
    assert mock_run.call_args.kwargs["symbol"] == "BYO"


def test_run_byo_empty_records_raises_pine_data_validation():
    """Empty records list is a schema defect handled by _byo_records_to_dataframe."""
    from openbb_pine.routers.run_router import run_byo

    with pytest.raises(PineDataValidationError) as ei:
        _run_async(run_byo(source=_TRIVIAL_SRC, records=[]))
    assert "empty" in str(ei.value).lower()


def test_run_byo_missing_date_column_raises():
    """Records without a date column are rejected."""
    from openbb_pine.routers.run_router import run_byo

    with pytest.raises(PineDataValidationError) as ei:
        _run_async(run_byo(source=_TRIVIAL_SRC, records=[{"close": 1.0}]))
    assert "date" in str(ei.value).lower()


def test_run_byo_tz_localisation_works():
    """Non-UTC tz records get localised then converted to UTC."""
    import pandas as pd
    from openbb_pine.routers.run_router import run_byo

    records = [
        {"date": "2024-01-02T09:30:00", "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.5, "volume": 1_000_000},
    ]
    with patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run_byo(source=_TRIVIAL_SRC, records=records, tz="America/New_York"))

    df = mock_run.call_args.kwargs["provider_or_data"]
    assert isinstance(df, pd.DataFrame)
    # After tz-localise + convert to UTC, 09:30 New_York (EST) = 14:30 UTC
    assert df.index[0].tz is not None


def test_run_byo_does_not_call_resolve_provider():
    """BYO mode skips provider validation entirely."""
    from openbb_pine.routers.run_router import run_byo

    with patch("openbb_pine.routers.run_router.resolve_provider") as mock_rp, \
         patch("openbb_pine.routers.run_router.run_compiled") as mock_run, \
         patch("openbb_pine.routers.run_router.compile_pine") as mock_compile:
        mock_compile.return_value = _mock_compiled()
        mock_run.return_value = _fake_obbject()
        _run_async(run_byo(source=_TRIVIAL_SRC, records=_sample_records(3)))

    assert not mock_rp.called


# ---------------------------------------------------------------------------
# /pine/strategies/run — 501 always at M1 (unchanged)
# ---------------------------------------------------------------------------


def test_strategies_run_raises_501_always_m1():
    from openbb_pine.routers.strategies_router import run

    with pytest.raises(PineStrategyNotYetImplementedError) as ei:
        _run_async(run(source=_TRIVIAL_SRC, provider="fmp", symbol="AAPL"))
    assert "M2" in str(ei.value)
    assert "0e9.5.6" in str(ei.value)


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


def test_run_router_registers_both_run_and_run_byo():
    from openbb_pine.routers.run_router import router

    paths = {r.path for r in router.api_router.routes}
    assert "/run" in paths
    assert "/run_byo" in paths


def test_strategies_router_registers_run_route_under_strategies():
    from openbb_pine.routers.strategies_router import router

    paths = {r.path for r in router.api_router.routes}
    assert "/strategies/run" in paths
