"""Integration test for #83 obb.techtrade.tune -- end-to-end against in-tree backtest + real tuneta.

Runs a single-segment tune against the **real** openbb-backtest validate router AND
real tuneta on a small ETF-pooled universe (kept tiny for cost-bounded CI). Skips
cleanly when ANY of (tuneta, openbb-backtest, fmp_cached) is absent so the default
offline unit sweep is unaffected.

The integration window is intentionally small (1y, top-3 universe) so a single
tuneta fit + a single validate run completes in a few minutes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest


_TUNETA_AVAILABLE = importlib.util.find_spec("tuneta") is not None
_BACKTEST_AVAILABLE = importlib.util.find_spec("openbb_backtest") is not None


def _fmp_cached_available() -> bool:
    """Best-effort probe (mirrors test_validate.py)."""
    if importlib.util.find_spec("openbb_fmp_cached") is None:
        return False
    settings = Path.home() / ".openbb_platform" / "user_settings.json"
    if not settings.exists():
        return False
    try:
        cred = json.loads(settings.read_text(encoding="utf-8")).get("credentials", {})
        return bool(cred.get("fmp_cached_api_key") or cred.get("fmp_api_key"))
    except Exception:  # noqa: BLE001 - any read failure -> skip
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _TUNETA_AVAILABLE,
        reason="tuneta not installed; install with: pip install 'openbb-techtrade[tuneta]'",
    ),
    pytest.mark.skipif(
        not _BACKTEST_AVAILABLE,
        reason="openbb-backtest not installed; install with: pip install 'openbb-techtrade[validation]'",
    ),
    pytest.mark.skipif(
        not _fmp_cached_available(),
        reason="fmp_cached provider / API key not configured for live integration",
    ),
]


def test_tune_returns_coherent_report_against_real_validate(tmp_path, monkeypatch):
    """End-to-end: tune one segment, get back a TuningReport with a real verdict."""
    # Pin the persistence path at tmp_path so the integration run doesn't pollute the
    # user's real ~/.openbb_platform/techtrade_tuned.json.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    # Use a short 1y window + small universe to keep wall-clock bounded.
    from openbb_techtrade.tuning.tune_router import tune

    obb = asyncio.run(tune(
        segment="Information Technology",
        as_of=date(2024, 12, 13),  # deterministic Friday in late 2024
        horizon_years=1,            # short
        trials=20,                  # small budget for CI
        early_stop=5,
    ))
    report = obb.results

    # Shape assertions:
    assert report.segment == "Information Technology"
    assert report.as_of == date(2024, 12, 13)
    assert report.candidate is not None
    assert report.validation is not None
    assert report.tuneta_version  # non-empty
    assert report.fit_seconds > 0
    # The verdict must be one of the locked three.
    verdict = getattr(report.validation, "verdict", None)
    assert verdict in {"robust", "fragile", "overfit"}
    # If robust AND not a no-op tune -> file should now exist.
    if report.persisted:
        assert (tmp_path / "techtrade_tuned.json").exists()
        assert "verdict=robust" in report.reason
    else:
        # File may or may not exist depending on prior tunes in tmp_path
        # (which is fresh per-test, so it WON'T exist). Reason must explain why.
        assert any(
            marker in report.reason
            for marker in ("verdict=fragile", "verdict=overfit", "no change from defaults")
        )
