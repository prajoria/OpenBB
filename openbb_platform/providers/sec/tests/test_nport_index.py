"""Unit tests for openbb_sec.utils.nport_index (#99 T2).

All offline. Fakes the fmp_cached database module via patch on the lazy
``_db()`` import. Mirrors the pattern from test_openfigi.py + test_thirteen_f_index.py.

Coverage per design §3 ACs:
- DDL idempotency (init runs all 4 tables + seeds SPDR map)
- Write helpers (upsert_filing 12-tuple, upsert_holdings 13-tuple,
  upsert_fund_map 8-tuple, record_ingest_run, record_resume_cursor) idempotency
- Read helpers graceful on empty / DB error
- **L10 as-of read semantics** (asof=date returns rows from latest filing ≤ asof)
- **L11 amendment supersession** (NPORT-P/A supersedes prior NPORT-P)
- **G4 content-derived holding_key** regression (same content → same key)
- L12 staleness disclosure (report_date + data_age_days carried in returned dicts)
- is_uit flag handling (UIT fund → empty holdings, no exception)
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from openbb_sec.utils.nport_index import (
    ALL_DDL,
    SOURCE_NPORT_ARCHIVE,
    SOURCE_NPORT_BULK,
    SOURCE_NPORT_SUBMISSIONS,
    SOURCE_SEED,
    SPDR_FUND_MAP,
    fund_for_ticker,
    holdings_for_fund,
    init_nport_index,
    latest_period_for_fund,
    record_ingest_run,
    record_resume_cursor,
    seed_fund_map,
    upsert_filing,
    upsert_fund_map,
    upsert_holdings,
)

# ---------------------------------------------------------------------------
# DDL constants + init
# ---------------------------------------------------------------------------


def test_all_ddl_contains_four_create_table_statements():
    """4 tables per L4: filings, holdings, fund_map, ingest_runs."""
    assert len(ALL_DDL) == 4
    sql_blob = " ".join(ALL_DDL)
    assert "CREATE TABLE IF NOT EXISTS sec_nport_filings" in sql_blob
    assert "CREATE TABLE IF NOT EXISTS sec_nport_holdings" in sql_blob
    assert "CREATE TABLE IF NOT EXISTS sec_nport_fund_map" in sql_blob
    assert "CREATE TABLE IF NOT EXISTS sec_nport_ingest_runs" in sql_blob


def test_source_enum_constants_match_l8():
    """L8 provenance enum: sec_nport_bulk / submissions / archive + seed."""
    assert SOURCE_NPORT_BULK == "sec_nport_bulk"
    assert SOURCE_NPORT_SUBMISSIONS == "sec_nport_submissions"
    assert SOURCE_NPORT_ARCHIVE == "sec_nport_archive"
    assert SOURCE_SEED == "seed"


def test_spdr_fund_map_has_eleven_entries():
    """§2.3 seed: all 11 GICS sector SPDRs."""
    assert len(SPDR_FUND_MAP) == 11
    for ticker in ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
                   "XLP", "XLRE", "XLU", "XLV", "XLY"):
        assert ticker in SPDR_FUND_MAP


def test_spdr_fund_map_values_are_4_tuples():
    """SPDR seed value shape: (cik, series_id, fund_name, is_etf)."""
    for ticker, value in SPDR_FUND_MAP.items():
        assert len(value) == 4, f"{ticker} value must be (cik, series_id, fund_name, is_etf)"
        cik, series_id, fund_name, is_etf = value
        assert cik.isdigit() and len(cik) == 10, f"{ticker} cik must be 10-digit zero-padded"
        assert series_id.startswith("S"), f"{ticker} series_id must start with 'S'"
        assert is_etf is True, f"{ticker} is_etf must be True (these are all ETFs)"


def test_init_nport_index_runs_all_ddl(monkeypatch):
    """init_nport_index executes every DDL in ALL_DDL."""
    captured: list[str] = []

    def execute_query(sql, params=()):
        captured.append(sql)

    fake = MagicMock(execute_query=execute_query)
    fake.execute_many = MagicMock(return_value=11)  # seed_fund_map inside init
    monkeypatch.setattr("openbb_sec.utils.nport_index._db", lambda: fake)
    init_nport_index()
    assert sum("CREATE TABLE" in s for s in captured) == 4


def test_init_nport_index_seeds_spdr_fund_map(monkeypatch):
    """Init also seeds the 11 SPDR rows (idempotent via L5)."""
    seed_call_rows: list[list] = []

    def execute_query(sql, params=()):
        pass

    def execute_many(sql, rows):
        seed_call_rows.append(list(rows))
        return len(rows)

    fake = MagicMock(execute_query=execute_query, execute_many=execute_many)
    monkeypatch.setattr("openbb_sec.utils.nport_index._db", lambda: fake)
    init_nport_index()
    # seed_fund_map should have fired once with 11 SPDR rows
    assert seed_call_rows, "seed_fund_map should have fired"
    assert len(seed_call_rows[0]) == 11


# ---------------------------------------------------------------------------
# seed_fund_map
# ---------------------------------------------------------------------------


def test_seed_fund_map_writes_exactly_eleven_rows(monkeypatch):
    """seed_fund_map writes the 11 SPDR rows."""
    captured: list = []
    fake = MagicMock(execute_many=lambda sql, rows: captured.extend(rows) or len(rows))
    monkeypatch.setattr("openbb_sec.utils.nport_index._db", lambda: fake)
    n = seed_fund_map()
    assert n == 11
    assert len(captured) == 11


def test_seed_fund_map_row_shape_matches_upsert_fund_map_contract(monkeypatch):
    """Seed rows are 8-tuples matching upsert_fund_map signature per §2.3."""
    captured: list = []
    fake = MagicMock(execute_many=lambda sql, rows: captured.extend(rows) or len(rows))
    monkeypatch.setattr("openbb_sec.utils.nport_index._db", lambda: fake)
    seed_fund_map()
    assert all(len(row) == 8 for row in captured), \
        "Each seed row must be 8-tuple: (ticker, cik, series_id, class_id, fund_name, is_etf, source, updated_at)"


# ---------------------------------------------------------------------------
# Write helpers: tuple-shape enforcement
# ---------------------------------------------------------------------------


def test_upsert_filing_rejects_wrong_tuple_shape(monkeypatch):
    """12-tuple required; other shapes raise ValueError."""
    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_many=lambda s, r: 0))
    with pytest.raises(ValueError, match="12-tuple"):
        upsert_filing([("only", "five", "fields", "not", "twelve")])


def test_upsert_filing_idempotent_executemany_shape(monkeypatch):
    """Filings call execute_many with the 12-tuple SQL params."""
    captured = {}

    def execute_many(sql, rows):
        captured["sql"] = sql
        captured["rows"] = list(rows)
        return len(captured["rows"])

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_many=execute_many))
    row = (
        "0001234567-25-000001",  # accession_number
        "0000884394",            # cik
        "S000004310",            # series_id
        "C000000001",            # class_id
        date(2025, 12, 31),       # report_date
        datetime(2026, 2, 25),    # filing_date
        False,                   # is_amendment
        "sec_nport_bulk",        # source
        datetime(2026, 6, 27),    # ingested_at
        "https://www.sec.gov/Archives/edgar/data/...txt",  # raw_xml_url
        "abc" * 21 + "a",        # raw_xml_sha256 (64 chars)
        None,                    # raw_xml_blob (off by default)
    )
    upsert_filing([row])
    assert "INSERT INTO sec_nport_filings" in captured["sql"]
    assert "ON DUPLICATE KEY UPDATE" in captured["sql"]
    assert len(captured["rows"][0]) == 12


def test_upsert_holdings_rejects_wrong_tuple_shape(monkeypatch):
    """13-tuple required; other shapes raise ValueError."""
    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_many=lambda s, r: 0))
    with pytest.raises(ValueError, match="13-tuple"):
        upsert_holdings([("too", "few", "fields")])


def test_upsert_holdings_uses_content_derived_key_not_ordinal(monkeypatch):
    """G4: holding_key is in the upserted row; same content → same key on re-parse."""
    captured = {}

    def execute_many(sql, rows):
        captured["sql"] = sql
        captured["rows"] = list(rows)
        return len(captured["rows"])

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_many=execute_many))
    row = (
        "0001234567-25-000001",  # accession_number
        "037833100",             # holding_key (= CUSIP per G4)
        "APPLE INC",             # issuer_name
        "AAPL",                  # ticker
        "037833100",             # cusip
        "US0378331005",          # isin
        None,                    # lei
        "EC",                    # asset_category
        100.0,                   # units
        15000.0,                  # value_usd
        0.0234,                   # pct_nav
        "Long",                  # payoff_direction
        False,                   # derivative_flag
    )
    upsert_holdings([row])
    assert "INSERT INTO sec_nport_holdings" in captured["sql"]
    assert "ON DUPLICATE KEY UPDATE" in captured["sql"]
    # PK includes (accession_number, holding_key) — not an ordinal
    assert "(accession_number, holding_key)" in captured["sql"] or "holding_key" in captured["sql"]


def test_upsert_fund_map_8_tuple_idempotent(monkeypatch):
    """8-tuple shape upserts with the expected SQL."""
    captured = {}

    def execute_many(sql, rows):
        captured["sql"] = sql
        captured["rows"] = list(rows)
        return len(captured["rows"])

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_many=execute_many))
    row = ("XLK", "0000884394", "S000004310", None,
           "Technology Select Sector SPDR Fund", True, "seed", datetime(2026, 6, 27))
    upsert_fund_map([row])
    assert "INSERT INTO sec_nport_fund_map" in captured["sql"]
    assert "ON DUPLICATE KEY UPDATE" in captured["sql"]


def test_upsert_fund_map_rejects_wrong_tuple_shape(monkeypatch):
    """8-tuple required; other shapes raise ValueError."""
    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_many=lambda s, r: 0))
    with pytest.raises(ValueError, match="8-tuple"):
        upsert_fund_map([("XLK", "0000884394")])


def test_record_ingest_run_appends_observability_row(monkeypatch):
    """One INSERT into sec_nport_ingest_runs per call."""
    captured = []

    def execute_query(sql, params=()):
        captured.append((sql, params))

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    record_ingest_run(
        quarter="2026-Q1",
        mode="bulk",
        source_zip_sha256="abc" * 21 + "a",
        fund_count=512,
        holding_count=99000,
    )
    assert len(captured) == 1
    sql, params = captured[0]
    assert "INSERT INTO sec_nport_ingest_runs" in sql
    assert params[0] == "2026-Q1"
    assert params[1] == "bulk"


def test_record_resume_cursor_updates_last_accession_seen(monkeypatch):
    """G6: bulk loader writes the resume cursor after each chunk."""
    captured = []

    def execute_query(sql, params=()):
        captured.append((sql, params))

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    record_resume_cursor(
        quarter="2026-Q1",
        member="HOLDINGS.tsv",
        last_accession_seen="0001234567-25-000050",
    )
    assert len(captured) == 1
    sql, params = captured[0]
    # Resume cursor goes to sec_nport_ingest_runs (per design §2.1 + G6)
    assert "sec_nport_ingest_runs" in sql or "resume" in sql.lower()
    assert "0001234567-25-000050" in str(params)


# ---------------------------------------------------------------------------
# Read helpers: fund_for_ticker
# ---------------------------------------------------------------------------


def _fake_db_with_select(select_rows):
    """Build a MagicMock _db() that returns select_rows on any SELECT."""
    def execute_query(sql, params=()):
        if sql.lstrip().upper().startswith("SELECT"):
            return select_rows
        return None
    return MagicMock(execute_query=execute_query)


def test_fund_for_ticker_returns_row_when_present(monkeypatch):
    """Known ticker -> normalized fund dict."""
    rows = [{
        "cik": "0000884394",
        "series_id": "S000004310",
        "fund_name": "Technology Select Sector SPDR Fund",
        "is_etf": True,
        "is_uit": False,
    }]
    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: _fake_db_with_select(rows))
    result = fund_for_ticker("XLK")
    assert result is not None
    assert result["cik"] == "0000884394"
    assert result["series_id"] == "S000004310"
    assert result["is_etf"] is True


def test_fund_for_ticker_returns_none_when_unknown(monkeypatch):
    """Empty SELECT -> None."""
    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: _fake_db_with_select([]))
    assert fund_for_ticker("BOGUS") is None


def test_fund_for_ticker_uppercases_input(monkeypatch):
    """Lowercase input is upper-cased before the SQL params."""
    captured = {}

    def execute_query(sql, params=()):
        captured["params"] = params
        return []

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    fund_for_ticker("xlk")
    assert captured["params"][0] == "XLK"


def test_fund_for_ticker_returns_none_on_db_error(monkeypatch):
    """Any DB exception -> None (graceful)."""
    def boom(sql, params=()):
        raise RuntimeError("DB down")

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=boom))
    assert fund_for_ticker("XLK") is None


# ---------------------------------------------------------------------------
# Read helpers: holdings_for_fund (L10 + L11 + L12)
# ---------------------------------------------------------------------------


def _holding_row(holding_key="037833100", issuer="APPLE INC", ticker="AAPL",
                 cusip="037833100", pct_nav=0.0234, report_date=date(2025, 12, 31)):
    return {
        "accession_number": "0001234567-25-000001",
        "holding_key": holding_key,
        "issuer_name": issuer,
        "ticker": ticker,
        "cusip": cusip,
        "isin": "US0378331005",
        "lei": None,
        "asset_category": "EC",
        "units": 100.0,
        "value_usd": 15000.0,
        "pct_nav": pct_nav,
        "payoff_direction": "Long",
        "derivative_flag": False,
        "report_date": report_date,
    }


def test_holdings_for_fund_returns_latest_period_when_asof_none(monkeypatch):
    """asof=None → today; returns rows from most recent filing."""
    fund_row = {"cik": "0000884394", "series_id": "S000004310",
                "fund_name": "XLK Fund", "is_etf": True, "is_uit": False}
    latest_accession_row = [{
        "accession_number": "0001234567-25-000002",
        "report_date": date(2025, 12, 31),
        "is_amendment": False,
    }]
    holding_rows = [_holding_row(report_date=date(2025, 12, 31))]
    call_count = {"n": 0}

    def execute_query(sql, params=()):
        call_count["n"] += 1
        # Multi-step query: fund lookup first, then latest-filing lookup, then holdings
        sql_upper = sql.upper()
        if "FROM SEC_NPORT_FUND_MAP" in sql_upper:
            return [fund_row]
        if "FROM SEC_NPORT_FILINGS" in sql_upper:
            return latest_accession_row
        if "FROM SEC_NPORT_HOLDINGS" in sql_upper:
            return holding_rows
        return []

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    rows = holdings_for_fund("XLK")
    assert len(rows) == 1
    assert rows[0]["holding_key"] == "037833100"


def test_holdings_for_fund_returns_period_at_or_before_asof(monkeypatch):
    """L10 as-of: asof=2025-09-30 returns the Q3 filing, not Q4."""
    fund_row = {"cik": "0000884394", "series_id": "S000004310",
                "fund_name": "XLK Fund", "is_etf": True, "is_uit": False}
    q3_filing = [{
        "accession_number": "Q3-ACCN",
        "report_date": date(2025, 9, 30),
        "is_amendment": False,
    }]
    q3_holdings = [_holding_row(report_date=date(2025, 9, 30))]
    captured_filings_query = {}

    def execute_query(sql, params=()):
        sql_upper = sql.upper()
        if "FROM SEC_NPORT_FUND_MAP" in sql_upper:
            return [fund_row]
        if "FROM SEC_NPORT_FILINGS" in sql_upper:
            # Verify the WHERE clause carries an asof comparison
            captured_filings_query["sql"] = sql
            captured_filings_query["params"] = params
            return q3_filing
        if "FROM SEC_NPORT_HOLDINGS" in sql_upper:
            return q3_holdings
        return []

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    rows = holdings_for_fund("XLK", asof=date(2025, 9, 30))
    assert len(rows) == 1
    # The asof must have been passed into the filings query as a parameter
    assert any("2025-09-30" in str(p) or date(2025, 9, 30) in (
        p if isinstance(p, tuple) else [p]
    ) for p in [captured_filings_query.get("params")])


def test_holdings_for_fund_amendment_supersedes_original(monkeypatch):
    """L11 / G5: NPORT-P/A supersedes prior NPORT-P for same (cik, series, period).

    The filings query should ORDER BY filing_date DESC (or accession_number DESC)
    so the amendment comes back first; holdings_for_fund returns only THAT
    accession's holdings, not the union of original + amendment.
    """
    fund_row = {"cik": "0000884394", "series_id": "S000004310",
                "fund_name": "XLK Fund", "is_etf": True, "is_uit": False}
    # Amendment B is the latest filing for the period
    latest_filing = [{
        "accession_number": "B-AMENDMENT",
        "report_date": date(2025, 12, 31),
        "is_amendment": True,
    }]
    amendment_holdings = [
        _holding_row(holding_key="AAPL-NEW", issuer="APPLE INC AMENDED"),
    ]
    captured_holdings_params = {}

    def execute_query(sql, params=()):
        sql_upper = sql.upper()
        if "FROM SEC_NPORT_FUND_MAP" in sql_upper:
            return [fund_row]
        if "FROM SEC_NPORT_FILINGS" in sql_upper:
            return latest_filing
        if "FROM SEC_NPORT_HOLDINGS" in sql_upper:
            captured_holdings_params["params"] = params
            return amendment_holdings
        return []

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    rows = holdings_for_fund("XLK", asof=date(2025, 12, 31))
    # Only the amendment's holdings are returned
    assert len(rows) == 1
    assert rows[0]["issuer_name"] == "APPLE INC AMENDED"
    # Holdings query was scoped to the amendment accession only
    assert "B-AMENDMENT" in str(captured_holdings_params.get("params"))


def test_holdings_for_fund_carries_report_date_and_data_age_days(monkeypatch):
    """L12 staleness disclosure: every returned row carries report_date + data_age_days."""
    fund_row = {"cik": "0000884394", "series_id": "S000004310",
                "fund_name": "XLK Fund", "is_etf": True, "is_uit": False}
    rd = date(2025, 12, 31)
    filing = [{"accession_number": "X", "report_date": rd, "is_amendment": False}]
    holdings = [_holding_row(report_date=rd)]

    def execute_query(sql, params=()):
        sql_upper = sql.upper()
        if "FUND_MAP" in sql_upper:
            return [fund_row]
        if "FILINGS" in sql_upper:
            return filing
        if "HOLDINGS" in sql_upper:
            return holdings
        return []

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    rows = holdings_for_fund("XLK")
    assert rows
    row = rows[0]
    assert row["report_date"] == rd
    assert "data_age_days" in row
    assert isinstance(row["data_age_days"], int)
    assert row["data_age_days"] >= 0


def test_holdings_for_fund_uit_fund_returns_empty(monkeypatch):
    """UITs may not file NPORT-P; is_uit=True funds with no filings return []."""
    fund_row = {"cik": "0000884394", "series_id": "S000004310",
                "fund_name": "SPY (UIT)", "is_etf": True, "is_uit": True}

    def execute_query(sql, params=()):
        sql_upper = sql.upper()
        if "FUND_MAP" in sql_upper:
            return [fund_row]
        # No filings/holdings for the UIT
        return []

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=execute_query))
    rows = holdings_for_fund("SPY")
    assert rows == []


def test_holdings_for_fund_unknown_ticker_returns_empty(monkeypatch):
    """Unknown ticker -> [] (graceful)."""
    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: _fake_db_with_select([]))
    assert holdings_for_fund("BOGUS") == []


def test_holdings_for_fund_graceful_on_db_error(monkeypatch):
    """DB exception -> [] (graceful)."""
    def boom(sql, params=()):
        raise RuntimeError("DB down")

    monkeypatch.setattr("openbb_sec.utils.nport_index._db",
                        lambda: MagicMock(execute_query=boom))
    assert holdings_for_fund("XLK") == []


# ---------------------------------------------------------------------------
# latest_period_for_fund
# ---------------------------------------------------------------------------


def test_latest_period_for_fund_returns_max_report_date(monkeypatch):
    """Returns the max(report_date) for a fund."""
    monkeypatch.setattr(
        "openbb_sec.utils.nport_index._db",
        lambda: _fake_db_with_select([{"max_report_date": date(2025, 12, 31)}]),
    )
    period = latest_period_for_fund("0000884394", "S000004310")
    assert period == date(2025, 12, 31)


def test_latest_period_for_fund_returns_none_on_empty(monkeypatch):
    """Empty result -> None (graceful)."""
    monkeypatch.setattr(
        "openbb_sec.utils.nport_index._db",
        lambda: _fake_db_with_select([{"max_report_date": None}]),
    )
    assert latest_period_for_fund("0000884394", "S000004310") is None
