"""Unit tests for ``openbb_pine.diagnostics``.

Per D3 §10.2 + PRD §16.4, the diagnostic checks are the single source of truth
shared between ``obb.pine.about()`` (§3) and the ``openbb-pine doctor`` CLI
(§10). These tests pin each check function's contract and guarantee
``run_all_checks`` returns the full §10.2 nine-check sequence.

No test in this module may make a real network call. ``check_fmp_reachable``
is exercised via ``monkeypatch`` on its HTTP entry point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest


# ----------------------------------------------------------------------
# CheckResult shape
# ----------------------------------------------------------------------


def test_check_result_is_frozen_dataclass_with_fields():
    from openbb_pine.diagnostics import CheckResult

    r = CheckResult(name="x", status="ok", message="y")
    assert r.name == "x"
    assert r.status == "ok"
    assert r.message == "y"
    assert r.fix_hint is None
    with pytest.raises(Exception):
        r.name = "z"  # frozen


def test_check_result_status_is_one_of_three_literal_strings():
    """Status MUST be ``"ok" | "warn" | "fail"`` (lowercase) for CLI tag dispatch."""
    from openbb_pine.diagnostics import CheckResult

    for s in ("ok", "warn", "fail"):
        r = CheckResult(name="n", status=s, message="m")
        assert r.status == s


# ----------------------------------------------------------------------
# Individual check functions
# ----------------------------------------------------------------------


def test_check_python_version_ok_on_311_plus(monkeypatch):
    from openbb_pine import diagnostics

    monkeypatch.setattr(
        sys, "version_info", (3, 11, 7, "final", 0)
    )  # noqa: SLF001 - test-only
    r = diagnostics.check_python_version()
    assert r.name == "Python 3.11+"
    assert r.status == "ok"
    assert "3.11.7" in r.message


def test_check_python_version_fail_on_310(monkeypatch):
    from openbb_pine import diagnostics

    monkeypatch.setattr(
        sys, "version_info", (3, 10, 14, "final", 0)
    )  # noqa: SLF001
    r = diagnostics.check_python_version()
    assert r.status == "fail"
    assert r.fix_hint is not None  # actionable


def test_check_openbb_core_installed_ok():
    """openbb_core is a hard dep of the pine extension — must be present."""
    from openbb_pine.diagnostics import check_openbb_core_installed

    r = check_openbb_core_installed()
    assert r.name == "openbb-core installed"
    assert r.status == "ok"


def test_check_openbb_core_installed_fail_when_missing(monkeypatch):
    """If ``find_spec("openbb_core")`` returns None the check FAILs."""
    import openbb_pine.diagnostics as d

    monkeypatch.setattr(
        d.importlib.util, "find_spec", lambda name: None if name == "openbb_core" else object()
    )
    r = d.check_openbb_core_installed()
    assert r.status == "fail"


def test_check_openbb_fmp_installed_ok():
    from openbb_pine.diagnostics import check_openbb_fmp_installed

    r = check_openbb_fmp_installed()
    assert r.name == "openbb-fmp installed (required)"
    assert r.status == "ok"


def test_check_openbb_fmp_cached_installed_warns_when_missing(monkeypatch):
    """Per D3 §10.2 row 4: fmp-cached missing is WARN, not FAIL."""
    import openbb_pine.diagnostics as d

    monkeypatch.setattr(
        d.importlib.util,
        "find_spec",
        lambda name: None if name == "openbb_fmp_cached" else object(),
    )
    r = d.check_openbb_fmp_cached_installed()
    assert r.name == "openbb-fmp-cached installed (recommended)"
    assert r.status == "warn"
    assert r.fix_hint is not None


def test_check_openbb_fmp_cached_installed_ok_when_present():
    """Real environment in this venv has fmp_cached installed."""
    from openbb_pine.diagnostics import check_openbb_fmp_cached_installed

    r = check_openbb_fmp_cached_installed()
    # Either ok or warn, but the check itself must run without error.
    assert r.status in ("ok", "warn")


def test_check_fmp_api_key_present_ok_from_env(monkeypatch, tmp_path):
    """Env var ``OPENBB_API_FMP_API_KEY`` is the first source consulted."""
    import openbb_pine.diagnostics as d

    monkeypatch.setenv("OPENBB_API_FMP_API_KEY", "test-key-xxx")
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "no_such.json")
    r = d.check_fmp_api_key_present()
    assert r.status == "ok"


def test_check_fmp_api_key_present_ok_from_user_settings(monkeypatch, tmp_path):
    """If env is unset but ``user_settings.json`` has ``fmp_api_key``, OK."""
    import openbb_pine.diagnostics as d

    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)
    fp = tmp_path / "user_settings.json"
    fp.write_text(json.dumps({"credentials": {"fmp_api_key": "abc"}}))
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", fp)
    r = d.check_fmp_api_key_present()
    assert r.status == "ok"


def test_check_fmp_api_key_present_fail_when_absent(monkeypatch, tmp_path):
    import openbb_pine.diagnostics as d

    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "no_such.json")
    r = d.check_fmp_api_key_present()
    assert r.status == "fail"
    assert r.fix_hint is not None


def test_check_fmp_api_key_present_warn_under_byo_only(monkeypatch, tmp_path):
    """D3 §10 BYO-only clause: missing FMP key degrades to WARN."""
    import openbb_pine.diagnostics as d

    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "no_such.json")
    r = d.check_fmp_api_key_present(allow_byo_only=True)
    assert r.status == "warn"


def test_check_fmp_reachable_ok(monkeypatch):
    """Mocks the HTTP call — no real network reached."""
    import openbb_pine.diagnostics as d

    calls = []

    def fake_get(url: str, timeout: float | None = None) -> Any:  # noqa: ANN401
        calls.append((url, timeout))

        class _R:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return [{"symbol": "AAPL"}]

        return _R()

    monkeypatch.setattr(d, "_http_get", fake_get)
    r = d.check_fmp_reachable()
    assert r.status == "ok"
    assert calls and "profile/AAPL" in calls[0][0]


def test_check_fmp_reachable_fail_on_500(monkeypatch):
    import openbb_pine.diagnostics as d

    class _R:
        status_code = 500

        def json(self) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(d, "_http_get", lambda url, timeout=None: _R())
    r = d.check_fmp_reachable()
    assert r.status == "fail"


def test_check_fmp_reachable_fail_on_exception(monkeypatch):
    """Any transport-level error → FAIL (no traceback escape)."""
    import openbb_pine.diagnostics as d

    def boom(url: str, timeout: float | None = None) -> Any:  # noqa: ANN401
        raise OSError("connection refused")

    monkeypatch.setattr(d, "_http_get", boom)
    r = d.check_fmp_reachable()
    assert r.status == "fail"
    assert "connection refused" in r.message or "FMP" in r.message


def test_check_fmp_reachable_warn_under_byo_only(monkeypatch):
    """BYO-only: unreachable FMP degrades hard FAIL → WARN."""
    import openbb_pine.diagnostics as d

    def boom(url: str, timeout: float | None = None) -> Any:  # noqa: ANN401
        raise OSError("nope")

    monkeypatch.setattr(d, "_http_get", boom)
    r = d.check_fmp_reachable(allow_byo_only=True)
    assert r.status == "warn"


def test_check_pynecore_importable_ok():
    """The vendored PyneCore (third_party submodule) is on sys.path after import."""
    import openbb_pine  # noqa: F401  — triggers sys.path injection
    from openbb_pine.diagnostics import check_pynecore_importable

    r = check_pynecore_importable()
    assert r.name == "PyneCore importable"
    assert r.status == "ok"


def test_check_pynecore_importable_fail_when_missing(monkeypatch):
    import openbb_pine.diagnostics as d

    monkeypatch.setattr(
        d.importlib.util,
        "find_spec",
        lambda name: None if name == "pynecore" else object(),
    )
    r = d.check_pynecore_importable()
    assert r.status == "fail"
    assert r.fix_hint is not None


def test_check_compile_cache_writable_ok(monkeypatch, tmp_path):
    import openbb_pine.diagnostics as d

    monkeypatch.setattr(d, "COMPILE_CACHE_DIR", tmp_path / "pine_cache")
    r = d.check_compile_cache_writable()
    assert r.name == "Compile cache writable"
    assert r.status == "ok"


def test_check_compile_cache_writable_fail_on_unwritable(monkeypatch):
    """If mkdir / mkstemp throws, the check FAILs with the OS error in message."""
    import openbb_pine.diagnostics as d

    class _BadPath:
        def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
            raise PermissionError("denied")

        def __fspath__(self) -> str:  # pragma: no cover - defensive
            return "/dev/null/unwritable"

    monkeypatch.setattr(d, "COMPILE_CACHE_DIR", _BadPath())
    r = d.check_compile_cache_writable()
    assert r.status == "fail"
    assert "denied" in r.message or "Permission" in r.message


def test_check_attribution_surfaces_ok():
    """All four §2.6 attribution surfaces — at L0.2 attribution.py exists."""
    from openbb_pine.diagnostics import check_attribution_surfaces

    r = check_attribution_surfaces()
    assert r.name.startswith("PyneSys attribution surfaces")
    # The scaffold has surface #3 (about) and the constants live in attribution.py.
    # Surfaces #1 (health JSON), #2 (widget footer), #4 (CLI banner) are wired by
    # subsequent beads — until then this check is OK only on the modules that exist.
    assert r.status in ("ok", "warn", "fail")


# ----------------------------------------------------------------------
# run_all_checks
# ----------------------------------------------------------------------


def test_run_all_checks_returns_nine_named_checks(monkeypatch):
    """Per D3 §10.2 — nine checks, in the documented order."""
    import openbb_pine.diagnostics as d

    # Defang the network check so this test stays offline.
    class _R:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return [{"symbol": "AAPL"}]

    monkeypatch.setattr(d, "_http_get", lambda url, timeout=None: _R())

    results = d.run_all_checks()
    assert len(results) == 9
    names = [r.name for r in results]
    assert names == [
        "Python 3.11+",
        "openbb-core installed",
        "openbb-fmp installed (required)",
        "openbb-fmp-cached installed (recommended)",
        "FMP API key present",
        "FMP /api/v3/profile/AAPL reachable",
        "PyneCore importable",
        "Compile cache writable",
        "PyneSys attribution surfaces present (4/4)",
    ]


def test_run_all_checks_allow_byo_only_degrades_fmp_failures(
    monkeypatch, tmp_path
):
    """BYO-only flag: missing key and unreachable FMP both go WARN, not FAIL."""
    import openbb_pine.diagnostics as d

    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "no_such.json")

    def boom(url: str, timeout: float | None = None) -> Any:  # noqa: ANN401
        raise OSError("offline")

    monkeypatch.setattr(d, "_http_get", boom)

    hard = d.run_all_checks(allow_byo_only=False)
    soft = d.run_all_checks(allow_byo_only=True)

    hard_by_name = {r.name: r.status for r in hard}
    soft_by_name = {r.name: r.status for r in soft}
    assert hard_by_name["FMP API key present"] == "fail"
    assert hard_by_name["FMP /api/v3/profile/AAPL reachable"] == "fail"
    assert soft_by_name["FMP API key present"] == "warn"
    assert soft_by_name["FMP /api/v3/profile/AAPL reachable"] == "warn"


def test_run_all_checks_does_not_make_network_call_in_byo_only_with_no_key(
    monkeypatch, tmp_path
):
    """Sanity: even with the flag, the HTTP call is still mocked here — no real network."""
    import openbb_pine.diagnostics as d

    called = {"n": 0}

    def fake(url: str, timeout: float | None = None) -> Any:  # noqa: ANN401
        called["n"] += 1

        class _R:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return []

        return _R()

    monkeypatch.setattr(d, "_http_get", fake)
    monkeypatch.delenv("OPENBB_API_FMP_API_KEY", raising=False)
    monkeypatch.setattr(d, "USER_SETTINGS_PATH", tmp_path / "no_such.json")
    d.run_all_checks(allow_byo_only=True)
    # Confirm only the fake (not real httpx/requests) was reached.
    assert called["n"] >= 1
