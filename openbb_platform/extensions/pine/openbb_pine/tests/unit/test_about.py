"""Expanded tests for ``openbb_pine.about`` (P5 — bead 0e9.5.56).

The L0.2 scaffold returned hardcoded placeholder values. P5 wires every field
to its real source (PyneCore version from the L0.3 license manifest, builtins
count from ``_coverage_manifest``, FMP detection from ``user_settings.json``
or env, etc.). These tests pin the new contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def test_about_extension_version_is_real_metadata():
    """Pulled via ``importlib.metadata.version("openbb-extension-pine")``."""
    from openbb_pine.about import about

    r = about().results
    # 0.1.0 is the pyproject pin; any digit-dot-digit is fine.
    assert isinstance(r.extension_version, str)
    assert r.extension_version  # non-empty


def test_about_pine_version_supported_mentions_v6_and_v5_migration():
    from openbb_pine.about import about

    r = about().results
    assert "6" in r.pine_version_supported
    assert "v5" in r.pine_version_supported.lower()


def test_about_runtime_string_uses_pynecore_pinned_version(monkeypatch, tmp_path):
    """Runtime must source from ``third_party/pynecore.license_manifest.json``."""
    import openbb_pine.about as about_mod

    fake_manifest = tmp_path / "manifest.json"
    fake_manifest.write_text(
        json.dumps({"schema_version": 1, "pinned_version": "9.9.9"})
    )
    monkeypatch.setattr(about_mod, "LICENSE_MANIFEST_PATH", fake_manifest)
    r = about_mod.about().results
    assert "PyneCore" in r.runtime
    assert "9.9.9" in r.runtime
    assert "Apache-2.0" in r.runtime


def test_about_runtime_falls_back_to_default_when_manifest_missing(monkeypatch, tmp_path):
    import openbb_pine.about as about_mod

    monkeypatch.setattr(about_mod, "LICENSE_MANIFEST_PATH", tmp_path / "nope.json")
    r = about_mod.about().results
    assert "PyneCore" in r.runtime
    assert "6.5.2" in r.runtime  # documented fallback


def test_about_powered_by_is_attribution_full_constant():
    """Surface #3 of the four §2.6 attribution surfaces."""
    from openbb_pine.about import about
    from openbb_pine.attribution import POWERED_BY_FULL

    r = about().results
    assert r.powered_by == POWERED_BY_FULL


def test_about_compiler_status_mentions_phase_1_scaffold():
    from openbb_pine.about import about

    r = about().results
    s = r.compiler_status.lower()
    assert "scaffold" in s
    assert "phase 1" in s or "compiler not yet" in s


def test_about_builtins_implemented_reads_coverage_manifest(monkeypatch):
    """The count is len(BUILTINS_IMPLEMENTED) — Phase 0 = 0, future bumps += 1."""
    from openbb_pine import _coverage_manifest
    from openbb_pine.about import about

    monkeypatch.setattr(
        _coverage_manifest,
        "BUILTINS_IMPLEMENTED",
        frozenset({"ta.sma", "math.abs"}),
    )
    r = about().results
    assert r.builtins_implemented == 2


def test_about_builtins_total_is_357_placeholder():
    from openbb_pine.about import about

    r = about().results
    assert r.builtins_total == 357


def test_about_providers_supported_is_locked_to_fmp_pair():
    from openbb_pine.about import about

    r = about().results
    assert r.providers_supported == ["fmp", "fmp_cached"]


def test_about_fmp_key_present_true_from_env(monkeypatch, tmp_path):
    import pyne_compiler.errors.diagnostics as d
    from openbb_pine.about import about

    monkeypatch.setenv("OPENBB_API_FMP_API_KEY", "envkey")
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "absent.json")
    r = about().results
    assert r.fmp_key_present is True


def test_about_fmp_key_present_false_when_neither_source_has_it(monkeypatch, tmp_path):
    import pyne_compiler.errors.diagnostics as d
    from openbb_pine.about import about

    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "absent.json")
    r = about().results
    assert r.fmp_key_present is False


def test_about_fmp_cached_installed_uses_find_spec():
    """``importlib.util.find_spec("openbb_fmp_cached")`` truthy ⇒ True."""
    import importlib.util

    from openbb_pine.about import about

    r = about().results
    assert r.fmp_cached_installed is (
        importlib.util.find_spec("openbb_fmp_cached") is not None
    )


def test_about_compile_cache_dir_is_home_pine_cache():
    from openbb_pine.about import about

    r = about().results
    p = Path(r.compile_cache_dir)
    assert p.name == "pine_cache"
    assert p.parent.name == ".openbb"


def test_about_doctor_ok_true_when_all_checks_pass(monkeypatch):
    """When every shared check returns OK/WARN, ``doctor_ok`` is True."""
    import openbb_pine.about as about_mod
    from pyne_compiler.errors.diagnostics import CheckResult

    monkeypatch.setattr(
        about_mod,
        "run_all_checks",
        lambda allow_byo_only=False: [
            CheckResult(name="x", status="ok", message="m"),
            CheckResult(name="y", status="warn", message="m"),
        ],
    )
    r = about_mod.about().results
    assert r.doctor_ok is True
    assert r.doctor_issues == []


def test_about_doctor_issues_lists_failing_check_names(monkeypatch):
    import openbb_pine.about as about_mod
    from pyne_compiler.errors.diagnostics import CheckResult

    monkeypatch.setattr(
        about_mod,
        "run_all_checks",
        lambda allow_byo_only=False: [
            CheckResult(name="ok-check", status="ok", message="."),
            CheckResult(name="bad-check", status="fail", message="oops"),
            CheckResult(name="other-bad", status="fail", message="oof"),
        ],
    )
    r = about_mod.about().results
    assert r.doctor_ok is False
    assert "bad-check" in r.doctor_issues
    assert "other-bad" in r.doctor_issues


def test_about_about_call_does_not_raise_in_real_environment(monkeypatch):
    """End-to-end smoke: about() runs against the real environment without exceptions.

    HTTP probe is stubbed so this test stays offline and CI-safe.
    """
    import pyne_compiler.errors.diagnostics as d
    from openbb_pine.about import about

    class _R:
        status_code = 200

        def json(self) -> Any:  # noqa: ANN401
            return [{"symbol": "AAPL"}]

    monkeypatch.setattr(d, "_http_get", lambda url, timeout=None: _R())
    obj = about()
    assert obj.results.extension_name == "pine"
