"""bd-cht: conformance_strategy harness (D5 §9.1).

Discovers Pine strategy fixture triples in ``./fixtures/<name>/`` and
provides ``strategy_conformance_triple`` as a parametrized pytest
fixture. Each triple runs against
``obb.pine.strategies.run_byo(source=<pine>, records=deterministic_500_bars)``
(bd-250). Three parity assertions (equity curve, trade list, stats)
live in ``test_conformance_strategy.py``.

A fixture "triple" is actually four files sharing a stem:

    fixtures/<name>/<name>.pine        # Pine v5/v6 source
    fixtures/<name>/<name>.equity.csv  # bar_index,equity,drawdown (500 rows)
    fixtures/<name>/<name>.trades.csv  # closed-trade table (header + N rows)
    fixtures/<name>/<name>.stats.csv   # 1 row of the serialized stats dict

Incomplete fixture directories are logged and skipped so half-authored
fixtures don't silently disappear from the run.

bd-cht ships ONE placeholder fixture (``placeholder_smoke``) to prove
the harness runs end-to-end. bd-ph0 ships the five real triples
(rsi_reversal, sma_crossover, breakout_atr, bb_squeeze, macd_histogram)
using this same harness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Fixed date-based seed so any new fixture author generating expected
# values from a fresh run produces byte-identical bars to what the
# harness feeds run_byo at test time. Do NOT change this seed — every
# recorded expected value in every fixture depends on it.
DETERMINISTIC_SEED = 20260711
DETERMINISTIC_N_BARS = 500


@dataclass(frozen=True)
class StrategyTriple:
    """One fixture: Pine source + three expected-value CSVs."""

    name: str
    pine_path: Path
    equity_path: Path
    trades_path: Path
    stats_path: Path


def _discover_strategy_triples() -> list[StrategyTriple]:
    """Walk ``fixtures/<name>/`` and collect complete triples.

    A triple is complete when all four files (pine + equity.csv +
    trades.csv + stats.csv) exist under ``fixtures/<name>/`` with a
    matching stem. Incomplete directories are logged at WARNING and
    skipped, never silently dropped.
    """
    if not FIXTURES_DIR.exists():
        return []
    triples: list[StrategyTriple] = []
    for subdir in sorted(FIXTURES_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        name = subdir.name
        pine = subdir / f"{name}.pine"
        equity = subdir / f"{name}.equity.csv"
        trades = subdir / f"{name}.trades.csv"
        stats = subdir / f"{name}.stats.csv"
        missing = [p.name for p in (pine, equity, trades, stats) if not p.exists()]
        if missing:
            logger.warning(
                "conformance_strategy: skipping incomplete fixture %r "
                "(missing: %s)",
                name,
                ", ".join(missing),
            )
            continue
        triples.append(
            StrategyTriple(
                name=name,
                pine_path=pine,
                equity_path=equity,
                trades_path=trades,
                stats_path=stats,
            )
        )
    return triples


def _deterministic_500_bars() -> list[dict]:
    """Fixed-seed synthetic 500-bar OHLCV, materialized as run_byo records.

    Uses a Gaussian random walk seeded by ``DETERMINISTIC_SEED`` so any
    fixture author who calls this helper to generate expected values
    gets the exact bytes the test harness will feed run_byo at test
    time. UTC daily bars starting 2024-01-01.
    """
    rng = np.random.default_rng(seed=DETERMINISTIC_SEED)
    n = DETERMINISTIC_N_BARS
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
    df = pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        }
    )
    # run_byo expects ISO date strings, not pandas Timestamps.
    records = df.to_dict(orient="records")
    for r in records:
        r["date"] = r["date"].isoformat()
    return records


@pytest.fixture(
    params=_discover_strategy_triples(),
    ids=lambda t: t.name,
)
def strategy_conformance_triple(request) -> StrategyTriple:
    """Parametrized fixture yielding each discovered ``StrategyTriple``."""
    return request.param


@pytest.fixture
def deterministic_500_bars() -> list[dict]:
    """Fresh copy of the deterministic bar set for one test."""
    return _deterministic_500_bars()
