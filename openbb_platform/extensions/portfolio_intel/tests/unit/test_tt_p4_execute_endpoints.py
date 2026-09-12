"""Tests for T5 P4 widget-backend execute endpoints (#1768)."""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

_client = TestClient(app)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate PI_ALLOW_T5_EXECUTE / PI_PAPER_DB / output dir per-test."""
    monkeypatch.setenv("PI_PAPER_DB", str(tmp_path / "paper.db"))
    monkeypatch.setenv("PI_T5_EXECUTE_OUTPUT_DIR", str(tmp_path / "t5_out"))
    monkeypatch.setenv("PI_T5_EXECUTION_AUDIT_DB", str(tmp_path / "execution-audit.db"))
    monkeypatch.setenv("PI_T5_BROKER_MODE", "paper")
    monkeypatch.setenv("PI_PAPER_ENGINE", "sqlite")
    monkeypatch.delenv("PI_ALLOW_T5_EXECUTE", raising=False)
    monkeypatch.delenv("PI_ALLOW_T5_LIVE", raising=False)


# ---------------------------------------------------------------------------
# tt/execute/write-batch — the triple-gate
# ---------------------------------------------------------------------------


class TestWriteBatchGates:
    def test_env_gate_off_returns_403(self, clean_env) -> None:
        """R7.11 twin: dropping the PI_ALLOW_T5_EXECUTE check turns a
        dev deployment into an auto-executor. The default OFF is the
        load-bearing safety.
        """
        r = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        assert r.status_code == 403
        assert "t5_execute_not_allowed" in str(r.json().get("detail"))

    def test_verdict_fail_returns_400(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """R7.11 twin: without the verdict check, a FAIL verdict silently
        writes anyway. Verified.
        """
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r = _client.post("/tt/execute/write-batch?verdict=FAIL&confirm=yes")
        assert r.status_code == 400
        assert "verdict_gate_blocked" in str(r.json().get("detail"))

    def test_missing_confirm_returns_400(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """R7.11 twin: skipping the explicit confirm check would let a
        page-reload trigger a write. The confirm=yes literal is the
        anti-reload guard.
        """
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r = _client.post("/tt/execute/write-batch?verdict=PASS")
        assert r.status_code == 400
        assert "explicit_confirm_required" in str(r.json().get("detail"))

    def test_wrong_confirm_string_returns_400(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """The literal 'yes' is required — 'true', '1', 'YES' all rejected.

        R7.11 twin: loose comparison here would defeat the explicit
        signal-not-noise design.
        """
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        for bad_confirm in ("true", "1", "YES", "y"):
            r = _client.post(
                f"/tt/execute/write-batch?verdict=PASS&confirm={bad_confirm}"
            )
            assert r.status_code == 400, f"{bad_confirm!r} should have been rejected"


# ---------------------------------------------------------------------------
# tt/execute/write-batch — happy path
# ---------------------------------------------------------------------------


class TestWriteBatchHappyPath:
    def test_returns_batch_sha_and_paths(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """All three gates open → write happens + response shape is right."""
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        assert r.status_code == 200
        body = r.json()
        assert "batch_sha" in body
        assert len(body["batch_sha"]) == 8
        assert "csv_path" in body
        assert "xlsx_path" in body
        assert "order_ids" in body
        assert len(body["order_ids"]) == 3  # demo batch has 3 tickets
        assert "next_step" in body

    def test_files_actually_written_to_disk(
        self, monkeypatch: pytest.MonkeyPatch, clean_env, tmp_path: Path
    ) -> None:
        """R7.11 twin: if PaperOrderSink were replaced by a noop, the
        response would look right but no disk files exist.
        """
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        assert r.status_code == 200
        csv_path = Path(r.json()["csv_path"])
        xlsx_path = Path(r.json()["xlsx_path"])
        assert csv_path.exists()
        assert xlsx_path.exists()

    def test_idempotent_second_write(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """Same demo batch => same SHA. Second call returns same paths."""
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r1 = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        r2 = _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["batch_sha"] == r2.json()["batch_sha"]
        assert r1.json()["csv_path"] == r2.json()["csv_path"]


# ---------------------------------------------------------------------------
# tt/execute/paper-status
# ---------------------------------------------------------------------------


class TestPaperStatus:
    def test_empty_state_when_db_missing(self, clean_env) -> None:
        """Fresh install: no paper.db yet → empty snapshot, not error.

        R7.11 twin: raising on missing DB would make the widget crash
        every first load — the empty snapshot IS the correct "fresh
        install" signal.
        """
        r = _client.get("/tt/execute/paper-status")
        assert r.status_code == 200
        body = r.json()
        assert body["account"] is None
        assert body["positions"] == []
        assert body["pending_order_count"] == 0
        assert body["filled_order_count"] == 0

    def test_reports_state_after_write_batch(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """After a submit_batch, status endpoint reports the PENDING orders."""
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        r = _client.get("/tt/execute/paper-status")
        assert r.status_code == 200
        body = r.json()
        assert body["account"] is not None
        assert body["pending_order_count"] == 3
        assert body["filled_order_count"] == 0

    def test_paper_status_does_not_need_env_gate(self, clean_env) -> None:
        """Read-only endpoint. R7.11 twin: gating reads behind
        PI_ALLOW_T5_EXECUTE would break the widget's default view.
        """
        # Without PI_ALLOW_T5_EXECUTE
        r = _client.get("/tt/execute/paper-status")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    def test_new_p4_routes_registered(self) -> None:
        routes = {r.path for r in app.routes}
        assert "/tt/execute/write-batch" in routes
        assert "/tt/execute/cancel" in routes
        assert "/tt/execute/paper-status" in routes
