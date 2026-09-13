"""Compute-free TechTrade widget reads from the canonical EOD snapshot store."""

# ruff: noqa: D103

from __future__ import annotations

import importlib
import os
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient
from openbb_portfolio_intel.widget_backend.main import app
from openbb_techtrade.snapshot.datasets import (
    SURVIVORSHIP_UNCORRECTED,
    TECHTRADE_DATASETS,
)
from openbb_techtrade.snapshot.registry import DEFAULT_DATASET_REGISTRY
from openbb_techtrade.snapshot.store import SnapshotStatus, SqliteSnapshotStore

SESSION = date(2026, 9, 11)
SEGMENT = "Information Technology"
KEY = "segment=information technology"
DISCLAIMER = "EOD planning snapshot — not a live/intraday quote"
_client = TestClient(app)


def _rows_by_dataset() -> dict[str, list[dict]]:
    return {
        "techtrade.movers": [
            {"symbol": "NVDA", "segment": SEGMENT, "pct_change": 4.2, "rank": 1}
        ],
        "techtrade.scan": [
            {"symbol": "NVDA", "segment": SEGMENT, "score": 0.91, "direction": "long"}
        ],
        "techtrade.signals": [
            {"symbol": "NVDA", "segment": SEGMENT, "score": 0.91, "direction": "long"}
        ],
        "techtrade.plan": [
            {
                "symbol": "NVDA",
                "segment": SEGMENT,
                "recommendation": {
                    "entry_price": 100.0,
                    "stop_price": 95.0,
                    "target_price": 110.0,
                    "risk_reward": 2.0,
                },
            }
        ],
        "techtrade.orders": [
            {
                "symbol": "NVDA",
                "leg_type": "entry",
                "side": "BUY",
                "quantity": 10,
                "price": 100.0,
            }
        ],
        "techtrade.simulate": [{"symbol": "NVDA", "day": 1, "pnl": 12.5}],
        "techtrade.validate": [
            {"symbol": "NVDA", "metric": "PBO", "value": 0.18, "gate": "PASS"}
        ],
        "techtrade.tune": [
            {
                "symbol": "NVDA",
                "param": "atr_period",
                "current": 14,
                "proposed": 20,
                "delta": 6,
                "validate_gate": "PASS",
            }
        ],
        "techtrade.audit": [
            {
                "symbol": "NVDA",
                "bar_date": SESSION.isoformat(),
                "replay_cagr": 0.10,
                "replay_sharpe": 1.25,
                "forward_pnl": 80.0,
                "forward_return": 0.08,
            }
        ],
    }


def _seed(
    store: SqliteSnapshotStore,
    dataset: str,
    rows: list[dict],
    *,
    segment: str = SEGMENT,
    earnings_symbols: list[str] | None = None,
    session: date = SESSION,
) -> None:
    key = f"segment={segment.casefold()}"
    payload = {
        "rows": rows,
        "segment": segment,
        "as_of_session": session.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": (
            ["NVDA"] if earnings_symbols is None else earnings_symbols
        ),
        "excluded_symbols": [],
        "survivorship": (
            SURVIVORSHIP_UNCORRECTED
            if dataset in {"techtrade.validate", "techtrade.tune", "techtrade.audit"}
            else "not-applicable"
        ),
        "universe_membership": [],
    }
    run_id = f"{dataset.replace('.', '-')}-{segment.replace(' ', '-')}"
    store.stage(
        dataset,
        key,
        session,
        run_id,
        payload,
        status=SnapshotStatus.OK,
        row_count=len(rows),
        engine_version="test",
        payload_schema_version="1",
    )
    definition = DEFAULT_DATASET_REGISTRY.require(dataset)
    assert store.validate(
        dataset,
        key,
        session,
        run_id,
        lambda row: definition.validator(row, None),
    ).ok
    assert store.promote(dataset, key, session, run_id)


def _seeded_store(tmp_path: Path) -> SqliteSnapshotStore:
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    for dataset, rows in _rows_by_dataset().items():
        _seed(store, dataset, rows)
    return store


def test_all_snapshot_widgets_render_seeded_content_without_compute(
    tmp_path: Path, monkeypatch
) -> None:
    store = _seeded_store(tmp_path)
    movers_module = importlib.import_module("openbb_techtrade.engine.movers")
    monkeypatch.setattr(
        movers_module,
        "list_movers",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("compute called")),
    )
    endpoints = (
        "/tt/scan/segment-movers",
        "/tt/scan/table?segment=Information%20Technology",
        "/tt/scan/export",
        "/tt/position/signal-card?symbol=NVDA",
        "/tt/position/plan-card?symbol=NVDA",
        "/tt/position/order-legs?symbol=NVDA",
        "/tt/position/simulate?symbol=NVDA",
        "/tt/validation/verdict?symbol=NVDA",
        "/tt/tuning/report?symbol=NVDA",
        "/tt/audit/journal?symbol=NVDA",
    )

    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        for endpoint in endpoints:
            started = time.perf_counter()
            response = _client.get(endpoint)
            elapsed = time.perf_counter() - started
            assert response.status_code == 200, endpoint
            assert elapsed < 0.5, f"{endpoint} took {elapsed:.3f}s"
            body = response.json()
            assert "stub" not in str(body).lower()
            assert "NVDA" in str(body)
            assert DISCLAIMER in str(body)
    store.close()


def test_empty_store_is_loud_fast_and_compute_free(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "empty.db")

    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        started = time.perf_counter()
        response = _client.get("/tt/position/plan-card?symbol=NVDA")
        elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.5
    assert "No EOD snapshot available" in response.json()
    assert "post-close snapshot job" in response.json()
    store.close()


def test_sensitive_widgets_display_survivorship_warning(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        for endpoint in (
            "/tt/validation/verdict?symbol=NVDA",
            "/tt/tuning/report?symbol=NVDA",
            "/tt/audit/journal?symbol=NVDA",
        ):
            rows = _client.get(endpoint).json()
            assert rows
            assert all(row["survivorship"] == SURVIVORSHIP_UNCORRECTED for row in rows)
    store.close()


def test_every_registered_dataset_has_a_seed_fixture() -> None:
    assert tuple(_rows_by_dataset()) == TECHTRADE_DATASETS


def test_unknown_segment_is_a_client_error(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "empty.db")
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        response = _client.get("/tt/scan/table?segment=Technology")
    assert response.status_code == 400
    store.close()


def test_completed_empty_snapshot_is_not_reported_as_missing(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "empty-result.db")
    _seed(store, "techtrade.orders", [])
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        row = _client.get("/tt/position/order-legs?symbol=NVDA").json()[0]
    assert "Latest EOD snapshot completed" in row["note"]
    assert "No EOD snapshot available" not in row["note"]
    store.close()


def test_symbol_earnings_annotation_is_not_inherited_from_other_symbol(
    tmp_path: Path,
) -> None:
    store = SqliteSnapshotStore(tmp_path / "earnings.db")
    _seed(
        store,
        "techtrade.signals",
        [{"symbol": "AAPL", "score": 0.5, "direction": "long"}],
        earnings_symbols=["NVDA"],
    )
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        body = _client.get("/tt/position/signal-card?symbol=AAPL").json()
    assert "Reports before next open" not in body
    store.close()


def test_tuning_resolves_symbol_to_one_scan_segment(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "tuning.db")
    _seed(
        store,
        "techtrade.scan",
        [{"symbol": "NVDA", "segment": SEGMENT}],
        earnings_symbols=[],
    )
    _seed(
        store,
        "techtrade.tune",
        [{"param": "tech-param"}],
        earnings_symbols=[],
    )
    _seed(
        store,
        "techtrade.tune",
        [{"param": "energy-param"}],
        segment="Energy",
        earnings_symbols=[],
    )
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        rows = _client.get("/tt/tuning/report?symbol=NVDA").json()
    assert [row["param"] for row in rows] == ["tech-param"]
    store.close()


def test_export_reads_materialized_plans_not_scan_rows(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "export.db")
    _seed(
        store,
        "techtrade.scan",
        [{"symbol": "SCAN_ONLY"}],
        earnings_symbols=[],
    )
    _seed(
        store,
        "techtrade.plan",
        [{"symbol": "PLAN_ONLY"}],
        earnings_symbols=[],
    )
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        body = _client.get("/tt/scan/export").json()
    assert "PLAN_ONLY" in body
    assert "SCAN_ONLY" not in body
    store.close()


def test_completed_empty_plan_export_is_not_reported_missing(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "empty-export.db")
    _seed(store, "techtrade.plan", [], earnings_symbols=[])
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        body = _client.get("/tt/scan/export").json()
    assert "Latest EOD snapshot completed" in body
    assert "No EOD snapshot available" not in body
    store.close()


def test_tuning_inherits_symbol_scoped_earnings_annotation(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "tuning-earnings.db")
    _seed(
        store,
        "techtrade.scan",
        [{"symbol": "NVDA", "segment": SEGMENT}],
        earnings_symbols=["NVDA"],
    )
    _seed(
        store,
        "techtrade.tune",
        [{"param": "atr_period"}],
        earnings_symbols=[],
    )
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        rows = _client.get("/tt/tuning/report?symbol=NVDA").json()
    assert all(row["earnings_annotation"] == "Reports before next open" for row in rows)
    store.close()


def test_symbol_badge_ignores_unrelated_stale_segment(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "symbol-freshness.db")
    _seed(
        store,
        "techtrade.signals",
        [{"symbol": "NVDA", "direction": "long", "score": 0.8}],
        earnings_symbols=[],
    )
    _seed(
        store,
        "techtrade.signals",
        [{"symbol": "XOM", "direction": "long", "score": 0.4}],
        segment="Energy",
        earnings_symbols=[],
        session=date(2026, 9, 9),
    )
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        body = _client.get("/tt/position/signal-card?symbol=NVDA").json()
    assert "As of 2026-09-11 XNYS close" in body
    store.close()


def test_aggregate_movers_marks_incomplete_sector_coverage(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "partial-coverage.db")
    _seed(store, "techtrade.movers", _rows_by_dataset()["techtrade.movers"])
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        body = _client.get("/tt/scan/segment-movers").json()
    assert body["is_partial"] is True
    assert body["freshness"] == "red"
    assert len(body["missing_segments"]) == 10
    store.close()


def test_excluded_symbol_has_targeted_warning(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "excluded.db")
    payload = {
        "rows": [],
        "segment": SEGMENT,
        "as_of_session": SESSION.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": [],
        "excluded_symbols": ["NVDA"],
        "exclusion_reasons": {"NVDA": "halted"},
        "survivorship": "not-applicable",
    }
    store.stage(
        "techtrade.signals",
        KEY,
        SESSION,
        "excluded",
        payload,
        row_count=0,
        engine_version="test",
        payload_schema_version="1",
    )
    definition = DEFAULT_DATASET_REGISTRY.require("techtrade.signals")
    assert store.validate(
        "techtrade.signals",
        KEY,
        SESSION,
        "excluded",
        lambda row: definition.validator(row, None),
    ).ok
    assert store.promote("techtrade.signals", KEY, SESSION, "excluded")
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=store,
    ):
        body = _client.get("/tt/position/signal-card?symbol=NVDA").json()
    assert "excluded" in body.lower()
    assert "halted" in body.lower()
    store.close()


def test_tuning_lookup_uses_batched_live_reads(monkeypatch) -> None:
    class _BatchStore:
        def __init__(self):
            self.calls = 0

        def get_live(self, *_args):
            raise AssertionError("single-row read used")

        def get_live_many(self, _dataset, _entity_keys):
            self.calls += 1
            return {}

    store = _BatchStore()
    monkeypatch.setattr(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        lambda: store,
    )

    response = _client.get("/tt/tuning/report?symbol=NVDA")

    assert response.status_code == 200
    assert store.calls <= 5
