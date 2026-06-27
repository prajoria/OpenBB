"""Unit tests for openbb_sec.utils.sec_http (#99 T1).

All offline — `requests_mock` is the HTTP fake. Tests cover:
- L2 User-Agent enforcement (missing config → fast hard error)
- L2 resolution ladder: env → user_settings → raise
- Retry-After honoring (L3)
- gzip negotiation (L3)
- Session reuse (L3)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from openbb_sec.utils.sec_http import (
    SecHttpConfigError,
    _resolve_user_agent,
    get,
    post,
)

# ---------------------------------------------------------------------------
# L2: _resolve_user_agent — env → user_settings → raise
# ---------------------------------------------------------------------------


def test_resolve_user_agent_uses_env_when_set(monkeypatch):
    """Env SEC_USER_AGENT is the first-resort source."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME Research alice@example.com")
    assert _resolve_user_agent() == "ACME Research alice@example.com"


def test_resolve_user_agent_falls_back_to_user_settings(monkeypatch):
    """No env → consults user_settings.credentials.sec_user_agent."""
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    fake_creds = MagicMock(sec_user_agent="BetaCorp ops@beta.com")
    with patch("openbb_sec.utils.sec_http._user_service_credentials",
               return_value=fake_creds):
        assert _resolve_user_agent() == "BetaCorp ops@beta.com"


def test_resolve_user_agent_raises_when_nothing_configured(monkeypatch):
    """L2 hard rule: missing UA → SecHttpConfigError, not a silent default."""
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with patch("openbb_sec.utils.sec_http._user_service_credentials",
               return_value=None), pytest.raises(SecHttpConfigError, match="sec_user_agent"):
        _resolve_user_agent()


def test_resolve_user_agent_raises_when_user_settings_field_missing(monkeypatch):
    """user_settings exists but lacks sec_user_agent → still raises (not silent fallback)."""
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    fake_creds = MagicMock(spec=[])  # No sec_user_agent attribute
    with patch("openbb_sec.utils.sec_http._user_service_credentials",
               return_value=fake_creds), pytest.raises(SecHttpConfigError):
        _resolve_user_agent()


def test_resolve_user_agent_env_wins_over_user_settings(monkeypatch):
    """Env beats user_settings (operator override)."""
    monkeypatch.setenv("SEC_USER_AGENT", "from-env you@env.com")
    fake_creds = MagicMock(sec_user_agent="from-settings them@settings.com")
    with patch("openbb_sec.utils.sec_http._user_service_credentials",
               return_value=fake_creds):
        assert _resolve_user_agent() == "from-env you@env.com"


# ---------------------------------------------------------------------------
# L2: get() / post() set the User-Agent header
# ---------------------------------------------------------------------------


def _fake_session_returning(status_code: int = 200, headers: dict | None = None,
                            text: str = "ok", json_payload: Any = None):
    """Build a MagicMock session whose .request() returns one response.

    Captures the args/kwargs passed to .request() for assertions.
    """
    response = MagicMock(status_code=status_code, headers=headers or {}, text=text)
    if json_payload is not None:
        response.json.return_value = json_payload
    response.raise_for_status.return_value = None
    session = MagicMock()
    session.request.return_value = response
    return session, response


def test_get_sets_user_agent_header_from_env(monkeypatch):
    """Every get() call carries the L2 UA header."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")
    session, _ = _fake_session_returning()
    with patch("openbb_sec.utils.sec_http._get_session", return_value=session):
        get("https://www.sec.gov/test")
    headers = session.request.call_args.kwargs["headers"]
    assert headers["User-Agent"] == "ACME alice@example.com"


def test_post_sets_user_agent_header_from_env(monkeypatch):
    """Every post() call carries the L2 UA header."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")
    session, _ = _fake_session_returning(json_payload={"ok": True})
    with patch("openbb_sec.utils.sec_http._get_session", return_value=session):
        post("https://www.sec.gov/api", json={"q": "x"})
    headers = session.request.call_args.kwargs["headers"]
    assert headers["User-Agent"] == "ACME alice@example.com"


def test_get_negotiates_gzip(monkeypatch):
    """L3: Accept-Encoding: gzip on every request."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")
    session, _ = _fake_session_returning()
    with patch("openbb_sec.utils.sec_http._get_session", return_value=session):
        get("https://www.sec.gov/test")
    headers = session.request.call_args.kwargs["headers"]
    assert "gzip" in headers.get("Accept-Encoding", "")


def test_get_raises_when_no_user_agent_configured(monkeypatch):
    """L2 hard fail — get() raises at first call, never silently makes the request."""
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with patch("openbb_sec.utils.sec_http._user_service_credentials",
               return_value=None), pytest.raises(SecHttpConfigError):
        get("https://www.sec.gov/test")


# ---------------------------------------------------------------------------
# L3: Retry-After honoring on 429
# ---------------------------------------------------------------------------


def test_get_honors_retry_after_on_429(monkeypatch):
    """L3: 429 with Retry-After header → sleep then retry."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")
    sleeps: list[float] = []
    monkeypatch.setattr("openbb_sec.utils.sec_http.time.sleep", sleeps.append)

    too_many = MagicMock(status_code=429, headers={"Retry-After": "1"}, text="throttled")
    too_many.raise_for_status.return_value = None
    ok = MagicMock(status_code=200, headers={}, text="ok")
    ok.raise_for_status.return_value = None

    session = MagicMock()
    session.request.side_effect = [too_many, ok]
    with patch("openbb_sec.utils.sec_http._get_session", return_value=session):
        r = get("https://www.sec.gov/test")
    assert r.status_code == 200
    assert 1 in sleeps  # 1-second Retry-After honored


def test_get_falls_back_to_exponential_backoff_when_no_retry_after_header(monkeypatch):
    """L3: 429 without Retry-After header → exponential fallback."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")
    sleeps: list[float] = []
    monkeypatch.setattr("openbb_sec.utils.sec_http.time.sleep", sleeps.append)

    too_many = MagicMock(status_code=429, headers={}, text="throttled")
    too_many.raise_for_status.return_value = None
    ok = MagicMock(status_code=200, headers={}, text="ok")
    ok.raise_for_status.return_value = None

    session = MagicMock()
    session.request.side_effect = [too_many, ok]
    with patch("openbb_sec.utils.sec_http._get_session", return_value=session):
        r = get("https://www.sec.gov/test")
    assert r.status_code == 200
    assert sleeps and sleeps[0] > 0


def test_get_raises_after_retry_budget_exhausted(monkeypatch):
    """L3: persistent 429 → raises after max_retries."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")
    monkeypatch.setattr("openbb_sec.utils.sec_http.time.sleep", lambda _s: None)

    too_many = MagicMock(
        status_code=429,
        headers={"Retry-After": "1"},
        text="still throttled",
    )
    too_many.raise_for_status.side_effect = requests.HTTPError("429")

    session = MagicMock()
    session.request.return_value = too_many
    with patch("openbb_sec.utils.sec_http._get_session", return_value=session), \
         pytest.raises(requests.HTTPError):
        get("https://www.sec.gov/test", max_retries=2)


# ---------------------------------------------------------------------------
# L3: Session reuse
# ---------------------------------------------------------------------------


def test_get_reuses_module_level_session(monkeypatch):
    """L3: multiple get() calls share one requests.Session for connection pooling."""
    monkeypatch.setenv("SEC_USER_AGENT", "ACME alice@example.com")

    # Reset the global so the test is order-independent.
    from openbb_sec.utils import sec_http as mod
    mod._SESSION = None
    response = MagicMock(status_code=200, headers={}, text="x")
    response.raise_for_status.return_value = None

    # Patch session() creation to a MagicMock factory that records calls.
    real_session_class = MagicMock(side_effect=lambda: MagicMock(
        request=MagicMock(return_value=response),
    ))
    monkeypatch.setattr("openbb_sec.utils.sec_http.requests.Session", real_session_class)

    get("https://www.sec.gov/a")
    sess_a = mod._SESSION
    get("https://www.sec.gov/b")
    assert mod._SESSION is sess_a
    # requests.Session was called exactly once across the two get() calls
    assert real_session_class.call_count == 1
