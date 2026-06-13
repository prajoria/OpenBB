"""Unit tests for the techtrade golden-file test harness (issue #71, PRD §17).

Fully offline. Exercises ``to_jsonable`` type coercion (Decimal -> str, date /
datetime -> isoformat, nested pydantic ``Data`` -> dict) and ``assert_matches_golden``
match / mismatch / float-tolerance / regen-write behavior using a tmp fixture dir.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_techtrade.models import Mover
from openbb_techtrade.testing import (
    REGEN_ENV,
    assert_matches_golden,
    to_jsonable,
)


def test_to_jsonable_coerces_decimal_to_string():
    assert to_jsonable(Decimal("300")) == "300"
    assert to_jsonable({"volume": Decimal("12.5")}) == {"volume": "12.5"}


def test_to_jsonable_coerces_dates_to_isoformat():
    assert to_jsonable(date(2024, 1, 12)) == "2024-01-12"
    assert to_jsonable(datetime(2024, 1, 12, 9, 30)) == "2024-01-12T09:30:00"


def test_to_jsonable_handles_nested_pydantic_and_lists():
    mover = Mover(symbol="AAA", pct_change=0.05, volume=Decimal("200"), rank=1)
    out = to_jsonable([mover])
    assert out == [{"symbol": "AAA", "pct_change": 0.05, "volume": "200", "rank": 1}]


def test_to_jsonable_coerces_non_finite_floats_to_sentinel():
    assert to_jsonable(float("nan")) == "__nonfinite__:nan"
    assert to_jsonable(float("inf")) == "__nonfinite__:inf"
    assert to_jsonable(float("-inf")) == "__nonfinite__:-inf"


def test_assert_matches_golden_locks_non_finite_via_sentinel(tmp_path):
    import json as _json
    payload = {"rsi": float("nan")}
    (tmp_path / "ind.json").write_text(_json.dumps({"rsi": "__nonfinite__:nan"}) + "\n", encoding="utf-8")
    # The NaN payload now matches the sentinel-bearing golden (no permanent red).
    assert_matches_golden("ind", payload, fixture_dir=tmp_path)


def test_assert_matches_golden_passes_on_exact_match(tmp_path: Path):
    payload = {"a": 1, "nested": {"b": "x"}}
    (tmp_path / "fx.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    # Does not raise.
    assert_matches_golden("fx", payload, fixture_dir=tmp_path)


def test_assert_matches_golden_allows_float_within_tolerance(tmp_path: Path):
    (tmp_path / "fx.json").write_text(json.dumps({"x": 1.0}) + "\n", encoding="utf-8")
    assert_matches_golden("fx", {"x": 1.0 + 1e-12}, fixture_dir=tmp_path, tol=1e-9)


def test_assert_matches_golden_raises_on_value_mismatch(tmp_path: Path):
    (tmp_path / "fx.json").write_text(json.dumps({"x": 1.0}) + "\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_matches_golden("fx", {"x": 2.0}, fixture_dir=tmp_path)


def test_assert_matches_golden_raises_on_structural_mismatch(tmp_path: Path):
    (tmp_path / "fx.json").write_text(json.dumps({"x": 1}) + "\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_matches_golden("fx", {"x": 1, "y": 2}, fixture_dir=tmp_path)


def test_assert_matches_golden_regen_writes_fixture(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(REGEN_ENV, "1")
    payload = {"symbol": "AAA", "volume": "200"}
    assert_matches_golden("fresh", payload, fixture_dir=tmp_path)
    written = json.loads((tmp_path / "fresh.json").read_text(encoding="utf-8"))
    assert written == payload


def test_assert_matches_golden_missing_fixture_without_regen_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        assert_matches_golden("nope", {"x": 1}, fixture_dir=tmp_path)
