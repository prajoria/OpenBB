"""Integration tests for the bundle sub-router against live fmp_cached MySQL.

These exercise the *real* ``obb.backtest.bundle.ingest`` -> ``BundleIngestor`` ->
``FmpCachedReader`` -> parquet path and the ``bundle.list`` enumeration over the
written store, with no fakes. They are marked ``integration`` and skip cleanly
when the ``openbb_fmp_cache`` database is unreachable, so the default unit suite
stays hermetic.

Anchored on the same stable fact as the C03 bundle integration test: AAPL trades
exactly 5 sessions in the holiday-free week 2021-01-04..08.

See ``docs/designs/backtest-design/09-api-surface.md`` §1.
"""

from __future__ import annotations

from datetime import date

import pytest


def _db_available() -> bool:
    try:
        from openbb_fmp_cached.utils.database import execute_query

        execute_query("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip integration"
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _db_available(), reason="openbb_fmp_cache MySQL not reachable"
    ),
]


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="buy_and_hold",
        universe=["AAPL"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
    )
    params.update(kw)
    return BacktestConfig(**params)


def test_bundle_ingest_then_list_end_to_end(monkeypatch, tmp_path):
    from openbb_backtest.models import BundleInfo
    from openbb_backtest.routers import bundle_router as br

    # Point the store root at tmp_path so the live ingest writes there.
    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))

    ingested = br.ingest(_config(), name="it_router_aapl")
    assert isinstance(ingested.results, BundleInfo)
    assert ingested.results.name == "it_router_aapl"
    assert ingested.results.symbols == ["AAPL"]
    assert ingested.results.calendar == "XNYS"

    listed = br.list()
    names = [b.name for b in listed.results]
    assert "it_router_aapl" in names
    found = next(b for b in listed.results if b.name == "it_router_aapl")
    assert found.symbols == ["AAPL"]
    # The week 2021-01-04..08 frames the ingested calendar range.
    assert found.start == "2021-01-04"
    assert found.end == "2021-01-08"


def test_bundle_ingest_default_name_is_provider(monkeypatch, tmp_path):
    # With no explicit name the bundle is named after the resolved provider, so the
    # engine routers' build_feed(name=provider) can load it straight back.
    from openbb_backtest.routers import bundle_router as br

    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))
    out = br.ingest(_config())
    assert out.results.name == "fmp_cached"
    assert "fmp_cached" in [b.name for b in br.list().results]
