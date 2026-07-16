"""build_signals-layer classic-path invariance goldens (bd-o4q).

Blocks bd-luy (first family PR). Pins the bytes of ``build_signals``
output for the recorded basket at the anchor date so no family PR can
accidentally change the classic path without a deliberate golden regen.

Why this file exists (spec §D8 + code-reviewer YELLOW 2b, bd-7ct iter-1):
- ``build_signals`` calls ``build_signal`` WITHOUT ``panel_config``.
- Downstream consumers (``list_movers`` / ``scan_segments`` /
  ``plan_router`` / ``screener_router``) all go through ``build_signals``.
- bd-7ct pinned the ``build_signal`` layer output but NOT the layer above.
- Family PRs (bd-luy et al) will add ``panel_config`` threading to
  ``build_signals`` — this golden guards against classic-path drift
  while that wiring lands.

Uses the recorded basket fixture + an offline panel fetcher (no live
fmp_cached calls), so the golden is reproducible cross-env.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openbb_techtrade.engine import indicators, signals
from openbb_techtrade.testing import assert_matches_golden

# Load the techtrade tests/fixtures module by absolute path to bypass
# pytest's `tests` package-name ambiguity when running under repo-root
# scope (multiple tests/__init__.py trees exist across extensions, and
# under `--import-mode=importlib` the enclosing package resolution is
# not stable). See PR restoring Unit test Platform CI.
import importlib.util as _iu
from pathlib import Path as _Path
_fixtures_path = _Path(__file__).parent.parent / "fixtures" / "__init__.py"
_spec = _iu.spec_from_file_location("_techtrade_fixtures", _fixtures_path)
_fixtures_mod = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures_mod)
load_basket = _fixtures_mod.load_basket

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "build_signals_invariance"

# Anchor date matches bd-7ct's flag-off-invariance goldens for consistency.
AS_OF = date(2025, 6, 16)


def _build_offline_fetcher(basket: dict):
    """Return a panel_fetcher that reads from the recorded basket
    instead of hitting fmp_cached. Ranks like the live fetcher would,
    but deterministically."""
    def _fetch(symbol, *, as_of):
        df = basket[symbol].sort_index()
        df_thru = df[df.index.date <= as_of]
        records = df_thru.reset_index().to_dict(orient="records")
        return indicators.build_indicator_panel(
            symbol=symbol,
            as_of=df_thru.index[-1].date(),
            ohlcv_rows=records,
        )
    return _fetch


def _signals_to_dict(signal_list) -> dict:
    """Serialise a list[MoverSignal] to a stable dict for golden diff.

    Excludes non-deterministic ``candles`` implicitly (already excluded
    at the panel layer per bd-7ct.8) and lists votes in the ranked order
    they appear (so a family PR that changes the ranking mechanism —
    not just the vote count — flips the golden loudly)."""
    return {
        "count": len(signal_list),
        "signals": [
            {
                "symbol": s.symbol,
                "segment": s.segment,
                "as_of": s.as_of.isoformat(),
                "score": s.score,
                "direction": s.direction,
                "rank_in_segment": s.rank_in_segment,
                "votes": [
                    {
                        "family": v.family,
                        "name": v.name,
                        "vote": v.vote,
                        "weight": v.weight,
                    }
                    for v in s.votes
                ],
            }
            for s in signal_list
        ],
    }


class TestBuildSignalsClassicInvariance:
    """R7.11 load-bearing: pins ``build_signals`` output bytes for the
    full 5-symbol basket at the anchor date, one golden per preset.

    Family PRs (bd-luy et al) MUST regenerate these goldens deliberately
    when they change the extended-panel wiring — the classic-path output
    should not change (byte-identity is the AC).
    """

    @pytest.mark.parametrize("preset", ["trend_follow", "mean_revert", "breakout"])
    def test_build_signals_classic_matches_golden(self, preset):
        basket = load_basket()
        # Use ALL 5 basket symbols so any per-symbol drift is caught.
        symbols = ["NVDA", "PG", "XOM", "PLTR", "SPY"]
        fetcher = _build_offline_fetcher(basket)
        result = signals.build_signals(
            symbols=symbols,
            preset=preset,
            as_of=AS_OF,
            panel_fetcher=fetcher,
        )
        assert_matches_golden(
            name=f"build_signals_{preset}_2025-06-16",
            payload=_signals_to_dict(result),
            fixture_dir=GOLDEN_DIR,
        )


class TestBuildSignalsRankingContract:
    """Non-golden R7.4 seam contract tests — verify ranking-layer
    invariants that a family PR could break independently of the
    vote-content bytes."""

    def test_rank_in_segment_is_contiguous_from_one(self):
        """rank_in_segment must be 1..N contiguous after ranking, per
        PRD §12.3. A family PR that adds indicators shouldn't leave
        gaps in the ranking (empty slots) or off-by-one starts."""
        basket = load_basket()
        symbols = ["NVDA", "PG", "XOM", "PLTR", "SPY"]
        fetcher = _build_offline_fetcher(basket)
        result = signals.build_signals(
            symbols=symbols, preset="trend_follow",
            as_of=AS_OF, panel_fetcher=fetcher,
        )
        ranks = [s.rank_in_segment for s in result]
        assert ranks == list(range(1, len(result) + 1)), (
            f"ranks must be 1..{len(result)} contiguous; got {ranks}"
        )

    def test_ranking_is_score_descending(self):
        """The ranking order must be `score` descending. A family PR
        that flips the sort would silently invert the "top mover"
        semantics without any single vote diff — golden alone wouldn't
        catch a *complete* sort inversion if the vote bytes match, but
        an explicit sort assertion does."""
        basket = load_basket()
        symbols = ["NVDA", "PG", "XOM", "PLTR", "SPY"]
        fetcher = _build_offline_fetcher(basket)
        result = signals.build_signals(
            symbols=symbols, preset="trend_follow",
            as_of=AS_OF, panel_fetcher=fetcher,
        )
        scores = [s.score for s in result]
        assert scores == sorted(scores, reverse=True), (
            f"scores must be descending; got {scores}"
        )

    def test_all_signals_carry_the_same_as_of(self):
        """Every ranked signal in one call must share the same as_of
        (the resolved session). A family PR that accidentally passes a
        per-symbol as_of would silently corrupt the cross-symbol
        ranking timeline."""
        basket = load_basket()
        symbols = ["NVDA", "PG", "XOM", "PLTR", "SPY"]
        fetcher = _build_offline_fetcher(basket)
        result = signals.build_signals(
            symbols=symbols, preset="trend_follow",
            as_of=AS_OF, panel_fetcher=fetcher,
        )
        as_ofs = {s.as_of for s in result}
        assert len(as_ofs) == 1, (
            f"all signals must share one as_of; got {sorted(as_ofs)}"
        )
