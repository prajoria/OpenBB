"""Techtrade Morning Scan tab tests (#1692 T13.1, #1940, #1941).

Ships 3 read widgets under the tt_ prefix (techtrade) in the existing
portfolio_intel widget_backend server (Option A architecture):

- **tt_segment_movers** — chart+bar top gainers/losers by segment
- **tt_scan_table** — table of filtered ticker scan results
- **tt_export_button** — markdown-link widget for CSV export

Also verifies:
- The new "techtrade-desk" app entry exists in apps.json with a Morning
  Scan tab (T1 = first techtrade tab).
- ``POST /tt/scan/trigger`` enqueues a job and returns 202 without
  executing any scan handler.
- Populated and empty endpoint latency stays below 500 ms.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from openbb_techtrade.snapshot.store import (  # noqa: E402
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
)

def _snapshot(dataset: str, segment: str, rows: list[dict]) -> SnapshotRow:
    session = date(2026, 9, 11)
    return SnapshotRow(
        dataset=dataset,
        entity_key=f"segment={segment.casefold()}",
        as_of_session=session,
        created_at=datetime(2026, 9, 11, 22, 0, tzinfo=timezone.utc),
        job_run_id=f"{dataset}-{segment}",
        status=SnapshotStatus.OK,
        state=SnapshotState.LIVE,
        validated=True,
        payload_schema_version="1",
        payload={
            "rows": rows,
            "segment": segment,
            "as_of_session": session.isoformat(),
            "exchange_calendar": "XNYS",
            "earnings_symbols": [],
            "excluded_symbols": [],
            "survivorship": "not-applicable",
        },
    )


_TECHNOLOGY_MOVERS = _snapshot(
    "techtrade.movers",
    "Information Technology",
    [
        {
            "symbol": "NVDA",
            "segment": "Information Technology",
            "pct_change": 4.2,
        }
    ],
)
_TECHNOLOGY_SCAN = _snapshot(
    "techtrade.scan",
    "Information Technology",
    [
        {
            "symbol": "NVDA",
            "segment": "Information Technology",
            "score": 0.94,
            "direction": "long",
        },
        {
            "symbol": "AAPL",
            "segment": "Information Technology",
            "score": 0.82,
            "direction": "long",
        },
    ],
)
_COMMUNICATION_MOVERS = _snapshot(
    "techtrade.movers",
    "Communication Services",
    [
        {
            "symbol": "META",
            "segment": "Communication Services",
            "pct_change": -3.1,
        }
    ],
)
_EMPTY_HEALTH_CARE_SCAN = _snapshot("techtrade.scan", "Health Care", [])


class _FakeStore:
    """In-memory fake implementing the generic LIVE-read protocol."""

    def __init__(
        self, snapshots: dict[tuple[str, str], SnapshotRow] | None = None
    ):
        self._snapshots = snapshots or {}

    def get_live(self, dataset: str, entity_key: str) -> SnapshotRow | None:
        return self._snapshots.get((dataset, entity_key))


# Build a populated and an empty store for reuse.
_populated_store = _FakeStore(
    {
        (
            "techtrade.movers",
            "segment=information technology",
        ): _TECHNOLOGY_MOVERS,
        (
            "techtrade.movers",
            "segment=communication services",
        ): _COMMUNICATION_MOVERS,
        ("techtrade.scan", "segment=information technology"): _TECHNOLOGY_SCAN,
        ("techtrade.scan", "segment=health care"): _EMPTY_HEALTH_CARE_SCAN,
    }
)
_empty_store = _FakeStore()

from fastapi.testclient import TestClient  # noqa: E402

# Import the app (import triggers endpoint registration).
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

_client = TestClient(app)

_MANIFEST_DIR = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)


def _widgets() -> dict:
    return json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8"))


def _apps() -> list:
    apps = json.loads((_MANIFEST_DIR / "apps.json").read_text(encoding="utf-8"))
    return apps if isinstance(apps, list) else list(apps.values())


def _techtrade_app() -> dict:
    for a in _apps():
        if a.get("id") == "techtrade-desk":
            return a
    return {}


# ---------------------------------------------------------------------------
# Widget manifest declarations
# ---------------------------------------------------------------------------


def test_tt_segment_movers_widget_declared() -> None:
    """The segment movers widget remains in the manifest."""
    w = _widgets().get("tt_segment_movers")
    assert w and w["type"] == "chart"
    assert w["endpoint"] == "tt/scan/segment-movers"
    assert w["dataKey"] == "rows"


def test_tt_scan_table_widget_declared() -> None:
    """The scan table widget remains in the manifest."""
    w = _widgets().get("tt_scan_table")
    assert w and w["type"] == "table"
    assert w["endpoint"] == "tt/scan/table"
    assert w["dataKey"] == "rows"


def test_tt_export_button_widget_declared() -> None:
    """The export widget remains in the manifest."""
    w = _widgets().get("tt_export_button")
    assert w and w["type"] == "markdown"
    assert w["endpoint"] == "tt/scan/export"


# ---------------------------------------------------------------------------
# Endpoint shape — populated store
# ---------------------------------------------------------------------------


def test_segment_movers_shape() -> None:
    """Segment movers rows carry segment + change_pct + bucket."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        r = _client.get("/tt/scan/segment-movers")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body
    assert "computed_at" in body
    assert "as_of_session" in body
    assert "is_stale" in body
    rows = body["rows"]
    assert rows
    for row in rows:
        assert "segment" in row
        assert "change_pct" in row
        assert "bucket" in row
        assert row["bucket"] in ("gainer", "loser")


def test_scan_table_shape() -> None:
    """Scan-table rows carry the persisted symbol, score, and direction fields."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        r = _client.get("/tt/scan/table")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body
    assert "computed_at" in body
    rows = body["rows"]
    assert rows
    for row in rows:
        assert "symbol" in row
        assert "score" in row
        assert "direction" in row


def test_scan_table_accepts_segment_filter() -> None:
    """/tt/scan/table?segment=Information Technology filters rows."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        r = _client.get("/tt/scan/table?segment=Information%20Technology")
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    assert rows
    for row in rows:
        assert row.get("segment") == "Information Technology"


def test_scan_table_distinguishes_fresh_segment_without_matches() -> None:
    """An empty persisted segment does not claim that no scan has run."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        response = _client.get("/tt/scan/table?segment=Health%20Care")
    body = response.json()
    assert body["computed_at"] is not None
    assert "latest scan completed" in body["rows"][0]["note"].lower()
    assert "run a scan first" not in body["rows"][0]["note"].lower()


def test_scan_table_rejects_malformed_segment() -> None:
    """Segment must be an allowlisted string; reject XSS."""
    r = _client.get("/tt/scan/table?segment=<script>")
    assert r.status_code == 400


def test_export_button_returns_markdown() -> None:
    """Export widget returns a markdown link + guidance."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        r = _client.get("/tt/scan/export")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, str)
    assert "csv" in body.lower() or "export" in body.lower()


# ---------------------------------------------------------------------------
# Loud-empty behaviour — empty store
# ---------------------------------------------------------------------------


def test_segment_movers_empty_loud() -> None:
    """When no snapshot exists, response rows contain a loud-empty note."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_empty_store,
    ):
        r = _client.get("/tt/scan/segment-movers")
    assert r.status_code == 200
    body = r.json()
    assert body["computed_at"] is None
    assert body["is_stale"] is True
    assert any(
        "no eod snapshot" in str(row.get("note", "")).lower() for row in body["rows"]
    )


def test_scan_table_empty_loud() -> None:
    """When no snapshot exists, response rows contain a loud-empty note."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_empty_store,
    ):
        r = _client.get("/tt/scan/table")
    assert r.status_code == 200
    body = r.json()
    assert body["computed_at"] is None
    assert body["is_stale"] is True
    assert any(
        "no eod snapshot" in str(row.get("note", "")).lower() for row in body["rows"]
    )


def test_export_empty_loud() -> None:
    """When no snapshot exists, export returns guidance markdown."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_empty_store,
    ):
        r = _client.get("/tt/scan/export")
    assert r.status_code == 200
    body = r.json()
    assert "no eod snapshot" in body.lower()


# ---------------------------------------------------------------------------
# Metadata fields
# ---------------------------------------------------------------------------


def test_computed_at_and_as_of_session_present() -> None:
    """All scan endpoints expose computed_at + as_of_session + is_stale."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        for path in ("/tt/scan/segment-movers", "/tt/scan/table"):
            r = _client.get(path)
            body = r.json()
            assert body["computed_at"] is not None
            assert body["as_of_session"] is not None
            assert isinstance(body["is_stale"], bool)


# ---------------------------------------------------------------------------
# POST /tt/scan/trigger — enqueue only, never execute
# ---------------------------------------------------------------------------


def test_trigger_returns_202_and_does_not_execute() -> None:
    """POST /tt/scan/trigger enqueues a job but never calls scan_segments."""
    mock_run = MagicMock()
    mock_run.run_id = "test-run-id"
    mock_run.job_name = "techtrade.eod_snapshots"

    mock_service = MagicMock()
    mock_service.enqueue.return_value = mock_run

    with (
        patch(
            "openbb_portfolio_intel.widget_backend.widgets_endpoints.get_job_service",
            return_value=mock_service,
            create=True,
        ),
        patch(
            "openbb_core.api.dependency.jobs.get_job_service",
            return_value=mock_service,
        ),
    ):
        r = _client.post("/tt/scan/trigger")

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "accepted"
    assert body["run_id"] == "test-run-id"
    # Confirm enqueue was called, not any handler.
    mock_service.enqueue.assert_called_once_with(
        "techtrade.eod_snapshots",
        {"datasets": ["techtrade.movers", "techtrade.scan"]},
    )


def test_trigger_requires_auth() -> None:
    """POST /tt/scan/trigger must be authenticated (respects loopback-dev in tests)."""
    routes = {r.path for r in app.routes}
    assert "/tt/scan/trigger" in routes


# ---------------------------------------------------------------------------
# Latency contract — populated and empty under 500 ms
# ---------------------------------------------------------------------------

_LATENCY_THRESHOLD_S = 0.5


def test_populated_endpoint_latency() -> None:
    """Populated scan table and segment-movers respond in < 500 ms."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_populated_store,
    ):
        for path in ("/tt/scan/segment-movers", "/tt/scan/table"):
            start = time.perf_counter()
            r = _client.get(path)
            elapsed = time.perf_counter() - start
            assert r.status_code == 200
            assert (
                elapsed < _LATENCY_THRESHOLD_S
            ), f"{path} took {elapsed:.3f}s (> {_LATENCY_THRESHOLD_S}s)"


def test_empty_endpoint_latency() -> None:
    """Empty scan table and segment-movers respond in < 500 ms."""
    with patch(
        "openbb_portfolio_intel.widget_backend.widgets_endpoints._get_snapshot_store",
        return_value=_empty_store,
    ):
        for path in ("/tt/scan/segment-movers", "/tt/scan/table"):
            start = time.perf_counter()
            r = _client.get(path)
            elapsed = time.perf_counter() - start
            assert r.status_code == 200
            assert (
                elapsed < _LATENCY_THRESHOLD_S
            ), f"{path} took {elapsed:.3f}s (> {_LATENCY_THRESHOLD_S}s)"


# ---------------------------------------------------------------------------
# techtrade-desk app entry + Morning Scan tab
# ---------------------------------------------------------------------------


def test_techtrade_desk_app_declared() -> None:
    """techtrade-desk app must exist in apps.json alongside the terminal."""
    a = _techtrade_app()
    assert a, "techtrade-desk app entry missing from apps.json"


def test_techtrade_desk_has_morning_scan_tab() -> None:
    """T1 Morning Scan tab must exist with the 3 widgets."""
    a = _techtrade_app()
    tabs = a.get("tabs", {})
    scan_tab = tabs.get("morning-scan") or tabs.get("morning_scan")
    assert scan_tab, f"Morning Scan tab missing; got tabs {list(tabs)!r}"
    ids = {slot["i"] for slot in scan_tab["layout"]}
    for wid in ("tt_segment_movers", "tt_scan_table", "tt_export_button"):
        assert wid in ids, f"tab missing {wid}; got {ids!r}"


# ---------------------------------------------------------------------------
# Route parity — Workspace 404 guard
# ---------------------------------------------------------------------------


def test_all_tt_endpoints_registered() -> None:
    """All Morning Scan routes, including trigger, are registered."""
    routes = {r.path for r in app.routes}
    for path in (
        "/tt/scan/segment-movers",
        "/tt/scan/table",
        "/tt/scan/export",
        "/tt/scan/trigger",
    ):
        assert path in routes, f"missing route {path}"
