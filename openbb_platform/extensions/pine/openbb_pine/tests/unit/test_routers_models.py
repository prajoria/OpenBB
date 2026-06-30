"""Tests for :mod:`openbb_pine.routers._models` (P1 — bead 0e9.5.52).

Pin the Pydantic models referenced by every P1 sub-router. The models are
the wire contract: response shapes are advertised in the OpenAPI schema,
and request shapes drive client-side request validation. A drift here
silently changes the surface for every consumer, so every model gets a
constructor test plus a "validator fires when X" test for each model that
has a ``model_validator``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openbb_pine.attribution import POWERED_BY_SHORT
from openbb_pine.routers._models import (
    BuiltinsCoverage,
    BundledIndicatorEntry,
    PineByoData,
    PineCompileRequest,
    PineCompileResponse,
    PineHealth,
    PineRunRequest,
    PineStrategiesRunRequest,
)


# ---------------------------------------------------------------------------
# Response models — constructor sanity
# ---------------------------------------------------------------------------


def test_pine_compile_response_round_trip():
    resp = PineCompileResponse(
        python_source="# stub",
        sha="deadbeef",
        pine_version=6,
        compiler_version="0.1.0",
        builtins_used=["ta.sma"],
        warnings=[],
    )
    dumped = resp.model_dump()
    assert dumped["pine_version"] == 6
    assert dumped["builtins_used"] == ["ta.sma"]
    # Defaults: empty list when omitted.
    resp2 = PineCompileResponse(
        python_source="x",
        sha="abc",
        pine_version=5,
        compiler_version="0.1.0",
    )
    assert resp2.builtins_used == []
    assert resp2.warnings == []


def test_pine_compile_response_rejects_out_of_range_version():
    with pytest.raises(ValidationError):
        PineCompileResponse(
            python_source="x",
            sha="abc",
            pine_version=4,  # only 5 or 6 allowed
            compiler_version="0.1.0",
        )


def test_bundled_indicator_entry_constructs():
    entry = BundledIndicatorEntry(
        name="bollinger_bands",
        pine_source_path="bundled/bb.pine",
        description="Bollinger Bands",
        category="indicator",
        pine_version=6,
    )
    assert entry.name == "bollinger_bands"
    assert entry.pine_version == 6


def test_builtins_coverage_phase_0_baseline_constructs():
    cov = BuiltinsCoverage(
        pine_versions_supported=[],
        builtins_implemented_count=0,
        builtins_implemented=[],
        features_implemented=[],
        pine_versions_known=[5, 6],
    )
    assert cov.builtins_implemented_count == 0
    assert cov.pine_versions_known == [5, 6]


# ---------------------------------------------------------------------------
# PineHealth — defaults, powered_by binding, status enum
# ---------------------------------------------------------------------------


def test_pine_health_default_construction_yields_short_attribution():
    """Surface #3 default — `PineHealth()` MUST default to POWERED_BY_SHORT.

    The 4-of-4 attribution test (`test_attribution_surfaces`) constructs
    PineHealth() with no args; if the default drifts the attribution
    surface silently regresses.
    """
    h = PineHealth()
    assert h.powered_by == POWERED_BY_SHORT


def test_pine_health_explicit_powered_by_override_round_trips():
    h = PineHealth(powered_by="custom string for testing")
    assert h.powered_by == "custom string for testing"


def test_pine_health_status_enum_accepts_three_values():
    for s in ("ok", "degraded", "unhealthy"):
        h = PineHealth(status=s)
        assert h.status == s


def test_pine_health_status_enum_rejects_other_values():
    with pytest.raises(ValidationError):
        PineHealth(status="ill")  # not in the literal set


def test_pine_health_forbids_extra_fields():
    """`extra="forbid"` — a typo'd kwarg fails at construction time."""
    with pytest.raises(ValidationError):
        PineHealth(power_by="oops")  # typo: missing 'ed'


# ---------------------------------------------------------------------------
# Request models — validators fire
# ---------------------------------------------------------------------------


def test_pine_run_request_provider_mode_requires_symbol():
    with pytest.raises(ValidationError):
        PineRunRequest(source="x = 1", provider="fmp")  # no symbol


def test_pine_run_request_provider_mode_accepts_symbol():
    r = PineRunRequest(source="x = 1", provider="fmp", symbol="AAPL")
    assert r.provider == "fmp"
    assert r.symbol == "AAPL"


def test_pine_run_request_byo_mode_does_not_require_symbol():
    data = PineByoData(format="records", records=[{"close": 1.0}])
    r = PineRunRequest(source="x = 1", data=data)
    assert r.data is not None
    assert r.symbol is None


def test_pine_run_request_requires_provider_or_data():
    """At least one source MUST be set."""
    with pytest.raises(ValidationError):
        PineRunRequest(source="x = 1")


def test_pine_run_request_rejects_non_fmp_provider_at_pydantic_layer():
    """``provider`` is Literal['fmp','fmp_cached']."""
    with pytest.raises(ValidationError):
        PineRunRequest(source="x = 1", provider="yahoo", symbol="AAPL")


def test_pine_run_request_source_must_be_nonempty():
    with pytest.raises(ValidationError):
        PineRunRequest(source="", provider="fmp", symbol="AAPL")


def test_pine_run_request_timeout_must_be_positive():
    with pytest.raises(ValidationError):
        PineRunRequest(
            source="x", provider="fmp", symbol="AAPL", timeout_s=0
        )


def test_pine_byo_data_records_requires_payload():
    with pytest.raises(ValidationError):
        PineByoData(format="records")


def test_pine_byo_data_parquet_url_requires_url():
    with pytest.raises(ValidationError):
        PineByoData(format="parquet_url")


def test_pine_byo_data_arrow_ipc_requires_b64():
    with pytest.raises(ValidationError):
        PineByoData(format="arrow_ipc_base64")


def test_pine_byo_data_records_accepts_records():
    bd = PineByoData(format="records", records=[{"close": 100.0}])
    assert bd.records == [{"close": 100.0}]
    assert bd.tz == "UTC"


def test_pine_compile_request_defaults_target_version_to_6():
    cr = PineCompileRequest(source="x")
    assert cr.target_version == 6


def test_pine_compile_request_rejects_v4():
    with pytest.raises(ValidationError):
        PineCompileRequest(source="x", target_version=4)


def test_pine_strategies_run_request_inherits_run_request_validation():
    """`PineStrategiesRunRequest` extends `PineRunRequest` — same validator."""
    with pytest.raises(ValidationError):
        PineStrategiesRunRequest(source="x")  # no provider or data
    # Happy path
    r = PineStrategiesRunRequest(source="x", provider="fmp", symbol="AAPL")
    assert r.strategy_params == {}
    r2 = PineStrategiesRunRequest(
        source="x", provider="fmp", symbol="AAPL",
        strategy_params={"initial_capital": 100000},
    )
    assert r2.strategy_params["initial_capital"] == 100000
