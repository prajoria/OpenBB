"""Unit tests for intraday_drift strategy calculations and top-50 adapters.

Fixtures use **realistic 09:30-aligned intraday grids** because that is what
Yahoo Finance actually returns for US equities.  A 60-minute grid is
``09:30, 10:30, 11:30, 12:30, …`` -- it contains **no 12:00 bar** -- so
selecting the entry bar by hour alone would pick 12:30 ET (09:30 Pacific)
instead of the intended 12:00 ET (09:00 Pacific).  Several tests below
reverse-lock that regression.
"""

import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from openbb_backtest.strategies.intraday_drift import (
    BAR_MINUTES,
    ENTRY_HOUR,
    ENTRY_MINUTE,
    EXIT_HOUR,
    EXIT_MINUTE,
    DriftSummary,
    build_observations,
    exit_interval_end,
    filter_incomplete_exit_sessions,
    summarize_observations,
)

# Make the examples module importable without installation
from top50_intraday_drift import (  # noqa: E402
    INTRADAY_INTERVAL,
    WINDOW_TOLERANCE_DAYS,
    _promote_single_ticker_columns,
    assess_window_completeness,
    compute_requested_window,
    download_intraday_bars,
    enforce_window_completeness,
    fetch_top_symbols,
    intraday_chunks,
    main as cli_main,
    normalize_yfinance_bars,
    run_study,
)

NY = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")

# Realistic Yahoo grids: anchored on the 09:30 regular-session open.
GRID_30M = [
    (9, 30),
    (10, 0),
    (10, 30),
    (11, 0),
    (11, 30),
    (12, 0),
    (12, 30),
    (13, 0),
    (13, 30),
    (14, 0),
    (14, 30),
    (15, 0),
    (15, 30),
]
GRID_60M = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]

# A far-past as-of instant is safe for every historical fixture below.
AS_OF = datetime(2026, 12, 31, 23, 59, tzinfo=NY)


def session_bars(
    session: date,
    symbol: str,
    overrides: dict | None = None,
    grid=GRID_30M,
    tz=NY,
    base: float = 100.0,
) -> list[dict]:
    """Return one session of realistic bars on *grid* for *symbol*.

    ``overrides`` maps ``(hour, minute)`` to ``(open, close)`` so a test can
    make a specific bar identifiable.
    """
    overrides = overrides or {}
    rows = []
    for i, (hour, minute) in enumerate(grid):
        open_, close = overrides.get((hour, minute), (base + i, base + i + 0.5))
        rows.append(
            {
                "timestamp": datetime(
                    session.year, session.month, session.day, hour, minute, tzinfo=tz
                ),
                "symbol": symbol,
                "open": open_,
                "close": close,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# build_observations -- bar selection
# ---------------------------------------------------------------------------


def test_build_observations_uses_1200_open_and_1530_close():
    """Entry is the 12:00 ET open; exit is the 15:30 ET bar close."""
    rows = session_bars(
        date(2026, 2, 10),
        "AAA",
        overrides={(12, 0): (100.0, 101.0), (15, 30): (104.0, 105.0)},
    )
    rows += session_bars(
        date(2026, 7, 10),
        "BBB",
        overrides={(12, 0): (200.0, 198.0), (15, 30): (197.0, 196.0)},
        base=200.0,
    )
    # CCC has an entry bar but no exit bar for that session
    rows += [
        r
        for r in session_bars(
            date(2026, 7, 10), "CCC", overrides={(12, 0): (50.0, 51.0)}, base=50.0
        )
        if (r["timestamp"].hour, r["timestamp"].minute) != (15, 30)
    ]

    observations = build_observations(pd.DataFrame(rows), now=AS_OF)

    assert observations[["symbol", "entry_price", "exit_price", "win"]].to_dict(
        "records"
    ) == [
        {"symbol": "AAA", "entry_price": 100.0, "exit_price": 105.0, "win": True},
        {"symbol": "BBB", "entry_price": 200.0, "exit_price": 196.0, "win": False},
    ]


def test_build_observations_does_not_use_1230_bar_as_entry():
    """REVERSE-LOCK: 12:30 ET (09:30 PT) must never be chosen as the entry bar.

    Yahoo's 60-minute grid has a 12:30 bar and no 12:00 bar, so an
    ``hour == 12`` selector silently traded 30 minutes late.  The 12:30 open
    here is deliberately unmistakable (999.0).
    """
    rows = session_bars(
        date(2026, 2, 10),
        "AAA",
        overrides={
            (12, 0): (100.0, 101.0),
            (12, 30): (999.0, 999.5),
            (15, 30): (104.0, 105.0),
        },
    )

    obs = build_observations(pd.DataFrame(rows), now=AS_OF)

    assert len(obs) == 1
    assert obs.iloc[0]["entry_price"] == pytest.approx(100.0)
    assert obs.iloc[0]["entry_price"] != pytest.approx(999.0)


def test_build_observations_hourly_grid_yields_no_observations():
    """REVERSE-LOCK: a 09:30-aligned 60-minute grid has no 12:00 bar at all.

    With exact hour+minute matching this session is correctly dropped.  Under
    the old hour-only selector it would have produced an observation entered
    at 12:30 ET, which is the bug this test guards.
    """
    rows = session_bars(
        date(2026, 2, 10),
        "AAA",
        overrides={(12, 30): (999.0, 999.5), (15, 30): (104.0, 105.0)},
        grid=GRID_60M,
    )

    obs = build_observations(pd.DataFrame(rows), now=AS_OF)

    assert len(obs) == 0


def test_build_observations_entry_minute_is_zero_by_default():
    """Defaults must be exactly 12:00 -> 15:30 with 30-minute bars."""
    assert (ENTRY_HOUR, ENTRY_MINUTE) == (12, 0)
    assert (EXIT_HOUR, EXIT_MINUTE) == (15, 30)
    assert BAR_MINUTES == 30


def test_build_observations_custom_bar_times_are_honoured():
    """Entry/exit geometry is parameterised, not hard-coded."""
    rows = session_bars(
        date(2026, 2, 10),
        "AAA",
        overrides={(10, 30): (10.0, 11.0), (14, 0): (12.0, 13.0)},
    )

    obs = build_observations(
        pd.DataFrame(rows),
        now=AS_OF,
        entry_hour=10,
        entry_minute=30,
        exit_hour=14,
        exit_minute=0,
    )

    assert len(obs) == 1
    assert obs.iloc[0]["entry_price"] == pytest.approx(10.0)
    assert obs.iloc[0]["exit_price"] == pytest.approx(13.0)


def test_build_observations_invalid_geometry_raises():
    rows = session_bars(date(2026, 2, 10), "AAA")
    with pytest.raises(ValueError, match=r"entry_hour and exit_hour"):
        build_observations(pd.DataFrame(rows), now=AS_OF, entry_hour=25)
    with pytest.raises(ValueError, match=r"entry_minute and exit_minute"):
        build_observations(pd.DataFrame(rows), now=AS_OF, exit_minute=99)
    with pytest.raises(ValueError, match="bar_minutes must be positive"):
        build_observations(pd.DataFrame(rows), now=AS_OF, bar_minutes=0)


def test_build_observations_output_columns():
    rows = session_bars(date(2026, 2, 10), "AAA")
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)
    assert set(obs.columns) >= {
        "session",
        "symbol",
        "entry_price",
        "exit_price",
        "return",
        "win",
    }


def test_build_observations_sorted_by_session_symbol():
    """Output must be sorted by (session ASC, symbol ASC) regardless of input order."""
    rows = session_bars(date(2026, 7, 10), "BBB", base=200.0)
    rows += session_bars(date(2026, 2, 10), "AAA")
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)

    assert obs.iloc[0]["session"] == date(2026, 2, 10)
    assert obs.iloc[0]["symbol"] == "AAA"
    assert obs.iloc[1]["session"] == date(2026, 7, 10)
    assert obs.iloc[1]["symbol"] == "BBB"
    assert len(obs) == 2


def test_build_observations_missing_columns_raises():
    bars = pd.DataFrame(
        {"timestamp": [datetime(2026, 2, 10, 12, tzinfo=NY)], "symbol": ["AAA"]}
    )
    with pytest.raises(ValueError, match="bars missing required columns"):
        build_observations(bars, now=AS_OF)


def test_build_observations_excludes_nonpositive_prices():
    rows = session_bars(date(2026, 2, 10), "AAA", overrides={(12, 0): (0.0, 101.0)})
    rows += session_bars(date(2026, 2, 10), "BBB", base=200.0)
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)
    assert "AAA" not in obs["symbol"].values
    assert "BBB" in obs["symbol"].values


def test_build_observations_tie_is_loss():
    """Exact tie (exit == entry) must produce win=False."""
    rows = session_bars(
        date(2026, 2, 10),
        "TIE",
        overrides={(12, 0): (100.0, 100.0), (15, 30): (100.0, 100.0)},
    )
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)
    assert len(obs) == 1
    # Use bool() to coerce numpy.bool_ -> Python bool before identity check.
    assert bool(obs.iloc[0]["win"]) is False


def test_build_observations_missing_exit_excluded():
    """Stock-days with no 15:30 bar (e.g. a 13:00 early close) are excluded."""
    rows = [
        r
        for r in session_bars(date(2026, 11, 27), "CCC")
        if r["timestamp"].hour < 13  # half-day session
    ]
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)
    assert len(obs) == 0


def test_build_observations_duplicate_entry_bars_raises():
    """Two 12:00 bars for the same session/symbol must raise, not Cartesian-join."""
    rows = session_bars(date(2026, 2, 10), "AAA")
    rows.append(
        {
            "timestamp": datetime(2026, 2, 10, 12, 0, tzinfo=NY),
            "symbol": "AAA",
            "open": 102.0,
            "close": 103.0,
        }
    )
    with pytest.raises(ValueError, match="duplicate 12:00 entry bars"):
        build_observations(pd.DataFrame(rows), now=AS_OF)


def test_build_observations_duplicate_exit_bars_raises():
    """Two 15:30 bars for the same session/symbol must raise ValueError."""
    rows = session_bars(date(2026, 2, 10), "AAA")
    rows.append(
        {
            "timestamp": datetime(2026, 2, 10, 15, 30, tzinfo=NY),
            "symbol": "AAA",
            "open": 106.0,
            "close": 107.0,
        }
    )
    with pytest.raises(ValueError, match="duplicate 15:30 exit bars"):
        build_observations(pd.DataFrame(rows), now=AS_OF)


def test_build_observations_pacific_time_converted_to_new_york():
    """09:00 PT == 12:00 ET (entry) and 12:30 PT == 15:30 ET (exit).

    Bars stamped in Pacific time must be converted before matching, so the
    Pacific 09:00 bar is the entry -- not the Pacific 12:00 bar, which is
    15:00 ET and is not a bar this study uses.
    """
    pt_grid = [(h - 3, m) for (h, m) in GRID_30M]
    rows = session_bars(
        date(2026, 2, 10),
        "ZZZ",
        overrides={
            (9, 0): (50.0, 51.0),  # 12:00 ET -> entry
            (12, 0): (777.0, 778.0),  # 15:00 ET -> not used
            (12, 30): (55.0, 56.0),  # 15:30 ET -> exit
        },
        grid=pt_grid,
        tz=PT,
    )

    obs = build_observations(pd.DataFrame(rows), now=AS_OF)

    assert len(obs) == 1
    row = obs.iloc[0]
    assert row["symbol"] == "ZZZ"
    assert row["entry_price"] == pytest.approx(50.0)
    assert row["exit_price"] == pytest.approx(56.0)
    assert bool(row["win"]) is True


def test_build_observations_dst_winter_and_summer_sessions():
    """Both EST and EDT sessions must match on wall-clock time."""
    rows = session_bars(
        date(2026, 1, 20),
        "AAA",
        overrides={(12, 0): (10.0, 10.5), (15, 30): (11.0, 12.0)},
    )
    rows += session_bars(
        date(2026, 7, 20),
        "AAA",
        overrides={(12, 0): (20.0, 20.5), (15, 30): (21.0, 22.0)},
    )
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)
    assert list(obs["session"]) == [date(2026, 1, 20), date(2026, 7, 20)]
    assert list(obs["exit_price"]) == pytest.approx([12.0, 22.0])


def test_build_observations_tz_naive_treated_as_new_york():
    rows = session_bars(
        date(2026, 2, 10),
        "AAA",
        overrides={(12, 0): (100.0, 101.0), (15, 30): (104.0, 105.0)},
    )
    for row in rows:
        row["timestamp"] = row["timestamp"].replace(tzinfo=None)
    obs = build_observations(pd.DataFrame(rows), now=AS_OF)
    assert len(obs) == 1
    assert obs.iloc[0]["exit_price"] == pytest.approx(105.0)


# ---------------------------------------------------------------------------
# Currently-forming exit bars
# ---------------------------------------------------------------------------


def test_build_observations_drops_session_whose_exit_bar_is_still_forming():
    """A 15:30 bar mid-formation at 15:45 must not be treated as a close."""
    rows = session_bars(
        date(2026, 8, 12),
        "AAA",
        overrides={(12, 0): (100.0, 101.0), (15, 30): (104.0, 105.0)},
    )
    rows += session_bars(
        date(2026, 8, 13),
        "AAA",
        overrides={(12, 0): (110.0, 111.0), (15, 30): (114.0, 115.0)},
    )

    obs = build_observations(
        pd.DataFrame(rows), now=datetime(2026, 8, 13, 15, 45, tzinfo=NY)
    )

    assert list(obs["session"]) == [date(2026, 8, 12)]


def test_build_observations_keeps_session_when_exit_interval_just_closed():
    """At exactly 16:00 ET the 15:30-16:00 bar is complete and must be kept."""
    rows = session_bars(
        date(2026, 8, 13),
        "AAA",
        overrides={(12, 0): (110.0, 111.0), (15, 30): (114.0, 115.0)},
    )

    obs = build_observations(
        pd.DataFrame(rows), now=datetime(2026, 8, 13, 16, 0, tzinfo=NY)
    )

    assert list(obs["session"]) == [date(2026, 8, 13)]


def test_filter_incomplete_exit_sessions_requires_tz_aware_now():
    obs = pd.DataFrame(
        {
            "session": [date(2026, 8, 13)],
            "symbol": ["AAA"],
            "return": [0.01],
            "win": [True],
        }
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        filter_incomplete_exit_sessions(obs, datetime(2026, 8, 13, 16, 0))


def test_filter_incomplete_exit_sessions_accepts_other_timezones():
    """A UTC as-of instant is converted, not compared naively."""
    obs = pd.DataFrame(
        {
            "session": [date(2026, 8, 13)],
            "symbol": ["AAA"],
            "return": [0.01],
            "win": [True],
        }
    )
    utc = ZoneInfo("UTC")
    # 19:59Z == 15:59 EDT -> exit bar still forming
    still_forming = filter_incomplete_exit_sessions(
        obs, datetime(2026, 8, 13, 19, 59, tzinfo=utc)
    )
    # 20:00Z == 16:00 EDT -> complete
    complete = filter_incomplete_exit_sessions(
        obs, datetime(2026, 8, 13, 20, 0, tzinfo=utc)
    )
    assert len(still_forming) == 0
    assert len(complete) == 1


def test_filter_incomplete_exit_sessions_empty_frame_is_passthrough():
    obs = pd.DataFrame(columns=["session", "symbol", "return", "win"])
    out = filter_incomplete_exit_sessions(obs, datetime(2026, 8, 13, 16, 0, tzinfo=NY))
    assert out.empty


def test_exit_interval_end_is_dst_aware():
    """16:00 ET is UTC-05:00 in winter and UTC-04:00 in summer."""
    winter = exit_interval_end(date(2026, 1, 20))
    summer = exit_interval_end(date(2026, 7, 20))
    assert winter.hour == 16 and winter.minute == 0
    assert summer.hour == 16 and summer.minute == 0
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)


# ---------------------------------------------------------------------------
# summarize_observations
# ---------------------------------------------------------------------------


def test_summary_reports_stock_day_and_equal_weight_basket_rates():
    observations = pd.DataFrame(
        {
            "session": pd.to_datetime(
                ["2026-08-10", "2026-08-10", "2026-08-11", "2026-08-11"]
            ).date,
            "symbol": ["AAA", "BBB", "AAA", "BBB"],
            "return": [0.02, -0.01, -0.02, -0.01],
            "win": [True, False, False, False],
        }
    )

    summary = summarize_observations(observations, expected_symbols=2)

    # Rates and coverage
    assert summary.stock_day_win_rate_pct == pytest.approx(25.0)
    assert summary.basket_day_win_rate_pct == pytest.approx(50.0)
    assert summary.valid_stock_days == 4
    assert summary.coverage_pct == pytest.approx(100.0)
    # Return statistics
    # mean([0.02, -0.01, -0.02, -0.01]) = -0.005 -> -0.5 %
    assert summary.mean_stock_day_return_pct == pytest.approx(-0.5)
    # median(sorted: -0.02, -0.01, -0.01, 0.02) = (-0.01 + -0.01)/2 = -0.01 -> -1.0 %
    assert summary.median_stock_day_return_pct == pytest.approx(-1.0)
    # basket daily: 2026-08-10 = mean(0.02,-0.01)=0.005; 2026-08-11 = mean(-0.02,-0.01)=-0.015
    # cumulative: (1.005)(0.985) - 1 = -0.010075 -> -1.0075 %
    assert summary.cumulative_basket_return_pct == pytest.approx(-1.0075, rel=1e-4)
    # Session and symbol metadata
    assert summary.start_session == date(2026, 8, 10)
    assert summary.end_session == date(2026, 8, 11)
    assert summary.sessions == 2
    assert summary.symbols_observed == 2
    assert summary.expected_stock_days == 4


def test_summary_missing_columns_raises():
    """Observations lacking any of session/symbol/return/win must raise ValueError."""
    obs_no_win = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10"]).date,
            "symbol": ["AAA"],
            "return": [0.01],
            # "win" deliberately omitted
        }
    )
    with pytest.raises(ValueError, match="observations missing required columns"):
        summarize_observations(obs_no_win, expected_symbols=1)


def test_summary_missing_multiple_columns_names_all():
    """Error message must name every missing column, not just the first."""
    obs_bare = pd.DataFrame({"session": pd.to_datetime(["2026-08-10"]).date})
    with pytest.raises(ValueError, match="observations missing required columns"):
        summarize_observations(obs_bare, expected_symbols=1)


def test_summary_empty_observations_raises():
    obs = pd.DataFrame(columns=["session", "symbol", "return", "win"])
    with pytest.raises(ValueError, match="no complete stock-days"):
        summarize_observations(obs, expected_symbols=2)


def test_summary_nonpositive_expected_symbols_raises():
    obs = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10"]).date,
            "symbol": ["AAA"],
            "return": [0.01],
            "win": [True],
        }
    )
    with pytest.raises(ValueError, match="expected_symbols must be positive"):
        summarize_observations(obs, expected_symbols=0)


def test_summary_valid_stock_days_exceeds_expected_raises():
    """valid_stock_days > n_sessions * expected_symbols must raise ValueError."""
    observations = pd.DataFrame(
        {
            # 3 stock-days in 1 session but expected_symbols=2 -> exceeds
            "session": pd.to_datetime(["2026-08-10", "2026-08-10", "2026-08-10"]).date,
            "symbol": ["AAA", "BBB", "CCC"],
            "return": [0.01, 0.02, 0.03],
            "win": [True, True, True],
        }
    )
    with pytest.raises(
        ValueError, match="valid_stock_days.*exceeds expected_stock_days"
    ):
        summarize_observations(observations, expected_symbols=2)


def test_summary_drift_summary_is_immutable():
    observations = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10", "2026-08-10"]).date,
            "symbol": ["AAA", "BBB"],
            "return": [0.02, -0.01],
            "win": [True, False],
        }
    )
    summary = summarize_observations(observations, expected_symbols=2)
    assert isinstance(summary, DriftSummary)
    with pytest.raises((TypeError, AttributeError)):
        summary.sessions = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# normalize_yfinance_bars
# ---------------------------------------------------------------------------


def test_normalize_yfinance_bars_returns_long_contract():
    """Realistic two-symbol (symbol, price_field) frame -> long contract."""
    index = pd.DatetimeIndex(["2026-08-10T16:00:00Z", "2026-08-10T19:30:00Z"])
    columns = pd.MultiIndex.from_product([["AAA", "BBB"], ["Open", "Close"]])
    raw = pd.DataFrame(
        [[100.0, 101.0, 200.0, 201.0], [104.0, 105.0, 196.0, 196.0]],
        index=index,
        columns=columns,
    )

    result = normalize_yfinance_bars(raw)

    assert list(result.columns) == ["timestamp", "symbol", "open", "close"]
    assert set(result["symbol"]) == {"AAA", "BBB"}


def test_normalize_yfinance_bars_price_field_first_layout():
    """Yfinance >=0.2 uses (price_field, symbol) ordering -- should normalize correctly."""
    index = pd.DatetimeIndex(["2026-08-10T16:00:00Z"])
    columns = pd.MultiIndex.from_product([["Open", "Close"], ["AAA", "BBB"]])
    raw = pd.DataFrame(
        [[100.0, 200.0, 101.0, 201.0]],
        index=index,
        columns=columns,
    )

    result = normalize_yfinance_bars(raw)

    assert list(result.columns) == ["timestamp", "symbol", "open", "close"]
    assert set(result["symbol"]) == {"AAA", "BBB"}


def test_normalize_yfinance_bars_non_multiindex_raises():
    """Flat columns must raise ValueError."""
    raw = pd.DataFrame({"open": [100.0], "close": [101.0]})
    with pytest.raises(ValueError, match="MultiIndex"):
        normalize_yfinance_bars(raw)


# ---------------------------------------------------------------------------
# _promote_single_ticker_columns
# ---------------------------------------------------------------------------


def test_promote_single_ticker_columns_builds_multiindex():
    """Flat-column single-ticker result must be promoted to (symbol, price_field) MultiIndex."""
    index = pd.DatetimeIndex(["2026-08-10T16:00:00Z", "2026-08-10T19:30:00Z"])
    flat = pd.DataFrame(
        {"Open": [100.0, 104.0], "Close": [101.0, 105.0]},
        index=index,
    )

    promoted = _promote_single_ticker_columns(flat, "AAPL")

    assert isinstance(promoted.columns, pd.MultiIndex)
    assert list(promoted.columns.get_level_values(0).unique()) == ["AAPL"]
    assert "Open" in promoted.columns.get_level_values(1)


def test_promote_single_ticker_then_normalize_yields_long_contract():
    """Promote + normalize must produce the Task-1 long contract for a single ticker."""
    index = pd.DatetimeIndex(["2026-08-10T16:00:00Z", "2026-08-10T19:30:00Z"])
    flat = pd.DataFrame(
        {"Open": [100.0, 104.0], "Close": [101.0, 105.0]},
        index=index,
    )
    promoted = _promote_single_ticker_columns(flat, "AAPL")
    result = normalize_yfinance_bars(promoted)

    assert list(result.columns) == ["timestamp", "symbol", "open", "close"]
    assert list(result["symbol"]) == ["AAPL", "AAPL"]


# ---------------------------------------------------------------------------
# fetch_top_symbols (monkeypatched)
# ---------------------------------------------------------------------------


def _make_weight_table(symbols, weights=None):
    if weights is None:
        weights = list(range(len(symbols), 0, -1))
    return [pd.DataFrame({"Symbol": symbols, "Weight": weights})]


def test_fetch_top_symbols_dot_becomes_dash(monkeypatch):
    """Dots in ticker symbols must be converted to Yahoo dashes."""
    monkeypatch.setattr(
        "pandas.read_html",
        lambda url, **kwargs: _make_weight_table(["AAPL", "BRK.B", "GOOGL"]),
    )

    result = fetch_top_symbols(3)

    assert "BRK-B" in result
    assert "BRK.B" not in result


def test_fetch_top_symbols_preserves_weight_order(monkeypatch):
    """Symbols must be returned ordered by descending Weight, not source-table order."""
    monkeypatch.setattr(
        "pandas.read_html",
        lambda url, **kwargs: _make_weight_table(
            ["AMZN", "MSFT", "NVDA", "AAPL"], weights=[1.0, 2.0, 3.0, 4.0]
        ),
    )

    result = fetch_top_symbols(4)

    assert result == ["AAPL", "NVDA", "MSFT", "AMZN"]


def test_fetch_top_symbols_percentage_string_weights(monkeypatch):
    """Weight values supplied as percentage strings must be parsed correctly."""
    monkeypatch.setattr(
        "pandas.read_html",
        lambda url, **kwargs: _make_weight_table(
            ["AAPL", "NVDA", "MSFT"],
            weights=["7.12%", "6.50%", "6.01%"],
        ),
    )

    result = fetch_top_symbols(3)

    assert result == ["AAPL", "NVDA", "MSFT"]


def test_fetch_top_symbols_deduplicates(monkeypatch):
    """Duplicate symbols in the source table must be deduplicated (first-seen kept)."""
    monkeypatch.setattr(
        "pandas.read_html",
        lambda url, **kwargs: _make_weight_table(
            ["AAPL", "NVDA", "AAPL"],
            weights=[7.0, 6.0, 5.0],
        ),
    )

    result = fetch_top_symbols(2)

    assert result.count("AAPL") == 1
    assert result == ["AAPL", "NVDA"]


def test_fetch_top_symbols_slickcharts_fails_raises_runtime_error(monkeypatch):
    """If Slickcharts raises, a RuntimeError with a clear message must be raised."""
    monkeypatch.setattr(
        "pandas.read_html",
        lambda url, **kwargs: (_ for _ in ()).throw(OSError("connection refused")),
    )

    with pytest.raises(RuntimeError, match="Slickcharts"):
        fetch_top_symbols(count=5)


def test_fetch_top_symbols_insufficient_symbols_raises_runtime_error(monkeypatch):
    """If Slickcharts returns fewer than count symbols, RuntimeError must be raised."""
    monkeypatch.setattr(
        "pandas.read_html",
        lambda url, **kwargs: [pd.DataFrame({"other": [1]})],
    )

    with pytest.raises(RuntimeError, match="Slickcharts"):
        fetch_top_symbols(count=100)


# ---------------------------------------------------------------------------
# Requested-window accounting
# ---------------------------------------------------------------------------


def test_compute_requested_window_six_months():
    start, end = compute_requested_window(6, date(2026, 8, 13))
    assert start == date(2026, 2, 1)
    assert end == date(2026, 8, 13)


def test_compute_requested_window_wraps_year():
    start, _ = compute_requested_window(9, date(2026, 8, 13))
    assert start == date(2025, 11, 1)


def test_compute_requested_window_rejects_nonpositive_months():
    with pytest.raises(ValueError, match="months must be positive"):
        compute_requested_window(0, date(2026, 8, 13))


def test_assess_window_completeness_within_tolerance():
    is_partial, shortfall = assess_window_completeness(
        date(2026, 2, 1), date(2026, 2, 3), tolerance_days=7
    )
    assert is_partial is False
    assert shortfall == 2


def test_assess_window_completeness_beyond_tolerance():
    is_partial, shortfall = assess_window_completeness(
        date(2026, 2, 1), date(2026, 6, 16), tolerance_days=7
    )
    assert is_partial is True
    assert shortfall == 135


def test_assess_window_completeness_exactly_at_tolerance_is_complete():
    is_partial, shortfall = assess_window_completeness(
        date(2026, 2, 1), date(2026, 2, 8), tolerance_days=7
    )
    assert is_partial is False
    assert shortfall == 7


def test_enforce_window_completeness_raises_without_flag():
    with pytest.raises(RuntimeError) as excinfo:
        enforce_window_completeness(
            date(2026, 2, 1), date(2026, 6, 16), allow_partial=False
        )
    message = str(excinfo.value)
    assert "INCOMPLETE WINDOW" in message
    assert "2026-02-01" in message
    assert "2026-06-16" in message
    assert "--allow-partial-window" in message
    assert "60" in message


def test_enforce_window_completeness_allows_with_flag():
    assert (
        enforce_window_completeness(
            date(2026, 2, 1), date(2026, 6, 16), allow_partial=True
        )
        is True
    )


def test_enforce_window_completeness_complete_window_is_not_partial():
    assert (
        enforce_window_completeness(
            date(2026, 2, 1), date(2026, 2, 2), allow_partial=False
        )
        is False
    )


def test_window_tolerance_default_is_seven_days():
    assert WINDOW_TOLERANCE_DAYS == 7


# ---------------------------------------------------------------------------
# Download chunking / interval
# ---------------------------------------------------------------------------


def test_intraday_chunks_are_end_anchored_and_cover_range():
    chunks = intraday_chunks(date(2026, 2, 1), date(2026, 8, 14), max_chunk_days=59)
    assert chunks[0][1] == date(2026, 8, 14)
    assert chunks[0][0] == date(2026, 6, 16)  # newest chunk fits inside retention
    assert chunks[-1][0] == date(2026, 2, 1)
    for start, end in chunks:
        assert (end - start).days <= 59
    # contiguous, newest first
    for earlier, later in zip(chunks[1:], chunks[:-1]):
        assert earlier[1] == later[0]


def test_intraday_chunks_validates_arguments():
    with pytest.raises(ValueError, match="max_chunk_days must be positive"):
        intraday_chunks(date(2026, 2, 1), date(2026, 8, 14), max_chunk_days=0)
    with pytest.raises(ValueError, match="empty range"):
        intraday_chunks(date(2026, 8, 14), date(2026, 8, 14))


def _fake_yf_frame(session: date, symbol: str = "AAA") -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [
            datetime(session.year, session.month, session.day, hour, minute, tzinfo=NY)
            for hour, minute in GRID_30M
        ]
    )
    columns = pd.MultiIndex.from_product([[symbol], ["Open", "Close"]])
    data = [[100.0 + i, 100.5 + i] for i in range(len(index))]
    return pd.DataFrame(data, index=index, columns=columns)


def test_download_intraday_bars_requests_30m_and_stops_at_retention(monkeypatch):
    """REVERSE-LOCK: the adapter must request 30-minute bars, never 60-minute.

    It must also stop once a chunk beyond the provider's retention returns
    nothing, instead of paging pointlessly through the whole request.
    """
    calls: list[dict] = []

    def _download(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _fake_yf_frame(date(2026, 8, 12))
        return pd.DataFrame()

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=_download))

    bars = download_intraday_bars(["AAA"], date(2026, 2, 1), date(2026, 8, 13))

    assert [c["interval"] for c in calls] == [INTRADAY_INTERVAL, INTRADAY_INTERVAL]
    assert INTRADAY_INTERVAL == "30m"
    assert len(calls) == 2  # stopped after the first out-of-retention chunk
    assert list(bars.columns) == ["timestamp", "symbol", "open", "close"]
    assert len(bars) == len(GRID_30M)


def test_download_intraday_bars_empty_everywhere_returns_empty_contract(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda **kwargs: pd.DataFrame()),
    )

    bars = download_intraday_bars(["AAA"], date(2026, 8, 1), date(2026, 8, 13))

    assert bars.empty
    assert list(bars.columns) == ["timestamp", "symbol", "open", "close"]


def test_download_intraday_bars_deduplicates_overlapping_chunks(monkeypatch):
    """Overlapping chunk results must not double-count a bar."""
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda **kwargs: _fake_yf_frame(date(2026, 8, 12))),
    )

    bars = download_intraday_bars(
        ["AAA"], date(2026, 6, 1), date(2026, 8, 13), max_chunk_days=30
    )

    assert len(bars) == len(GRID_30M)


# ---------------------------------------------------------------------------
# CLI (monkeypatched -- no network)
# ---------------------------------------------------------------------------


def _bars_for_sessions(sessions: list[date]) -> pd.DataFrame:
    rows: list[dict] = []
    for symbol, base in [("AAA", 100.0), ("BBB", 200.0)]:
        for session in sessions:
            rows += session_bars(
                session,
                symbol,
                overrides={
                    (12, 0): (base, base + 1.0),
                    (15, 30): (base + 1.0, base + 2.0),
                },
                base=base,
            )
    return pd.DataFrame(rows)


def _complete_window_sessions() -> list[date]:
    """Two sessions starting at the requested six-month window start."""
    start, _ = compute_requested_window(6, date.today())
    return [start, start + timedelta(days=1)]


def _partial_window_sessions() -> list[date]:
    """Two recent sessions, far short of the requested six-month window."""
    recent = date.today() - timedelta(days=30)
    return [recent, recent + timedelta(days=1)]


def _patch_sources(monkeypatch, sessions: list[date]) -> None:
    monkeypatch.setattr(
        "top50_intraday_drift.fetch_top_symbols",
        lambda count: ["AAA", "BBB"][:count],
    )
    monkeypatch.setattr(
        "top50_intraday_drift.download_intraday_bars",
        lambda symbols, start, end: _bars_for_sessions(sessions),
    )


def test_cli_exit_zero_and_labels_present(monkeypatch, capsys):
    """CLI must exit 0 and print Stock-day accuracy and Basket-day accuracy."""
    _patch_sources(monkeypatch, _complete_window_sessions())

    rc = cli_main(["--top", "2", "--months", "6"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Stock-day accuracy" in captured.out
    assert "Basket-day accuracy" in captured.out
    assert "PARTIAL WINDOW" not in captured.out


def test_cli_survivorship_warning_mentions_leavers_and_joiners(monkeypatch, capsys):
    """Survivorship warning must mention both leavers (LEFT) and joiners (JOINED)."""
    _patch_sources(monkeypatch, _complete_window_sessions())

    cli_main(["--top", "2", "--months", "6"])

    captured = capsys.readouterr()
    assert "LEFT" in captured.out
    assert "JOINED" in captured.out


def test_cli_no_transaction_cost_warning_mentions_exact_bar_times(monkeypatch, capsys):
    """Transaction-cost warning must name the 12:00 ET open and 15:30 ET close."""
    _patch_sources(monkeypatch, _complete_window_sessions())

    cli_main(["--top", "2", "--months", "6"])

    out = capsys.readouterr().out.lower()
    assert "adjusted open" in out
    assert "adjusted close" in out
    assert "12:00 et" in out
    assert "15:30 et" in out


def test_cli_never_claims_hourly_or_top_of_hour(monkeypatch, capsys):
    """No output may describe the study as hourly / top-of-the-hour."""
    _patch_sources(monkeypatch, _complete_window_sessions())

    cli_main(["--top", "2", "--months", "6"])

    out = capsys.readouterr().out.lower()
    assert "hourly" not in out
    assert "top of the hour" not in out
    assert "15:00 et" not in out


def test_cli_partial_window_fails_loudly_by_default(monkeypatch, capsys):
    """A short window must be a hard error, never a silently relabelled result."""
    _patch_sources(monkeypatch, _partial_window_sessions())

    rc = cli_main(["--top", "2", "--months", "6"])

    assert rc == 1
    captured = capsys.readouterr()
    assert "INCOMPLETE WINDOW" in captured.err
    assert "--allow-partial-window" in captured.err
    assert "Stock-day accuracy" not in captured.out


def test_cli_partial_window_allowed_is_labelled(monkeypatch, capsys):
    """With the flag the run succeeds but is labelled PARTIAL WINDOW with dates."""
    sessions = _partial_window_sessions()
    _patch_sources(monkeypatch, sessions)

    rc = cli_main(["--top", "2", "--months", "6", "--allow-partial-window"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "PARTIAL WINDOW" in out
    assert str(sessions[0]) in out  # actual first session printed
    assert str(sessions[-1]) in out  # actual last session printed
    assert "(PARTIAL WINDOW)" in out  # headline percentages are labelled
    assert "not a six-month" in out.lower()


def test_cli_slickcharts_failure_exits_error(monkeypatch):
    """If fetch_top_symbols raises RuntimeError, CLI must return non-zero."""

    def _bad_fetch(count):
        raise RuntimeError("Slickcharts request failed")

    monkeypatch.setattr("top50_intraday_drift.fetch_top_symbols", _bad_fetch)

    rc = cli_main(["--top", "2", "--months", "6"])

    assert rc != 0


def test_cli_empty_download_exits_error(monkeypatch, capsys):
    """Empty bar download must cause CLI to return non-zero with a clear reason."""
    monkeypatch.setattr(
        "top50_intraday_drift.fetch_top_symbols",
        lambda count: ["AAA", "BBB"][:count],
    )
    monkeypatch.setattr(
        "top50_intraday_drift.download_intraday_bars",
        lambda symbols, start, end: pd.DataFrame(
            columns=["timestamp", "symbol", "open", "close"]
        ),
    )

    rc = cli_main(["--top", "2", "--months", "6"])

    assert rc != 0
    assert "30m" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# run_study
# ---------------------------------------------------------------------------


def test_run_study_reports_window_metadata(monkeypatch):
    sessions = _complete_window_sessions()
    _patch_sources(monkeypatch, sessions)

    result = run_study(count=2, months=6, now=datetime.now(tz=NY))

    assert result.partial_window is False
    assert result.requested_start == compute_requested_window(6, date.today())[0]
    assert result.actual_start == sessions[0]
    assert result.actual_end == sessions[-1]
    assert result.summary.symbols_observed == 2


def test_run_study_partial_window_raises_without_flag(monkeypatch):
    _patch_sources(monkeypatch, _partial_window_sessions())

    with pytest.raises(RuntimeError, match="INCOMPLETE WINDOW"):
        run_study(count=2, months=6, now=datetime.now(tz=NY))


def test_run_study_rejects_naive_now(monkeypatch):
    _patch_sources(monkeypatch, _complete_window_sessions())

    with pytest.raises(ValueError, match="timezone-aware"):
        run_study(count=2, months=6, now=datetime(2026, 8, 13, 16, 0))


def test_run_study_drops_forming_session_via_injected_now(monkeypatch):
    """An as-of instant before the exit bar closes must exclude that session."""
    start, _ = compute_requested_window(6, date.today())
    sessions = [start, date.today()]
    _patch_sources(monkeypatch, sessions)

    result = run_study(
        count=2,
        months=6,
        now=datetime.combine(date.today(), datetime.min.time(), tzinfo=NY).replace(
            hour=15, minute=45
        ),
    )

    assert result.actual_end == start
    assert date.today() not in set(result.observations["session"])
