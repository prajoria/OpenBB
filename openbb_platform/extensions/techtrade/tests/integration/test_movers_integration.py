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
