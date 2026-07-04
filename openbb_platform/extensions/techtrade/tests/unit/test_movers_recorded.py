"""Recorded-fixture unit test for ``list_movers`` (bd ri3, R7.1 follow-up to z7f).

Motivation
----------
bd ``OpenBBTechnical-z7f`` — ``techtrade.movers`` returned 0 movers for every
sector segment for months while 363 unit tests stayed green. Every existing
unit test injected hand-crafted mocks whose output was constructed to
*deliberately overlap* with the fake universe, so the tests could never
detect that the real discovery firehose does not intersect real sector-ETF
universes.

Rule R7.1 in ``rules/DEVELOPMENT_RULES.md`` Section 7 now requires that at
least one test per public entry point uses realistic-shape fixtures for
BOTH injected seams. This module delivers that test for
:func:`~openbb_techtrade.engine.movers.list_movers`.

Fixture provenance
------------------
The two JSON fixtures under ``tests/fixtures/movers/`` were captured live
against ``fmp_cached`` via ``temp/capture_movers_fixtures.py``:

* ``discovery_gainers.json`` — ``obb.equity.discovery.gainers`` response
  (~50 rows, dominated by low-priced small-cap daily swings).
* ``xlk_holdings.json`` — ``obb.etf.holdings(symbol="XLK")`` response
  (~75 mega-cap Information Technology names).

Their symbol sets have **zero overlap** on the capture date — the exact
signature of the ``z7f`` failure mode.

What this test proves
---------------------
Under the pre-``z7f`` code path (fan-out-then-filter: fetch the discovery
firehose, then intersect with the sector universe), ``build_mover_list``
would have returned an empty list. Under the post-``z7f`` universe path
(narrow-then-fan-out: fetch per-symbol OHLCV for the universe directly),
it returns at least one mover for every valid universe.

Why this is a unit test (not integration)
-----------------------------------------
The fixtures are on-disk JSON — no network, no keys required. This is
what R7.1 calls "realistic-shape" testing: fake seams, real payloads.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openbb_techtrade.engine.movers import list_movers
from openbb_techtrade.models import MoverList

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "movers"


def _load(name: str) -> list[dict]:
    """Load a captured fixture and return its ``rows`` list."""
    with (_FIXTURE_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)["rows"]


@pytest.fixture(scope="module")
def gainers_rows() -> list[dict]:
    """Rows from a real ``obb.equity.discovery.gainers`` response."""
    return _load("discovery_gainers.json")


@pytest.fixture(scope="module")
def xlk_rows() -> list[dict]:
    """Rows from a real ``obb.etf.holdings(symbol='XLK')`` response."""
    return _load("xlk_holdings.json")


def _make_candidate_fetcher(gainers_rows: list[dict], xlk_rows: list[dict]):
    """Build a fake ``candidate_fetcher`` that mimics the live path.

    Mirrors :func:`~openbb_techtrade.engine.movers._default_candidate_fetcher`'s
    branch behavior:

    * If ``universe`` is non-empty, synthesizes per-symbol candidate dicts for
      the requested universe using ``xlk_rows`` as the "OHLCV" source. This is
      the sector-scan path the ``z7f`` fix takes.
    * Otherwise, folds the discovery ``gainers_rows`` into candidate dicts
      keyed on ``symbol``, exactly like the pre-``z7f`` fan-out path.

    The pre-``z7f`` code path (universe-less) followed by
    ``build_mover_list``'s downstream ``symbol in allowed`` filter would
    produce zero movers on this fixture pair — 50 gainer symbols intersected
    with 75 XLK symbols = 0 overlap. The post-``z7f`` code path (universe
    threaded through) produces a candidate for each XLK symbol.
    """
    xlk_by_symbol = {r["symbol"]: r for r in xlk_rows if r.get("symbol")}

    def _fake_fetcher(
        *,
        as_of: date,
        calendar: str = "XNYS",
        needs_ohlcv: bool = False,
        universe: list[str] | None = None,
        **_kwargs: object,
    ) -> list[dict]:
        if universe:
            # Universe path: produce one candidate per requested symbol we know.
            # ``pct_change`` here stands in for an OHLCV-derived value; the
            # exact number isn't asserted, only that the ranker gets *some*
            # non-null metric per candidate so it can order them.
            return [
                {
                    "symbol": sym,
                    "pct_change": 0.01,
                    "volume": int(xlk_by_symbol[sym].get("shares") or 1_000_000),
                }
                for sym in universe
                if sym in xlk_by_symbol
            ]
        # Discovery path — the pre-z7f behavior.
        candidates: dict[str, dict] = {}
        for row in gainers_rows:
            symbol = row.get("symbol")
            if not symbol or symbol in candidates:
                continue
            candidates[symbol] = {
                "symbol": symbol,
                "pct_change": row.get("percent_change"),
                "volume": row.get("volume"),
            }
        return list(candidates.values())

    return _fake_fetcher


def _make_holdings_fetcher(xlk_rows: list[dict]):
    """Build a fake ``holdings_fetcher`` mirroring the live ETF holdings shape.

    :func:`~openbb_techtrade.engine.universe._default_holdings_fetcher`
    returns a bare ``list[str]`` of constituent symbols; this fake does the
    same, filtered to non-null symbol rows.
    """

    def _fake_holdings(etf_symbol: str) -> list[str]:
        if etf_symbol != "XLK":
            return []
        return [r["symbol"] for r in xlk_rows if r.get("symbol")]

    return _fake_holdings


def _make_fake_obb_for_universe_path():
    """Fake ``obb`` module surface exercised on the sector-scan (universe) path.

    ``_fetch_universe_candidates`` calls ``obb.equity.price.historical(...)``
    per symbol; we return two synthetic OHLCV bars per call so
    :func:`compute_ohlcv_metrics` produces a non-null metric row. The exact
    numbers don't matter — the load-bearing behavior is that the real code
    path in :func:`_default_candidate_fetcher` dispatches to the universe
    branch when ``universe`` is non-empty, and that ``list_movers`` threads
    it through end-to-end.
    """

    def _fake_historical(**_kwargs: object) -> SimpleNamespace:
        # Two chronologically-ascending bars — compute_ohlcv_metrics needs
        # >= 2 bars to derive pct_change / gap / rel_volume without falling
        # into its 1-bar degenerate branch.
        bars = [
            SimpleNamespace(
                open=100.0, high=101.0, low=99.5, close=100.5, volume=1_000_000
            ),
            SimpleNamespace(
                open=100.5, high=102.0, low=100.0, close=101.5, volume=1_200_000
            ),
        ]
        return SimpleNamespace(results=bars)

    return SimpleNamespace(
        equity=SimpleNamespace(
            price=SimpleNamespace(historical=_fake_historical),
        ),
    )


def test_list_movers_information_technology_end_to_end_with_recorded_holdings(
    xlk_rows: list[dict],
) -> None:
    """End-to-end ``list_movers("Information Technology")`` — the true R7.2 guard.

    This is the load-bearing regression test for bd-z7f. Unlike a naive R7.2
    test that stubs the candidate_fetcher (which shortcuts
    ``_resolve_filter_universe`` to ``None`` and never runs the universe
    path), this test:

    1. Injects only ``holdings_fetcher`` — driven by the recorded XLK fixture
       — so ``_resolve_filter_universe`` stays on the live branch and
       resolves the XLK universe against the real ``resolve_universe``.
    2. Patches ``openbb.obb`` at module scope so the *real*
       ``_default_candidate_fetcher`` runs. With ``universe`` non-empty it
       dispatches to ``_fetch_universe_candidates``, which in turn calls the
       patched ``obb.equity.price.historical`` per XLK symbol.

    Under the pre-z7f code (fan-out-then-filter: no ``universe`` kwarg,
    discovery firehose intersected with XLK downstream) this returns 0
    movers because the two symbol populations have zero overlap. Under the
    post-z7f code (narrow-then-fan-out: universe threaded to the fetcher)
    this returns 10 movers, one per top-N XLK symbol.

    If someone reverts the z7f fix (drops ``universe=universe`` from
    ``build_mover_list``'s fetcher call or the ``if universe:`` branch in
    ``_default_candidate_fetcher``), this test fails with ``len(movers) == 0``.
    """
    holdings = _make_holdings_fetcher(xlk_rows)
    fake_obb = _make_fake_obb_for_universe_path()

    import openbb

    with patch.object(openbb, "obb", fake_obb):
        results = list_movers(
            segment="Information Technology",
            metric="pct_change",
            top_n=10,
            as_of="2024-01-10",  # arbitrary weekday session, no calendar drift
            holdings_fetcher=holdings,
            # NOTE: deliberately NO candidate_fetcher — that's the exact
            # short-circuit that made the previous version of this test
            # decorative. Letting it default to None keeps
            # ``_resolve_filter_universe`` on the live branch so the whole
            # z7f code path actually runs.
        )

    assert len(results) == 1
    assert isinstance(results[0], MoverList)
    assert results[0].segment == "Information Technology"

    # Under the pre-z7f fetch-then-filter path, len(movers) would be 0
    # (discovery firehose ∩ XLK == 0, per fixture provenance). Under the
    # post-z7f universe-threading path, every XLK symbol becomes a candidate
    # so we get the full top-N.
    assert len(results[0].movers) == 10, (
        f"Expected top-10 XLK movers from universe-path scan; got "
        f"{len(results[0].movers)}. If this is 0, the z7f fix regressed — "
        f"check that _default_candidate_fetcher receives universe= from "
        f"build_mover_list and dispatches to _fetch_universe_candidates."
    )

    # Every mover must be an XLK constituent (the sector-scan universe).
    xlk_symbols = {r["symbol"] for r in xlk_rows if r.get("symbol")}
    result_symbols = {m.symbol for m in results[0].movers}
    assert result_symbols.issubset(xlk_symbols), (
        f"movers escaped the XLK universe: {result_symbols - xlk_symbols}"
    )


def test_build_mover_list_takes_universe_path_when_universe_supplied(
    gainers_rows: list[dict],
    xlk_rows: list[dict],
) -> None:
    """Direct ``build_mover_list`` test proving the universe-path behavior.

    Complements the end-to-end test above by isolating the middle stage:
    when ``build_mover_list`` is called with a non-empty universe, the
    fetcher gets a per-symbol candidate for every XLK member — matching the
    ``z7f`` fix's design intent (narrow-then-fan-out, R7.4).

    Uses an injected fake ``candidate_fetcher`` so the assertion is on the
    fetcher's ``universe=`` receipt, not on the live discovery path.
    """
    from openbb_techtrade.engine.movers import build_mover_list
    from openbb_techtrade.models import SegmentConfig

    fetcher = _make_candidate_fetcher(gainers_rows, xlk_rows)
    xlk_universe = [r["symbol"] for r in xlk_rows if r.get("symbol")]

    config = SegmentConfig(
        segment="Information Technology",
        benchmark_etf="XLK",
        universe_source="etf_holdings",
        rank_metric="pct_change",
        top_n=10,
    )
    result = build_mover_list(
        config,
        as_of="2024-01-10",
        universe=xlk_universe,
        candidate_fetcher=fetcher,
    )

    assert isinstance(result, MoverList)
    assert result.segment == "Information Technology"
    # 10 top-N cap × exactly the intersection of XLK ∩ fake fetcher
    # (which returns one candidate per XLK symbol) → capped at top_n=10.
    assert len(result.movers) == 10
    # Every symbol in the result must have been in the XLK universe.
    xlk_symbols = set(xlk_universe)
    assert {m.symbol for m in result.movers}.issubset(xlk_symbols)


def test_recorded_fixture_intersection_is_zero() -> None:
    """Documents the ``z7f`` diagnosis in code (R7.5 — test the assumption).

    This test does not exercise any production code path — it asserts that
    the two captured fixtures reproduce the ``z7f`` failure signature:
    zero overlap between discovery-feed symbols and sector-ETF holdings.

    If a future refresh of the fixtures happens to produce a non-zero
    intersection (unlikely but possible), this test will fail loudly and
    tell the reader to re-verify the ``z7f`` diagnostic still holds.
    """
    gainers = _load("discovery_gainers.json")
    xlk = _load("xlk_holdings.json")

    gainer_symbols = {r["symbol"] for r in gainers if r.get("symbol")}
    xlk_symbols = {r["symbol"] for r in xlk if r.get("symbol")}
    intersection = gainer_symbols & xlk_symbols

    assert not intersection, (
        f"Fixture intersection is {len(intersection)} — expected 0. "
        f"The z7f diagnostic assumed the discovery feed (small-cap movers) "
        f"and sector-ETF universes (mega-caps) never overlap. If they now "
        f"do, this fixture may need re-capture on a different session, or "
        f"the z7f fix's premise needs re-evaluation. Overlap: "
        f"{sorted(intersection)[:10]}"
    )
