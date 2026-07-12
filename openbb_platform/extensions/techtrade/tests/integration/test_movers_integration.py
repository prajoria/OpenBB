"""Integration test for the top-mover ranking engine against live fmp_cached (#70).

Runs the *real* default candidate fetcher (``obb.equity.discovery.*`` plus, when
needed, ``obb.equity.price.historical`` via fmp_cached) end to end for the
Information Technology sector. Marked ``integration`` and skips cleanly when
credentials are missing or the data source is unreachable, so the default unit
suite stays hermetic (mirrors the universe integration resilience).
"""

from __future__ import annotations

from datetime import date

import pytest

from openbb_techtrade.engine.movers import (
    _default_candidate_fetcher,
    list_movers,
    resolve_session,
)
from openbb_techtrade.models import MoverList

pytestmark = pytest.mark.integration


def test_movers_information_technology_live():
    try:
        result = list_movers(
            segment="Information Technology",
            metric="pct_change",
            top_n=5,
        )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live movers unavailable for Information Technology: {exc}")

    assert result, "Information Technology resolved to no MoverList"
    first = result[0]
    assert isinstance(first, MoverList)
    assert first.segment == "Information Technology"
    assert isinstance(first.as_of, date)
    assert len(first.movers) <= 5
    # Ranks are 1..n contiguous in order.
    assert [m.rank for m in first.movers] == list(range(1, len(first.movers) + 1))


def test_default_candidate_fetcher_live_returns_pool():
    try:
        pool = _default_candidate_fetcher(resolve_session(None))
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live discovery pool unavailable: {exc}")

    # The live fmp_cached discovery union is non-empty and every entry is keyed.
    assert pool, "Live discovery returned an empty candidate pool"
    assert all("symbol" in candidate for candidate in pool)


def test_movers_it_smoke_bd_lw3_regression():
    """bd-lw3 regression smoke test (R7.2 promoted from diag_movers_zero.py).

    Verifies the 3-defect fix holds against a real market: for a sector
    with 70+ constituents (IT/XLK), the movers list must return:
      - >= 8 movers (not the 5-name discovery-intersection collapse)
      - every mover has volume > 0 (not the discovery-feed None → 0)
      - pct_change spread is not all-zero (not the +0.01% fraction-
        displayed-as-percent visual bug)
    """
    from openbb_techtrade.models import Mover

    try:
        result = list_movers(
            segment="Information Technology",
            metric="pct_change",
            top_n=10,
        )
    except Exception as exc:  # noqa: BLE001 - graceful degrade
        pytest.skip(f"Live movers unavailable for IT sector: {exc}")

    assert result, "IT sector produced no MoverList"
    ml = result[0]
    assert isinstance(ml, MoverList)
    # Defect 3 fix: universe-driven candidate pool → >= 8 real movers, not
    # a 5-name discovery-intersection collapse.
    assert len(ml.movers) >= 8, (
        f"bd-lw3 Defect 3 (universe collapse): expected >= 8 IT movers "
        f"from ~70 XLK constituents; got {len(ml.movers)}. Regression: "
        f"the fetcher fell back to the discovery-firehose path and "
        f"intersected with the sector universe."
    )
    for m in ml.movers:
        assert isinstance(m, Mover)
        # Defect 1 fix: real volume from per-symbol OHLCV, not the
        # None-coerced-to-0 from the discovery feed.
        assert m.volume > 0, (
            f"bd-lw3 Defect 1 (volume=None): expected volume > 0 for "
            f"{m.symbol}, got {m.volume}. Regression: the discovery "
            f"path is populating pct_change/volume, and "
            f"EquityPerformanceData.volume is None."
        )
    # Defect 2 fix (Option B2): pct_change is a human percent, so the
    # spread across 10 movers should be > 0.5 (not all-zero from the
    # fraction-displayed-as-fraction visual bug).
    spreads = [m.pct_change for m in ml.movers]
    assert max(spreads) - min(spreads) > 0.5, (
        f"bd-lw3 Defect 2 (pct_change unit): expected non-trivial spread "
        f"across 10 IT movers; got range={max(spreads)-min(spreads):.4f} "
        f"across {spreads}. Regression: pct_change is stored as a "
        f"fraction so the spread compresses by 100x."
    )
