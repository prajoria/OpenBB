"""Unit tests for core/state_store.py (P3.0 / D6).

Verifies the resilience contract + typed-wrapper safety:

  1. Round-trip: save then load returns identical payload
  2. Absent key returns None
  3. Scope isolation: save at scope=a doesn't touch scope=b
  4. UPSERT SQL contract: writes hit fmp_trading_state with the right params
  5. DB failure on load returns None (never raises)
  6. DB failure on save doesn't raise (best-effort)
  7. A7: non-DB exceptions (TypeError) PROPAGATE — never swallowed
  8. A8: load_last_plan on corrupt payload returns None + logs

DB access is mocked via ``unittest.mock.patch`` targeting the canonical
location in ``openbb_fmp_cached.utils.database`` — same pattern the P2.2
TTL-wrapper tests established. No live MySQL needed; runs in ~30ms.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# 1. Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_save_then_load_returns_identical_payload(self):
        from openbb_fmp_trading.core.state_store import load_state, save_state

        captured: dict = {}

        def _fake_upsert(sql, params_list):
            captured["upsert_params"] = params_list

        def _fake_select(sql, params):
            if "upsert_params" not in captured:
                return []
            # Row shape mirrors what fmp_cached's execute_query returns:
            # a list of dicts. The payload column is stored as JSON text.
            payload_json = captured["upsert_params"][0][2]
            return [{"payload": payload_json}]

        payload = {"bar": 1, "baz": [2, 3], "nested": {"a": "b"}}
        with patch(
            "openbb_fmp_cached.utils.database.execute_many",
            side_effect=_fake_upsert,
        ), patch(
            "openbb_fmp_cached.utils.database.execute_query",
            side_effect=_fake_select,
        ):
            save_state("foo", payload)
            result = load_state("foo")

        assert result == payload


# ---------------------------------------------------------------------------
# 2. Absent key
# ---------------------------------------------------------------------------


class TestAbsentKey:
    def test_load_absent_key_returns_none(self):
        from openbb_fmp_trading.core.state_store import load_state

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=[],
        ):
            assert load_state("never-set") is None


# ---------------------------------------------------------------------------
# 3. Scope isolation
# ---------------------------------------------------------------------------


class TestScopeIsolation:
    def test_different_scopes_get_different_params(self):
        from openbb_fmp_trading.core.state_store import save_state

        captured: list = []

        def _fake_upsert(sql, params_list):
            captured.append(params_list)

        with patch(
            "openbb_fmp_cached.utils.database.execute_many",
            side_effect=_fake_upsert,
        ):
            save_state("k", 1, scope="a")
            save_state("k", 2, scope="b")

        assert captured[0][0][1] == "a"  # (key, scope, payload) -> scope at index 1
        assert captured[1][0][1] == "b"


# ---------------------------------------------------------------------------
# 4. UPSERT SQL contract
# ---------------------------------------------------------------------------


class TestUpsertContract:
    def test_save_calls_execute_many_with_upsert_sql(self):
        from openbb_fmp_trading.core.state_store import save_state

        captured: dict = {}

        def _fake_upsert(sql, params_list):
            captured["sql"] = sql
            captured["params"] = params_list

        with patch(
            "openbb_fmp_cached.utils.database.execute_many",
            side_effect=_fake_upsert,
        ):
            save_state("foo", {"bar": 1})

        # SQL contract: INSERT ... ON DUPLICATE KEY UPDATE to fmp_trading_state
        assert "INSERT INTO fmp_trading_state" in captured["sql"]
        assert "ON DUPLICATE KEY UPDATE" in captured["sql"]

        # Params contract: single row of (state_key, scope, payload_json)
        assert len(captured["params"]) == 1
        key, scope, payload_json = captured["params"][0]
        assert key == "foo"
        assert scope == "default"
        assert json.loads(payload_json) == {"bar": 1}


# ---------------------------------------------------------------------------
# 5-6. DB failure degrades gracefully
# ---------------------------------------------------------------------------


class TestDBFailureDegrades:
    def test_load_on_db_failure_returns_none(self):
        """SELECT that raises pymysql.MySQLError returns None, never raises."""
        import pymysql

        from openbb_fmp_trading.core.state_store import load_state

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            side_effect=pymysql.MySQLError("connection lost"),
        ):
            assert load_state("foo") is None

    def test_load_on_connection_error_returns_none(self):
        """A bare ConnectionError (e.g. DNS failure) is also caught."""
        from openbb_fmp_trading.core.state_store import load_state

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            side_effect=ConnectionError("network unreachable"),
        ):
            assert load_state("foo") is None

    def test_save_on_db_failure_does_not_raise(self):
        """UPSERT that raises pymysql.MySQLError is suppressed (best-effort)."""
        import pymysql

        from openbb_fmp_trading.core.state_store import save_state

        with patch(
            "openbb_fmp_cached.utils.database.execute_many",
            side_effect=pymysql.MySQLError("connection lost mid-write"),
        ):
            # Must NOT raise — caller continues with in-memory value
            save_state("foo", {"bar": 1})


# ---------------------------------------------------------------------------
# 7. A7 — narrow except: bugs propagate, don't masquerade as "DB down"
# ---------------------------------------------------------------------------


class TestA7ExceptionNarrowness:
    def test_typeerror_from_non_serializable_payload_propagates(self):
        """A7: TypeError from json.dumps is a caller bug, NOT 'DB down'.

        A non-JSON-serializable payload must surface loudly rather than
        get silently converted to a suppressed save. Otherwise a
        programming bug looks identical to a network outage.
        """
        from openbb_fmp_trading.core.state_store import save_state

        class NotJSONSerializable:
            """No __json__, no default, not iterable — json.dumps rejects."""

            def __repr__(self):
                # Also break str(self) since default=str would otherwise
                # rescue us here.
                raise TypeError("intentionally unserializable")

        # execute_many is never reached — json.dumps raises inside save_state
        # before we get to the try/except around the DB call.
        with pytest.raises(TypeError):
            save_state("foo", NotJSONSerializable())

    def test_json_decode_error_on_load_propagates(self):
        """A7: corrupt JSON in the DB is also a bug worth surfacing."""
        from openbb_fmp_trading.core.state_store import load_state

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=[{"payload": "this is not valid JSON {["}],
        ):
            with pytest.raises(json.JSONDecodeError):
                load_state("foo")


# ---------------------------------------------------------------------------
# 8. A8 — typed load wrappers gracefully handle corrupt payloads
# ---------------------------------------------------------------------------


class TestA8TypedLoadWrappers:
    def test_load_last_watchlist_returns_list_of_strings(self):
        """Happy path: stored list[str] survives the JSON round-trip typed."""
        from openbb_fmp_trading.core.state_store import load_last_watchlist

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=[{"payload": '["MSFT","AAPL"]'}],
        ):
            result = load_last_watchlist()

        assert result == ["MSFT", "AAPL"]

    def test_load_last_watchlist_on_corrupt_shape_returns_none(self):
        """A8: not-a-list payload -> None + log WARN, NOT crash."""
        from openbb_fmp_trading.core.state_store import load_last_watchlist

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=[{"payload": '{"totally": "not a list"}'}],
        ):
            assert load_last_watchlist() is None

    def test_load_last_watchlist_on_list_of_non_strings_returns_none(self):
        """A8: list[int] where list[str] expected -> None + WARN."""
        from openbb_fmp_trading.core.state_store import load_last_watchlist

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=[{"payload": "[1, 2, 3]"}],
        ):
            assert load_last_watchlist() is None

    def test_load_last_session_summary_on_non_dict_returns_none(self):
        """A8: last_session_summary demands a dict shape."""
        from openbb_fmp_trading.core.state_store import (
            load_last_session_summary,
        )

        with patch(
            "openbb_fmp_cached.utils.database.execute_query",
            return_value=[{"payload": '"just a string"'}],
        ):
            assert load_last_session_summary() is None
