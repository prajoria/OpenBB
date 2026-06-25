"""Unit tests for openbb_sec.utils.openfigi (#93).

All tests are offline — no live network. Fixtures mirror the
``third_party/openfigi-api/python/example.py`` response shape.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests
from openbb_sec.utils.openfigi import (
    OPENFIGI_CACHE_TTL_DAYS,
    cache_get,
    cache_put,
    init_openfigi_cache,
    map_cusips,
    resolve_credentials,
    select_match,
)

# ---------------------------------------------------------------------------
# Fixtures — verbatim shapes from third_party/openfigi-api/python/example.py
# ---------------------------------------------------------------------------

AAPL_JOB_RESULT: dict = {
    "data": [
        {
            "figi": "BBG000B9XRY4",
            "name": "APPLE INC",
            "ticker": "AAPL",
            "exchCode": "US",
            "compositeFIGI": "BBG000B9XRY4",
            "uniqueID": "EQ0010169500001000",
            "securityType": "Common Stock",
            "marketSector": "Equity",
            "shareClassFIGI": "BBG001S5N8V8",
            "securityType2": "Common Stock",
            "securityDescription": "AAPL",
        }
    ]
}

NO_MATCH_JOB_RESULT: dict = {"warning": "No identifier found."}

ERROR_JOB_RESULT: dict = {"error": "Invalid idType/idValue combination"}


# ---------------------------------------------------------------------------
# R3 select_match() — first failing test (Step 3)
# ---------------------------------------------------------------------------


def test_select_match_returns_single_us_composite_common():
    """R3 ladder rung (a): one Common-Stock US-composite match -> keep it."""
    m = select_match(AAPL_JOB_RESULT)
    assert m is not None
    assert m["ticker"] == "AAPL"
    assert m["figi"] == "BBG000B9XRY4"
    assert m["securityType2"] == "Common Stock"


def test_select_match_multi_match_us_composite_plus_foreign_keeps_us():
    """Multi-listing: foreign listings filtered out; US composite kept."""
    job = {
        "data": [
            {
                "ticker": "AAPL", "figi": "BBG000B9XRY4", "exchCode": "US",
                "compositeFIGI": "BBG000B9XRY4", "securityType2": "Common Stock",
                "marketSector": "Equity",
            },
            {
                "ticker": "APC", "figi": "BBG000BLPDP5", "exchCode": "GR",
                "compositeFIGI": "BBG000B9XRY4", "securityType2": "Common Stock",
                "marketSector": "Equity",
            },
        ]
    }
    m = select_match(job)
    assert m is not None and m["ticker"] == "AAPL"


def test_select_match_adr_via_us_composite():
    """ADR CUSIP -> US ADR ticker through composite FIGI."""
    job = {
        "data": [
            {
                "ticker": "BABA", "figi": "BBG006G2JVL2", "exchCode": "US",
                "compositeFIGI": "BBG006G2JVL2", "securityType2": "Common Stock",
                "marketSector": "Equity",
            },
        ]
    }
    assert select_match(job) is not None


def test_select_match_preferred_only_returns_preferred():
    """Preferred-only CUSIP is legitimately resolvable; not filtered out."""
    job = {
        "data": [
            {
                "ticker": "BAC-PB", "figi": "BBG004NLQHS5", "exchCode": "US",
                "compositeFIGI": "BBG004NLQHS5", "securityType2": "Preferred Stock",
                "marketSector": "Equity",
            },
        ]
    }
    m = select_match(job)
    assert m is not None and m["securityType2"] == "Preferred Stock"


def test_select_match_error_payload_returns_none():
    """An error-shaped /v3/mapping response has no usable match."""
    assert select_match(ERROR_JOB_RESULT) is None


def test_select_match_no_match_returns_none():
    """A warning-only ('No identifier found') response has no usable match."""
    assert select_match(NO_MATCH_JOB_RESULT) is None


def test_select_match_truly_ambiguous_two_us_commons_returns_none():
    """Both rows survive every rung -> caller must persist as 'ambiguous'."""
    job = {
        "data": [
            {
                "ticker": "FOO", "figi": "BBG000000001", "exchCode": "US",
                "compositeFIGI": "BBG000000001", "securityType2": "Common Stock",
                "marketSector": "Equity",
            },
            {
                "ticker": "BAR", "figi": "BBG000000002", "exchCode": "US",
                "compositeFIGI": "BBG000000002", "securityType2": "Common Stock",
                "marketSector": "Equity",
            },
        ]
    }
    assert select_match(job) is None


def test_select_match_prefers_common_over_preferred_when_tied():
    """R3 rung (c): Common Stock wins over Preferred Stock when both survive (a) + (b)."""
    job = {
        "data": [
            {
                "ticker": "FOO", "figi": "BBG000000001", "exchCode": "US",
                "compositeFIGI": "BBG000000001", "securityType2": "Common Stock",
                "marketSector": "Equity",
            },
            {
                "ticker": "FOO-PA", "figi": "BBG000000002", "exchCode": "US",
                "compositeFIGI": "BBG000000002", "securityType2": "Preferred Stock",
                "marketSector": "Equity",
            },
        ]
    }
    m = select_match(job)
    assert m is not None and m["securityType2"] == "Common Stock"


# ---------------------------------------------------------------------------
# R2 resolve_credentials() — flag -> env -> user_settings -> keyless
# ---------------------------------------------------------------------------


def test_resolve_credentials_flag_wins(monkeypatch):
    """R2: --api-key flag overrides any env / user_settings credential."""
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "from-env")
    key, source = resolve_credentials("from-flag")
    assert key == "from-flag" and source == "flag"


def test_resolve_credentials_env_used_when_no_flag(monkeypatch):
    """R2: OPEN_FIGI_API_KEY env is used when no --api-key was passed."""
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "from-env")
    key, source = resolve_credentials(None)
    assert key == "from-env" and source == "env"


def test_resolve_credentials_user_settings_used_when_no_env(monkeypatch):
    """R2: user_settings.credentials.openfigi_api_key is the third fallback."""
    monkeypatch.delenv("OPEN_FIGI_API_KEY", raising=False)
    fake_creds = MagicMock(openfigi_api_key="from-settings")
    with patch(
        "openbb_sec.utils.openfigi._user_service_credentials",
        return_value=fake_creds,
    ):
        key, source = resolve_credentials(None)
    assert key == "from-settings" and source == "user_settings"


def test_resolve_credentials_keyless_when_nothing_available(monkeypatch):
    """R2: with no flag/env/settings, returns (None, 'keyless') for low-rate mode."""
    monkeypatch.delenv("OPEN_FIGI_API_KEY", raising=False)
    with patch(
        "openbb_sec.utils.openfigi._user_service_credentials",
        return_value=None,
    ):
        key, source = resolve_credentials(None)
    assert key is None and source == "keyless"


# ---------------------------------------------------------------------------
# R9 openfigi_map_cache — DDL + cache_get / cache_put round-trip + TTL
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_db(monkeypatch):
    """Replace ``_db()`` with an in-memory dict-of-rows fake.

    Returns the underlying list so tests can inspect / pre-seed rows.
    """
    rows: list[dict] = []

    def execute_many(sql, batch):
        # Cache upsert path: (id_type, id_value, exch_code, response_json,
        #                    status, match_count, fetched_at)
        for tup in batch:
            # Remove any pre-existing PK match (simulate ON DUPLICATE KEY UPDATE)
            for idx, existing in enumerate(rows):
                if (existing["id_type"], existing["id_value"], existing["exch_code"]) == (
                    tup[0], tup[1], tup[2],
                ):
                    rows.pop(idx)
                    break
            rows.append({
                "id_type": tup[0],
                "id_value": tup[1],
                "exch_code": tup[2],
                "response_json": tup[3],
                "status": tup[4],
                "match_count": tup[5],
                "fetched_at": tup[6],
                "is_valid": 1,
            })
        return len(batch)

    def execute_query(sql, params=()):
        sql_upper = sql.lstrip().upper()
        if sql_upper.startswith("CREATE"):
            return None
        if sql_upper.startswith("SELECT"):
            # Only one SELECT shape is used by openfigi: by (id_type, id_value, exch_code).
            id_type, id_value, exch_code = params[0], params[1], params[2]
            for r in rows:
                if (r["id_type"], r["id_value"], r["exch_code"]) == (
                    id_type, id_value, exch_code,
                ):
                    return [r]
            return []
        return None

    fake = MagicMock(execute_many=execute_many, execute_query=execute_query)
    monkeypatch.setattr("openbb_sec.utils.openfigi._db", lambda: fake)
    return rows


def test_init_openfigi_cache_runs_ddl(monkeypatch):
    """R9: ``init_openfigi_cache`` executes a CREATE TABLE IF NOT EXISTS statement."""
    captured = []

    def execute_query(sql, params=()):
        captured.append(sql)

    fake = MagicMock(execute_query=execute_query)
    monkeypatch.setattr("openbb_sec.utils.openfigi._db", lambda: fake)
    init_openfigi_cache()
    assert any("CREATE TABLE IF NOT EXISTS openfigi_map_cache" in s for s in captured)


def test_cache_put_then_get_round_trips(fake_db):
    """R9: putting a raw job result, then getting it back yields the same dict."""
    cache_put("037833100", AAPL_JOB_RESULT)
    hit = cache_get("037833100")
    assert hit is not None
    assert hit["data"][0]["ticker"] == "AAPL"


def test_cache_get_miss_returns_none(fake_db):
    """R9: an unknown CUSIP yields a cache miss (None)."""
    assert cache_get("999999999") is None


def test_cache_get_stale_row_returns_none(fake_db):
    """Row older than OPENFIGI_CACHE_TTL_DAYS is a miss."""
    stale_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=OPENFIGI_CACHE_TTL_DAYS + 1
    )
    fake_db.append({
        "id_type": "ID_CUSIP",
        "id_value": "111111111",
        "exch_code": "",
        "response_json": json.dumps(AAPL_JOB_RESULT),
        "status": "ok",
        "match_count": 1,
        "fetched_at": stale_dt,
        "is_valid": 1,
    })
    assert cache_get("111111111") is None


# ---------------------------------------------------------------------------
# map_cusips() — read-through cache + batching + 429 Retry-After
# ---------------------------------------------------------------------------


def test_map_cusips_serves_from_cache_when_present(fake_db):
    """R9 cache hit short-circuits the HTTP call entirely."""
    cache_put("037833100", AAPL_JOB_RESULT)
    with patch(
        "openbb_sec.utils.openfigi.requests.post",
        side_effect=AssertionError("must not be called when cache is fresh"),
    ) as p:
        result = map_cusips(["037833100"], api_key=None)
    assert p.call_count == 0
    assert result["037833100"]["data"][0]["ticker"] == "AAPL"


def test_map_cusips_batches_misses_and_caches_responses(fake_db):
    """Misses are batched into one POST whose results are cached for later runs."""
    response_mock = MagicMock(status_code=200)
    response_mock.json.return_value = [AAPL_JOB_RESULT, NO_MATCH_JOB_RESULT]
    response_mock.raise_for_status.return_value = None
    with patch(
        "openbb_sec.utils.openfigi.requests.post", return_value=response_mock
    ) as p, patch("openbb_sec.utils.openfigi.time.sleep", lambda s: None):
        result = map_cusips(["037833100", "999999999"], api_key=None)
    assert p.call_count == 1  # one batch, two jobs
    payload = p.call_args.kwargs["json"]
    assert payload == [
        {"idType": "ID_CUSIP", "idValue": "037833100"},
        {"idType": "ID_CUSIP", "idValue": "999999999"},
    ]
    assert cache_get("037833100") is not None
    assert cache_get("999999999") is not None
    assert result["999999999"] == NO_MATCH_JOB_RESULT


def test_map_cusips_honors_retry_after_on_429(fake_db):
    """429 with Retry-After: 1 -> sleep 1s, then succeed."""
    sleeps: list[float] = []

    too_many = MagicMock(status_code=429, headers={"Retry-After": "1"})
    too_many.raise_for_status.side_effect = requests.HTTPError(response=too_many)
    ok = MagicMock(status_code=200)
    ok.json.return_value = [AAPL_JOB_RESULT]
    ok.raise_for_status.return_value = None

    with patch(
        "openbb_sec.utils.openfigi.requests.post", side_effect=[too_many, ok]
    ) as p, patch("openbb_sec.utils.openfigi.time.sleep", sleeps.append):
        result = map_cusips(["037833100"], api_key=None)
    assert p.call_count == 2
    assert 1 in sleeps  # Retry-After honored
    assert result["037833100"]["data"][0]["ticker"] == "AAPL"


def test_map_cusips_refresh_bypasses_cache(fake_db):
    """``refresh=True`` skips cache reads and overwrites the row with fresh data."""
    cache_put("037833100", NO_MATCH_JOB_RESULT)  # stale-looking row
    response_mock = MagicMock(status_code=200)
    response_mock.json.return_value = [AAPL_JOB_RESULT]
    response_mock.raise_for_status.return_value = None
    with patch(
        "openbb_sec.utils.openfigi.requests.post", return_value=response_mock
    ), patch("openbb_sec.utils.openfigi.time.sleep", lambda s: None):
        result = map_cusips(["037833100"], api_key=None, refresh=True)
    assert result["037833100"] == AAPL_JOB_RESULT
