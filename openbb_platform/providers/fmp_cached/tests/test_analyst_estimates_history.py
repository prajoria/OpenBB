"""Unit tests for the #998 / #1025 historical snapshotting helpers.

Discriminators:

- **_store_history** builds INSERT batches keyed by (symbol, date,
  period, snapshot_date). Test the batch shape without hitting MySQL
  via monkeypatching execute_many.
- **get_estimate_as_of** returns the LATEST snapshot <= as_of_date, or
  None. Test the SQL contract shape via monkeypatching execute_query.
- **Snapshot on today** — _store_history always uses date.today() (utc)
  as snapshot_date, so a same-day re-fetch overwrites via ON DUPLICATE
  KEY UPDATE (deferred to integration tests to actually verify the
  DUP-KEY behavior).
- **Loud empty** — get_estimate_as_of returns None on empty result set,
  never raises.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest


class _FakeQuery:
    """Minimal duck-type for FMPCachedAnalystEstimatesQueryParams."""

    def __init__(self, symbol: str = "AAPL", period: str = "quarter") -> None:
        self.symbol = symbol
        self.period = period


def test_store_history_builds_correct_insert_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One row per input fmp_data dict, all with the same snapshot_date."""
    from openbb_fmp_cached.models import analyst_estimates as m

    captured: list[tuple] = []

    def fake_execute_many(sql: str, params: list[tuple]) -> None:
        assert "INSERT INTO analyst_estimates_history" in sql
        captured.extend(params)

    def fake_create() -> None:
        return None

    monkeypatch.setattr(m, "execute_many", fake_execute_many)
    monkeypatch.setattr(
        "openbb_fmp_cached.utils.cache_schema.create_analyst_estimates_history_table",
        fake_create,
    )

    fmp_data = [
        {
            "date": "2026-03-31",
            "estimatedRevenueAvg": 100_000_000.0,
            "estimatedEpsAvg": 2.50,
            "numberAnalystsEstimatedRevenue": 32,
            "numberAnalystsEstimatedEps": 30,
        },
        {
            "date": "2026-06-30",
            "estimatedRevenueAvg": 110_000_000.0,
            "estimatedEpsAvg": 2.75,
            "numberAnalystsEstimatedRevenue": 32,
            "numberAnalystsEstimatedEps": 30,
        },
    ]

    m._store_history(_FakeQuery("AAPL", "quarter"), fmp_data)

    assert len(captured) == 2
    # (symbol, date, period, snapshot_date, revLow, revHigh, revAvg, ...)
    for row, expected_date_str in zip(captured, ["2026-03-31", "2026-06-30"]):
        assert row[0] == "AAPL"
        assert row[1] == datetime.strptime(expected_date_str, "%Y-%m-%d").date()
        assert row[2] == "quarter"
        # snapshot_date is today; just verify it's a date, not a str
        assert isinstance(row[3], date)


def test_store_history_skips_rows_without_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing / unparseable date → drop the row silently (data-quality)."""
    from openbb_fmp_cached.models import analyst_estimates as m

    captured: list[tuple] = []
    monkeypatch.setattr(m, "execute_many", lambda sql, p: captured.extend(p))
    monkeypatch.setattr(
        "openbb_fmp_cached.utils.cache_schema.create_analyst_estimates_history_table",
        lambda: None,
    )

    m._store_history(
        _FakeQuery(),
        [
            {"date": None, "estimatedEpsAvg": 1.0},  # missing
            {"date": "not-a-date", "estimatedEpsAvg": 1.0},  # unparseable
            {"date": "2026-03-31", "estimatedEpsAvg": 1.0},  # good
        ],
    )
    assert len(captured) == 1
    assert captured[0][1] == date(2026, 3, 31)


def test_store_history_empty_input_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty fmp_data → no DDL call, no INSERT."""
    from openbb_fmp_cached.models import analyst_estimates as m

    called = {"n": 0}

    def spy(*_a, **_kw) -> None:
        called["n"] += 1

    monkeypatch.setattr(m, "execute_many", spy)
    monkeypatch.setattr(
        "openbb_fmp_cached.utils.cache_schema.create_analyst_estimates_history_table",
        spy,
    )
    m._store_history(_FakeQuery(), [])
    assert called["n"] == 0


def test_get_estimate_as_of_returns_latest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQL contract: ORDER BY snapshot_date DESC LIMIT 1; return the row dict."""
    from openbb_fmp_cached.models import analyst_estimates as m

    captured_sql: list[str] = []
    captured_args: list[tuple] = []

    def fake_execute_query(sql: str, args: tuple):
        captured_sql.append(sql)
        captured_args.append(args)
        return [
            {
                "estimated_revenue_avg": 100_000_000.0,
                "estimated_eps_avg": 2.50,
                "snapshot_date": date(2026, 4, 15),
            }
        ]

    monkeypatch.setattr(m, "execute_query", fake_execute_query)

    row = m.get_estimate_as_of(
        symbol="AAPL",
        fiscal_period_end=date(2026, 3, 31),
        as_of_date=date(2026, 5, 1),
        period="quarter",
    )
    assert row is not None
    assert row["estimated_eps_avg"] == 2.50
    assert row["snapshot_date"] == date(2026, 4, 15)

    # Verify contract shape
    assert "ORDER BY snapshot_date DESC" in captured_sql[0]
    assert "LIMIT 1" in captured_sql[0]
    assert captured_args[0] == ("AAPL", date(2026, 3, 31), "quarter", date(2026, 5, 1))


def test_get_estimate_as_of_returns_None_on_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No snapshot exists yet → None, no exception."""
    from openbb_fmp_cached.models import analyst_estimates as m

    monkeypatch.setattr(m, "execute_query", lambda *_a, **_kw: [])
    row = m.get_estimate_as_of(
        symbol="ZZZ",
        fiscal_period_end=date(2026, 3, 31),
        as_of_date=date(2026, 5, 1),
    )
    assert row is None


def test_get_estimate_as_of_returns_None_on_query_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB error → None + WARN log; never propagates."""
    from openbb_fmp_cached.models import analyst_estimates as m

    def boom(*_a, **_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(m, "execute_query", boom)
    row = m.get_estimate_as_of(
        symbol="AAPL",
        fiscal_period_end=date(2026, 3, 31),
        as_of_date=date(2026, 5, 1),
    )
    assert row is None


def test_get_estimate_for_period_before_release_requires_exact_fiscal_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-calendar issuer period uses its exact date and a pre-release snapshot."""
    from openbb_fmp_cached.models import analyst_estimates as m

    fiscal_period_end = date(2026, 6, 27)
    release_date = date(2026, 8, 1)

    def fake_execute_query(sql: str, args: tuple):
        assert "AND date = %s" in sql
        assert "AND date <= %s" not in sql
        assert "snapshot_date <= %s" in sql
        assert "ORDER BY snapshot_date DESC" in sql
        assert args == ("AAPL", fiscal_period_end, "quarter", release_date)
        return [
            {
                "fiscal_period_end": fiscal_period_end,
                "estimated_revenue_avg": 100_000_000.0,
                "snapshot_date": date(2026, 7, 31),
            }
        ]

    monkeypatch.setattr(m, "execute_query", fake_execute_query)

    row = m.get_estimate_for_period_before_release(
        symbol="AAPL",
        fiscal_period_end=fiscal_period_end,
        release_date=release_date,
        period="quarter",
    )

    assert row == {
        "fiscal_period_end": fiscal_period_end,
        "estimated_revenue_avg": 100_000_000.0,
        "snapshot_date": date(2026, 7, 31),
    }


def test_get_estimate_for_period_before_release_returns_none_without_exact_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior-period row cannot substitute for the latest issuer period."""
    from openbb_fmp_cached.models import analyst_estimates as m

    fiscal_period_end = date(2026, 6, 27)
    release_date = date(2026, 8, 1)

    def no_exact_pre_release_snapshot(sql: str, args: tuple) -> list[dict]:
        assert "AND date = %s" in sql
        assert args == ("AAPL", fiscal_period_end, "quarter", release_date)
        # The database would have a March row, but the equality predicate
        # excludes it instead of silently relabeling it as last quarter.
        return []

    monkeypatch.setattr(m, "execute_query", no_exact_pre_release_snapshot)

    assert (
        m.get_estimate_for_period_before_release(
            symbol="AAPL",
            fiscal_period_end=fiscal_period_end,
            release_date=release_date,
            period="quarter",
        )
        is None
    )
