"""Tests for scrape_record.yahoo_query1 (fast-path client)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from scrape_record.yahoo_query1 import (
    SESSION_TTL,
    Query1Error,
    Query1Session,
    fetch_quote_summary,
    session_cache_path,
)


class _FakeCfg:
    """Config double — only needs a profile_dir with a parent."""

    def __init__(self, tmp_path):
        self.profile_dir = tmp_path / "chrome_profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)


def test_session_expiry_boundary(tmp_path):
    """Sessions fresh<TTL are not expired; stale>TTL are."""
    now = datetime.now(timezone.utc)
    fresh = Query1Session(
        crumb="abc",
        cookies={"A1": "x"},
        user_agent="UA",
        issued_at=now.isoformat(),
    )
    assert fresh.is_expired() is False
    stale = Query1Session(
        crumb="abc",
        cookies={"A1": "x"},
        user_agent="UA",
        issued_at=(now - SESSION_TTL - timedelta(minutes=1)).isoformat(),
    )
    assert stale.is_expired() is True


def test_session_expiry_malformed_timestamp():
    """Malformed issued_at is treated as expired (safe default)."""
    sess = Query1Session(crumb="c", cookies={}, user_agent="u", issued_at="not-iso")
    assert sess.is_expired() is True


def test_session_cache_path_lives_beside_profile(tmp_path):
    """Cache path is sibling of profile_dir under the parent."""
    cfg = _FakeCfg(tmp_path)
    p = session_cache_path(cfg)
    assert p.parent == tmp_path
    assert p.name == "session.json"


def _write_cached(tmp_path, minutes_ago=1):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    (tmp_path / "session.json").write_text(
        json.dumps(
            {
                "crumb": "TEST_CRUMB",
                "cookies": {"A1": "test-a1", "A3": "test-a3"},
                "user_agent": "TestAgent/1.0",
                "issued_at": ts,
                "source": "test",
            }
        ),
        encoding="utf-8",
    )


class _FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body
        self.text = json.dumps(json_body)

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, follow_redirects=True):
        self.calls.append(url)
        return self._responses.pop(0)


def test_fetch_quote_summary_success_uses_cache(tmp_path):
    """Cached session drives an httpx call with crumb; returns parsed JSON."""
    cfg = _FakeCfg(tmp_path)
    _write_cached(tmp_path)
    fake = _FakeClient(
        [
            _FakeResponse(
                200,
                {
                    "quoteSummary": {
                        "result": [{"price": {"symbol": "MSFT"}}],
                        "error": None,
                    }
                },
            )
        ]
    )
    with patch("httpx.Client", return_value=fake):
        data = fetch_quote_summary(cfg, "MSFT", "price")
    assert data["quoteSummary"]["result"][0]["price"]["symbol"] == "MSFT"
    assert "TEST_CRUMB" in fake.calls[0]
    assert "MSFT" in fake.calls[0]


def test_fetch_quote_summary_raises_on_missing_quotesummary(tmp_path):
    """Payload without a 'quoteSummary' key raises Query1Error."""
    cfg = _FakeCfg(tmp_path)
    _write_cached(tmp_path)
    fake = _FakeClient(
        [_FakeResponse(200, {"finance": {"error": {"code": "UnexpectedShape"}}})]
    )
    with patch("httpx.Client", return_value=fake), pytest.raises(
        Query1Error, match="missing quoteSummary"
    ):
        fetch_quote_summary(cfg, "MSFT", "price")


def test_fetch_quote_summary_raises_on_empty_result(tmp_path):
    """quoteSummary.result=[] raises Query1Error (loud-empty)."""
    cfg = _FakeCfg(tmp_path)
    _write_cached(tmp_path)
    fake = _FakeClient(
        [_FakeResponse(200, {"quoteSummary": {"result": [], "error": None}})]
    )
    with patch("httpx.Client", return_value=fake), pytest.raises(
        Query1Error, match="result empty"
    ):
        fetch_quote_summary(cfg, "MSFT", "price")


def test_fetch_quote_summary_raises_on_non_200(tmp_path):
    """Non-200 status raises Query1Error immediately, no retry."""
    cfg = _FakeCfg(tmp_path)
    _write_cached(tmp_path)
    fake = _FakeClient([_FakeResponse(500, {"error": "server"})])
    with patch("httpx.Client", return_value=fake), pytest.raises(
        Query1Error, match="non-200"
    ):
        fetch_quote_summary(cfg, "MSFT", "price")


def test_fetch_quote_summary_retries_on_401_then_raises(tmp_path):
    """401 triggers session refresh; still-401 after retries raises."""
    cfg = _FakeCfg(tmp_path)
    _write_cached(tmp_path)
    # Both attempts return 401 -> exhausted retries.
    fake = _FakeClient([_FakeResponse(401, {}), _FakeResponse(401, {})])

    # Patch _seed_via_playwright so retry doesn't launch a real browser.
    async def _fake_seed(cfg_, target_symbol="MSFT"):
        return Query1Session(
            crumb="RETRIED_CRUMB",
            cookies={},
            user_agent="UA",
            issued_at=datetime.now(timezone.utc).isoformat(),
        )

    with patch("httpx.Client", return_value=fake), patch(
        "scrape_record.yahoo_query1._seed_via_playwright", _fake_seed
    ), pytest.raises(Query1Error, match="exhausted retries"):
        fetch_quote_summary(cfg, "MSFT", "price")
    assert len(fake.calls) == 2
