"""bd-cht: conformance_strategy harness (D5 §9.1).

Discovers Pine strategy fixture triples in ``./fixtures/<name>/`` and
provides ``strategy_conformance_triple`` as a parametrized pytest
fixture. Each triple runs against
``obb.pine.strategies.run_byo(source=<pine>, records=<bars>)``
(bd-250). Three parity assertions (equity curve, trade list, stats)
live in ``test_conformance_strategy.py``.

A fixture "triple" is actually four required files sharing a stem plus
one OPTIONAL fifth file (bd-0ru2):

    fixtures/<name>/<name>.pine        # Pine v5/v6 source
    fixtures/<name>/<name>.equity.csv  # bar_index,equity,drawdown
    fixtures/<name>/<name>.trades.csv  # closed-trade table (header + N rows)
    fixtures/<name>/<name>.stats.csv   # 1 row of the serialized stats dict
    fixtures/<name>/<name>.bars.csv    # OPTIONAL: date,open,high,low,close,volume

Incomplete fixture directories are logged and skipped so half-authored
fixtures don't silently disappear from the run.

Per bd-0ru2: when ``<name>.bars.csv`` is present the harness uses those
bars (loaded via :func:`_load_bars_csv`) instead of the deterministic
500-bar generator. When absent, the harness falls back to
:func:`_deterministic_500_bars` (used only by ``placeholder_smoke``).
"""

from __future__ import annotations

import csv as _csv
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
# recorded expected value in every deterministic fixture depends on it.
DETERMINISTIC_SEED = 20260711
DETERMINISTIC_N_BARS = 500

_BARS_CSV_COLUMNS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class StrategyTriple:
    """One fixture: Pine source + three expected-value CSVs + optional bars CSV."""

    name: str
    pine_path: Path
    equity_path: Path
    trades_path: Path
    stats_path: Path
    bars_path: Path | None = None


def _discover_strategy_triples() -> list[StrategyTriple]:
    """Walk ``fixtures/<name>/`` and collect complete triples.

    A triple is complete when all four required files (pine + equity.csv +
    trades.csv + stats.csv) exist under ``fixtures/<name>/`` with a
    matching stem. Incomplete directories are logged at WARNING and
    skipped, never silently dropped.

    If ``<name>.bars.csv`` also exists it is attached as ``bars_path``
    on the triple (bd-0ru2). Its absence is *not* an incompleteness —
    the harness falls back to the deterministic generator when it's
    missing.
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
        bars = subdir / f"{name}.bars.csv"
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
                bars_path=bars if bars.exists() else None,
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


def _load_bars_csv(path: Path) -> list[dict]:
    """Load a bars.csv into a list of records matching run_byo's shape.

    Required columns: ``date, open, high, low, close, volume``. The
    ``date`` cell is kept as its raw string (ISO 8601 expected — no
    normalization is performed, matching the ISO-string convention of
    :func:`_deterministic_500_bars`). OHLCV cells are parsed to
    ``float``. Missing/extra columns raise :class:`ValueError` early so
    a malformed fixture fails loudly rather than at the run_byo layer.
    """
    with path.open(newline="", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        missing = set(_BARS_CSV_COLUMNS) - set(fieldnames)
        if missing:
            raise ValueError(
                f"bars.csv {path} missing required columns: {sorted(missing)}"
            )
        records: list[dict] = []
        for row in reader:
            records.append(
                {
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
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


@pytest.fixture
def bars_for_triple(strategy_conformance_triple) -> list[dict]:
    """Bars to feed run_byo for this triple (bd-0ru2).

    Uses the fixture's ``<name>.bars.csv`` when present, otherwise
    falls back to :func:`_deterministic_500_bars`. This is the fixture
    the parity tests should depend on — it keeps ``placeholder_smoke``
    on the deterministic path (no bars.csv shipped) while letting the
    five real bd-ph0 fixtures use TV-exported bars.
    """
    if strategy_conformance_triple.bars_path is not None:
        return _load_bars_csv(strategy_conformance_triple.bars_path)
    return _deterministic_500_bars()
