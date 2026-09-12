"""Compute-free TechTrade widget reads from the canonical EOD snapshot store."""

from __future__ import annotations

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
        "techtrade.simulate": [
            {"symbol": "NVDA", "day": 1, "pnl": 12.5}
        ],
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
                "event": "replayed",
            }
        ],
    }


def _seed(store: SqliteSnapshotStore, dataset: str, rows: list[dict]) -> None:
    payload = {
        "rows": rows,
        "segment": SEGMENT,
        "as_of_session": SESSION.isoformat(),
        "exchange_calendar": "XNYS",
        "earnings_symbols": ["NVDA"],
        "excluded_symbols": [],
        "survivorship": (
            SURVIVORSHIP_UNCORRECTED
            if dataset in {"techtrade.validate", "techtrade.tune", "techtrade.audit"}
            else "not-applicable"
        ),
        "universe_membership": [],
    }
    run_id = dataset.replace(".", "-")
    store.stage(
        dataset,
        KEY,
        SESSION,
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
        KEY,
        SESSION,
        run_id,
        lambda row: definition.validator(row, None),
    ).ok
    assert store.promote(dataset, KEY, SESSION, run_id)


def _seeded_store(tmp_path: Path) -> SqliteSnapshotStore:
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    for dataset, rows in _rows_by_dataset().items():
        _seed(store, dataset, rows)
    return store


def test_all_snapshot_widgets_render_seeded_content_without_compute(
    tmp_path: Path, monkeypatch
) -> None:
    store = _seeded_store(tmp_path)
    monkeypatch.setattr(
        "openbb_techtrade.engine.movers.list_movers",
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
            assert all(
                row["survivorship"] == SURVIVORSHIP_UNCORRECTED for row in rows
            )
    store.close()


def test_every_registered_dataset_has_a_seed_fixture() -> None:
    assert tuple(_rows_by_dataset()) == TECHTRADE_DATASETS
