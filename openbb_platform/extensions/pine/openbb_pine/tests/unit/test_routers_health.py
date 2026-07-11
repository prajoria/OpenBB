"""Tests for :mod:`openbb_pine.routers.health_router` (P1 — bead 0e9.5.52).

Pin the ``GET /pine/health`` command's contract:

* Returns ``OBBject[PineHealth]`` — typed model per D3 §5.
* ``powered_by`` is the literal :data:`POWERED_BY_SHORT` (surface #3).
* ``status`` enum follows the doctor-result roll-up rules (D3 §4.6 +
  module helper :func:`_derive_status`).
* ``doctor_ok`` / ``doctor_issues`` thread through from
  :func:`run_all_checks` so the JSON response mirrors what the CLI sees.

HTTP probes stubbed via ``diagnostics._http_get`` so the tests stay
offline / CI-safe (same pattern as :mod:`tests.unit.test_about`).
"""

from __future__ import annotations

from typing import Any

import pytest

from openbb_core.app.model.obbject import OBBject

from openbb_pine.attribution import POWERED_BY_SHORT
from pyne_compiler.errors.diagnostics import CheckResult


@pytest.fixture
def healthy_http(monkeypatch):
    """Stub the FMP reachability probe to return HTTP 200 JSON."""
    import pyne_compiler.errors.diagnostics as d

    class _R:
        status_code = 200

        def json(self) -> Any:
            return [{"symbol": "AAPL"}]

    monkeypatch.setattr(d, "_http_get", lambda url, timeout=None: _R())


def test_health_returns_obbject_wrapping_pinehealth(healthy_http):
    from openbb_pine.routers.health_router import PineHealth, health

    obj = health()
    assert isinstance(obj, OBBject)
    assert isinstance(obj.results, PineHealth)


def test_health_powered_by_is_short_literal(healthy_http):
    """Surface #3 wire contract — MUST equal POWERED_BY_SHORT."""
    from openbb_pine.routers.health_router import health

    obj = health()
    assert obj.results.powered_by == POWERED_BY_SHORT


def test_health_status_ok_when_no_warn_or_fail(monkeypatch):
    import openbb_pine.routers.health_router as hr

    monkeypatch.setattr(
        hr,
        "run_all_checks",
        lambda allow_byo_only=False: [
            CheckResult(name="a", status="ok", message="."),
            CheckResult(name="b", status="ok", message="."),
        ],
    )
    obj = hr.health()
    assert obj.results.status == "ok"
    assert obj.results.doctor_ok is True
    assert obj.results.doctor_issues == []


def test_health_status_degraded_on_warn(monkeypatch):
    import openbb_pine.routers.health_router as hr

    monkeypatch.setattr(
        hr,
        "run_all_checks",
        lambda allow_byo_only=False: [
            CheckResult(name="a", status="ok", message="."),
            CheckResult(name="b", status="warn", message="."),
        ],
    )
    obj = hr.health()
    assert obj.results.status == "degraded"
    # WARN does not fail the doctor — same convention as the CLI.
    assert obj.results.doctor_ok is True
    assert obj.results.doctor_issues == []


def test_health_status_unhealthy_on_fail(monkeypatch):
    import openbb_pine.routers.health_router as hr

    monkeypatch.setattr(
        hr,
        "run_all_checks",
        lambda allow_byo_only=False: [
            CheckResult(name="good", status="ok", message="."),
            CheckResult(name="broken", status="fail", message="oops"),
            CheckResult(name="other-broken", status="fail", message="oof"),
        ],
    )
    obj = hr.health()
    assert obj.results.status == "unhealthy"
    assert obj.results.doctor_ok is False
    assert obj.results.doctor_issues == ["broken", "other-broken"]


def test_health_extension_version_is_real_metadata(healthy_http):
    """Pulled via ``importlib.metadata.version("openbb-extension-pine")``."""
    from openbb_pine.routers.health_router import health

    obj = health()
    assert isinstance(obj.results.extension_version, str)
    assert obj.results.extension_version


def test_health_runtime_mentions_pynecore(healthy_http):
    from openbb_pine.routers.health_router import health

    obj = health()
    assert "PyneCore" in obj.results.runtime
    assert "Apache-2.0" in obj.results.runtime


def test_health_pine_version_supported_mentions_v6(healthy_http):
    from openbb_pine.routers.health_router import health

    obj = health()
    assert "6" in obj.results.pine_version_supported


def test_health_compiler_status_indicates_phase_1_scaffold(healthy_http):
    from openbb_pine.routers.health_router import health

    obj = health()
    s = obj.results.compiler_status.lower()
    assert "scaffold" in s or "phase 1" in s


def test_health_fmp_cached_installed_reflects_find_spec(healthy_http):
    import importlib.util

    from openbb_pine.routers.health_router import health

    obj = health()
    assert obj.results.fmp_cached_installed is (
        importlib.util.find_spec("openbb_fmp_cached") is not None
    )


def test_health_fmp_key_present_true_when_env_set(monkeypatch, tmp_path):
    """When ``OPENBB_API_FMP_API_KEY`` is set, the field is True."""
    import pyne_compiler.errors.diagnostics as d

    class _R:
        status_code = 200

        def json(self):
            return [{"symbol": "AAPL"}]

    monkeypatch.setattr(d, "_http_get", lambda url, timeout=None: _R())
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "absent.json")
    monkeypatch.setenv("OPENBB_API_FMP_API_KEY", "envkey")

    from openbb_pine.routers.health_router import health

    obj = health()
    assert obj.results.fmp_key_present is True


def test_health_fmp_key_present_false_when_no_source_has_it(monkeypatch, tmp_path):
    import pyne_compiler.errors.diagnostics as d

    class _R:
        status_code = 200

        def json(self):
            return [{"symbol": "AAPL"}]

    monkeypatch.setattr(d, "_http_get", lambda url, timeout=None: _R())
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "absent.json")
    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)

    from openbb_pine.routers.health_router import health

    obj = health()
    assert obj.results.fmp_key_present is False
