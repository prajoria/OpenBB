"""Tests for T5 P4 widget frontend rewrite (#1777)."""

# ruff: noqa: D101, D102, D103, D105

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

from fastapi.testclient import TestClient  # noqa: E402
from openbb_portfolio_intel.widget_backend.main import app  # noqa: E402

_client = TestClient(app)

_MANIFEST_DIR = (
    Path(__file__).resolve().parents[2] / "openbb_portfolio_intel" / "widget_backend"
)


def _widgets() -> dict:
    return json.loads((_MANIFEST_DIR / "widgets.json").read_text(encoding="utf-8"))


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PI_PAPER_DB", str(tmp_path / "paper.db"))
    monkeypatch.setenv("PI_T5_EXECUTE_OUTPUT_DIR", str(tmp_path / "t5_out"))
    monkeypatch.delenv("PI_ALLOW_T5_EXECUTE", raising=False)


# ---------------------------------------------------------------------------
# tt_execute_bridge — updated markdown output
# ---------------------------------------------------------------------------


class TestExecuteBridgeMarkdown:
    def test_pass_verdict_shows_write_batch_next_step(self, clean_env) -> None:
        """R7.11 twin: without the "write-batch" next-step link, the widget
        would still say READY but give the operator no path forward.
        """
        r = _client.get("/tt/execute/bridge?verdict=PASS")
        assert r.status_code == 200
        body = r.json()  # markdown endpoint returns json-string
        assert "write-batch" in body
        assert "confirm=yes" in body
        assert "PI_ALLOW_T5_EXECUTE" in body

    def test_pass_verdict_shows_env_var_status(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """Env var status must appear so the operator knows whether writes
        are enabled.
        """
        r = _client.get("/tt/execute/bridge?verdict=PASS")
        body = r.json()
        assert "DISABLED" in body or "🟡" in body

        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        r = _client.get("/tt/execute/bridge?verdict=PASS")
        body = r.json()
        assert "ENABLED" in body or "🟢" in body

    def test_fail_verdict_still_blocks(self, clean_env) -> None:
        """R7.11 twin: FAIL verdict must still show BLOCKED — the semantic
        gate can't regress.
        """
        r = _client.get("/tt/execute/bridge?verdict=FAIL")
        assert r.status_code == 200
        body = r.json()
        assert "BLOCKED" in body

    def test_invalid_verdict_still_400s(self, clean_env) -> None:
        r = _client.get("/tt/execute/bridge?verdict=MAYBE")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# tt_execute_paper_status_markdown
# ---------------------------------------------------------------------------


class TestPaperStatusMarkdown:
    def test_no_db_shows_friendly_empty_state(self, clean_env) -> None:
        """R7.11 twin: raising on missing DB would make the widget crash
        every fresh install.
        """
        r = _client.get("/tt/execute/paper-status/markdown")
        assert r.status_code == 200
        body = r.json()
        assert "Paper Trading Engine" in body
        assert "No batches submitted yet" in body

    def test_after_batch_shows_state(
        self, monkeypatch: pytest.MonkeyPatch, clean_env
    ) -> None:
        """After a batch, the markdown includes the cash + positions header."""
        monkeypatch.setenv("PI_ALLOW_T5_EXECUTE", "true")
        _client.post("/tt/execute/write-batch?verdict=PASS&confirm=yes")
        r = _client.get("/tt/execute/paper-status/markdown")
        assert r.status_code == 200
        body = r.json()
        assert "Cash" in body
        # After a submit_batch (no fills yet), positions is empty
        # so the "No open positions." fallback text appears.
        assert "PENDING" in body


# ---------------------------------------------------------------------------
# widgets.json manifest updates
# ---------------------------------------------------------------------------


class TestWidgetsJson:
    def test_bridge_description_updated(self) -> None:
        """R7.11 twin: reverting the description string here would surface
        the old '#1700 scaffold' text in the widget catalog.
        """
        w = _widgets().get("tt_execute_bridge")
        assert w is not None
        assert "#1719 P4" in w["description"]

    def test_new_paper_status_widget_declared(self) -> None:
        w = _widgets().get("tt_execute_paper_status")
        assert w is not None
        assert w["type"] == "markdown"
        assert w["endpoint"] == "tt/execute/paper-status/markdown"

    def test_new_route_registered(self) -> None:
        routes = {r.path for r in app.routes}
        assert "/tt/execute/paper-status/markdown" in routes
