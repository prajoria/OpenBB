"""BandwidthMeter — accounting, thresholds, monthly rollover, atomic persistence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openbb_fmp_trading.core.bandwidth import BandwidthMeter


def test_charge_accumulates(tmp_path: Path):
    m = BandwidthMeter(
        state_path=tmp_path / "bw.json",
        budget_bytes=1_000_000,
        today=date(2026, 7, 6),
    )
    s = m.charge(100)
    assert s.month_used_bytes == 100
    m.charge(400)
    assert m.state.month_used_bytes == 500


def test_conservation_at_80_pct(tmp_path: Path):
    m = BandwidthMeter(
        state_path=tmp_path / "bw.json", budget_bytes=1_000, today=date(2026, 7, 6)
    )
    m.charge(750)  # 75%
    assert m.state.mode == "normal"
    m.charge(100)  # 85%
    assert m.state.mode == "conservation"


def test_halted_at_95_pct(tmp_path: Path):
    m = BandwidthMeter(
        state_path=tmp_path / "bw.json", budget_bytes=1_000, today=date(2026, 7, 6)
    )
    m.charge(960)
    assert m.state.mode == "halted"


def test_month_rollover_resets(tmp_path: Path):
    m = BandwidthMeter(
        state_path=tmp_path / "bw.json", budget_bytes=1_000, today=date(2026, 7, 6)
    )
    m.charge(500)
    m.rollover_if_needed(today=date(2026, 8, 1))
    assert m.state.month_used_bytes == 0
    assert m.state.mode == "normal"


def test_persists_across_instances(tmp_path: Path):
    path = tmp_path / "bw.json"
    m1 = BandwidthMeter(state_path=path, budget_bytes=1_000, today=date(2026, 7, 6))
    m1.charge(300)
    m2 = BandwidthMeter(state_path=path, budget_bytes=1_000, today=date(2026, 7, 6))
    assert m2.state.month_used_bytes == 300


def test_atomic_write_does_not_leave_temp_files(tmp_path: Path):
    """After N charges the state dir contains exactly {bw.json} — no stray tmp."""
    path = tmp_path / "bw.json"
    m = BandwidthMeter(state_path=path, budget_bytes=1_000, today=date(2026, 7, 6))
    for _ in range(5):
        m.charge(50)
    # tmp files (bw-*.json) must not linger — os.replace should have moved them.
    stray = [p for p in path.parent.iterdir() if p.name.startswith("bw-")]
    assert stray == [], f"stray temp files not cleaned up: {stray}"


def test_corrupt_state_file_starts_fresh(tmp_path: Path):
    """A corrupt bw.json is treated as month 0 rather than blocking startup."""
    path = tmp_path / "bw.json"
    path.write_text("{not json}", encoding="utf-8")
    m = BandwidthMeter(state_path=path, budget_bytes=1_000, today=date(2026, 7, 6))
    # Corrupt file -> starts from 0 rather than raising.
    assert m.state.month_used_bytes == 0
    assert m.state.mode == "normal"
