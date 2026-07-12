"""bd-0ru2: unit tests for the optional per-fixture ``<name>.bars.csv`` override.

The conformance_strategy harness accepts an optional fifth file per
fixture (``<name>.bars.csv``). When present, its rows are loaded via
:func:`_load_bars_csv` and fed to ``run_byo`` instead of the
deterministic 500-bar generator. These tests exercise the loader,
dataclass shape, and back-compat fallback path independently of any
real fixture — the parity tests in ``test_conformance_strategy.py``
consume the actual dispatch fixture (``bars_for_triple``).
"""

from __future__ import annotations

import csv
import dataclasses

import pytest

from openbb_pine.tests.conformance_strategy.conftest import (
    StrategyTriple,
    _deterministic_500_bars,
    _load_bars_csv,
)


def test_triple_dataclass_carries_bars_path() -> None:
    """StrategyTriple has a ``bars_path`` field (Optional[Path], defaulted)."""
    fields = {f.name: f for f in dataclasses.fields(StrategyTriple)}
    assert "bars_path" in fields, (
        f"StrategyTriple must have bars_path field; got {sorted(fields)}"
    )
    # Defaulted → existing callers that construct StrategyTriple with the
    # original four positional args keep working.
    assert fields["bars_path"].default is None


def test_load_bars_csv_parses_ohlcv(tmp_path) -> None:
    """_load_bars_csv returns list[dict] with float OHLCV + raw date string."""
    bars_csv = tmp_path / "synthetic.bars.csv"
    with bars_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close", "volume"]
        )
        w.writeheader()
        w.writerow(
            {
                "date": "2024-01-01T00:00:00+00:00",
                "open": "100.0",
                "high": "101.0",
                "low": "99.0",
                "close": "100.5",
                "volume": "1000",
            }
        )
        w.writerow(
            {
                "date": "2024-01-02T00:00:00+00:00",
                "open": "100.5",
                "high": "102.0",
                "low": "99.5",
                "close": "101.0",
                "volume": "1100",
            }
        )
    records = _load_bars_csv(bars_csv)
    assert len(records) == 2
    assert records[0]["close"] == 100.5
    assert records[0]["date"] == "2024-01-01T00:00:00+00:00"
    assert records[1]["volume"] == 1100.0
    # All OHLCV columns coerced to float; date kept as raw ISO string
    # (matching _deterministic_500_bars's ISO-string convention).
    for r in records:
        for k in ("open", "high", "low", "close", "volume"):
            assert isinstance(r[k], float), f"{k}={r[k]!r} is {type(r[k])}"
        assert isinstance(r["date"], str)


def test_load_bars_csv_missing_column_raises(tmp_path) -> None:
    """Malformed bars.csv (missing 'volume') fails loudly at load time."""
    bars_csv = tmp_path / "broken.bars.csv"
    with bars_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close"]
        )
        w.writeheader()
        w.writerow(
            {
                "date": "2024-01-01T00:00:00+00:00",
                "open": "1",
                "high": "1",
                "low": "1",
                "close": "1",
            }
        )
    with pytest.raises(ValueError, match="volume"):
        _load_bars_csv(bars_csv)


def test_placeholder_smoke_falls_back_to_deterministic_generator() -> None:
    """The shipped placeholder_smoke fixture has no bars.csv → generator path."""
    from openbb_pine.tests.conformance_strategy.conftest import (
        _discover_strategy_triples,
    )

    triples = {t.name: t for t in _discover_strategy_triples()}
    assert "placeholder_smoke" in triples, (
        "placeholder_smoke must remain discoverable"
    )
    assert triples["placeholder_smoke"].bars_path is None, (
        "placeholder_smoke must NOT ship a bars.csv — its expected values "
        "are pinned to the deterministic generator (back-compat guarantee)."
    )
    # And that generator itself remains stable — 500 rows, deterministic.
    bars = _deterministic_500_bars()
    assert len(bars) == 500
