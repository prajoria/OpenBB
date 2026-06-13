"""Unit tests for the router foundation helpers (component 09.1).

Covers the shared substrate every ``obb.backtest.*`` sub-router relies on:

- :func:`resolve_engine` — turns ``engine="auto"|"vector"|"event"`` (plus the
  canonical ``vectorized``) into a concrete engine name per the auto policy, and
  raises :class:`EngineSelectionError` for anything else.
- :func:`sanitize_result` — the privacy boundary: outward results carry
  normalized returns/metrics only; raw ``positions`` (and any lot detail) are
  stripped before a result leaves the router (fork privacy rule).
- :func:`resolve_provider` / :func:`required_credentials` — credential plumbing
  that only ever deals in provider/credential *names*, never plaintext secrets.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

# ---- resolve_engine ------------------------------------------------------


def test_resolve_engine_explicit_vectorized_passes_through():
    from openbb_backtest.router_helpers import resolve_engine

    assert resolve_engine("vectorized") == "vectorized"
    assert resolve_engine("vector") == "vectorized"  # ergonomic alias


def test_resolve_engine_explicit_event_passes_through():
    from openbb_backtest.router_helpers import resolve_engine

    assert resolve_engine("event") == "event"


def test_resolve_engine_auto_defaults_to_vectorized():
    from openbb_backtest.router_helpers import resolve_engine

    # The auto policy prefers the vectorized engine for the common path.
    assert resolve_engine("auto") == "vectorized"


def test_resolve_engine_auto_picks_event_for_path_dependent():
    from openbb_backtest.router_helpers import resolve_engine

    # Path-dependent / Pipeline strategies route to the event-driven engine.
    assert resolve_engine("auto", path_dependent=True) == "event"


def test_resolve_engine_is_case_insensitive():
    from openbb_backtest.router_helpers import resolve_engine

    assert resolve_engine("EVENT") == "event"
    assert resolve_engine("Auto") == "vectorized"


def test_resolve_engine_unknown_raises_engine_selection_error():
    from openbb_backtest.errors import EngineSelectionError
    from openbb_backtest.router_helpers import resolve_engine

    with pytest.raises(EngineSelectionError) as excinfo:
        resolve_engine("turbo")
    assert excinfo.value.requested == "turbo"


# ---- sanitize_result (privacy boundary) ----------------------------------


def _result_with_positions():
    from openbb_backtest.models import (
        BacktestConfig,
        BacktestResult,
        EquityPoint,
        PerformanceMetrics,
        PositionSnapshot,
        Trade,
    )

    cfg = BacktestConfig(
        strategy="buy_and_hold",
        universe=["AAA"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
    )
    metrics = PerformanceMetrics(
        cagr=0.1, sharpe=1.0, sortino=1.0, calmar=1.0, max_drawdown=-0.05,
        volatility=0.1, var_95=-0.02, cvar_95=-0.03, win_rate=0.6,
        profit_factor=1.5, turnover=2.0,
    )
    return BacktestResult(
        equity_curve=[
            EquityPoint(
                date=datetime(2021, 1, 4), equity=Decimal("100000"),
                cash=Decimal("0"), exposure=1.0,
            )
        ],
        trades=[
            Trade(
                timestamp=datetime(2021, 1, 4), symbol="AAA", side="buy",
                quantity=Decimal("10"), price=Decimal("100"),
            )
        ],
        positions=[
            PositionSnapshot(
                date=datetime(2021, 1, 4), symbol="AAA",
                quantity=Decimal("10"), market_value=Decimal("1000"), weight=1.0,
            )
        ],
        metrics=metrics,
        engine_used="vectorized",
        config=cfg,
    )


def test_sanitize_result_strips_raw_positions():
    from openbb_backtest.router_helpers import sanitize_result

    out = sanitize_result(_result_with_positions())
    assert out.positions == []


def test_sanitize_result_preserves_metrics_and_equity_curve():
    from openbb_backtest.router_helpers import sanitize_result

    original = _result_with_positions()
    out = sanitize_result(original)
    assert out.metrics.sharpe == original.metrics.sharpe
    assert len(out.equity_curve) == len(original.equity_curve)
    assert out.engine_used == "vectorized"


def test_sanitize_result_does_not_mutate_the_input():
    from openbb_backtest.router_helpers import sanitize_result

    original = _result_with_positions()
    sanitize_result(original)
    # The privacy strip returns a copy; the caller's object is untouched.
    assert len(original.positions) == 1


def test_sanitize_result_serialized_payload_has_no_position_lot_detail():
    from openbb_backtest.router_helpers import sanitize_result

    out = sanitize_result(_result_with_positions())
    assert out.model_dump()["positions"] == []


# ---- credential / provider plumbing --------------------------------------


def test_resolve_provider_defaults_to_fmp_cached():
    from openbb_backtest.router_helpers import resolve_provider

    assert resolve_provider(None) == "fmp_cached"


def test_resolve_provider_passes_through_explicit_name():
    from openbb_backtest.router_helpers import resolve_provider

    assert resolve_provider("fmp_cached") == "fmp_cached"


def test_resolve_provider_default_is_sourced_from_settings():
    from openbb_backtest.router_helpers import resolve_provider
    from openbb_backtest.settings import DEFAULT_SETTINGS

    # The fallback provider is the configurable settings default, not a literal.
    assert resolve_provider(None) == DEFAULT_SETTINGS.default_provider
    assert DEFAULT_SETTINGS.default_provider == "fmp_cached"


def test_required_credentials_names_only_no_secret_values():
    from openbb_backtest.router_helpers import required_credentials

    creds = required_credentials("fmp_cached")
    # Returns credential *names* the platform resolves — never plaintext secrets.
    assert "fmp_cached_api_key" in creds
    assert all(isinstance(name, str) for name in creds)
    assert all("key" in name.lower() or "token" in name.lower() for name in creds)


# ---- build_feed (store-root must agree with the bundle writer) -----------


def test_build_feed_loads_from_settings_bundle_root(monkeypatch):
    # The reader (build_feed) must load from the same configurable store root the
    # writer (bundle.ingest) persists to -- both source it from settings so a
    # custom OPENBB_BACKTEST_BUNDLE_ROOT can never split them apart.
    from datetime import date

    from openbb_backtest.data import bundle as bundle_mod
    from openbb_backtest.models import BacktestConfig
    from openbb_backtest.router_helpers import build_feed
    from openbb_backtest.settings import DEFAULT_SETTINGS

    captured: dict = {}

    class _FakeIngestor:
        def __init__(self, *a, **kw):
            pass

        def ingest(self, *a, **kw):
            return bundle_mod.BundleMetadata(name="fmp_cached", symbols=["AAA"], calendar="XNYS")

    def _capture_load(root, name):
        captured["root"] = root
        return object()

    monkeypatch.setattr(bundle_mod, "FmpCachedReader", lambda *a, **kw: object())
    monkeypatch.setattr(bundle_mod, "BundleIngestor", _FakeIngestor)
    monkeypatch.setattr(bundle_mod.Bundle, "load", staticmethod(_capture_load))
    # A custom (non-default) store root must flow through to the loader.
    monkeypatch.setattr(DEFAULT_SETTINGS, "bundle_root", "custom/bundle/store")

    config = BacktestConfig(
        strategy="s", universe=["AAA"], start=date(2021, 1, 4), end=date(2021, 1, 8)
    )
    build_feed(config, provider="fmp_cached")
    assert captured["root"] == "custom/bundle/store"
