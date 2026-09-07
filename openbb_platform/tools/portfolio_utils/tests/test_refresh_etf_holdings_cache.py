"""Unit tests for ``portfolio_utils/refresh_etf_holdings_cache.py``.

All tests are offline -- the obb provider call is mocked, the DB connection
is patched, and no live network/cache writes happen. Mirrors the
``test_enrich_cusip_figi.py`` test patterns (sys.path bootstrap,
MagicMock-based fakes).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

# Make the portfolio_utils inner package importable.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_PKG_DIR, "portfolio_utils")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# Repo root sits 4 levels above the tests dir.
_REPO_ROOT = os.path.abspath(os.path.join(_PKG_DIR, "..", "..", ".."))
for _p in (
    os.path.join(_REPO_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(_REPO_ROOT, "openbb_platform", "extensions", "techtrade"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import refresh_etf_holdings_cache as tool  # noqa: E402

# ---------------------------------------------------------------------------
# L9 regression: SPDR_SECTORS is derived from techtrade GICS_SECTOR_ETFS
# ---------------------------------------------------------------------------


def test_spdr_sectors_matches_techtrade_gics_sector_etfs():
    """SPDR_SECTORS must equal the set of techtrade's GICS_SECTOR_ETFS values (L9)."""
    from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS

    assert set(tool.SPDR_SECTORS) == set(GICS_SECTOR_ETFS.values()), (
        "SPDR_SECTORS drift detected. Either (a) techtrade's GICS_SECTOR_ETFS "
        "changed -- update the fallback constant in refresh_etf_holdings_cache.py, "
        "or (b) the module's runtime derivation broke."
    )


def test_spdr_sectors_has_eleven_tickers():
    """The GICS taxonomy has 11 sectors; the SPDR tuple must reflect that."""
    assert len(tool.SPDR_SECTORS) == 11


def test_known_etfs_is_superset_of_spdr_sectors():
    """Every SPDR sector ETF must be in KNOWN_ETFS so the portfolio filter accepts it."""
    assert set(tool.SPDR_SECTORS).issubset(tool.KNOWN_ETFS)


def test_known_etfs_excludes_common_non_etfs():
    """Sanity: heavily-held single stocks must not look like ETFs to the filter."""
    for non_etf in ("AAPL", "MSFT", "GOOGL", "NVDA", "META"):
        assert non_etf not in tool.KNOWN_ETFS


# ---------------------------------------------------------------------------
# list_portfolio_etfs: KNOWN_ETFS filter applied to Portfolio_Positions
# ---------------------------------------------------------------------------


def _fake_connection(rows):
    """Return a MagicMock that simulates a fmp_cached get_connection() context."""
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = rows
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False
    return fake_conn


def test_list_portfolio_etfs_filters_by_known_set():
    """Mixed Portfolio_Positions symbols -- only KNOWN_ETFS pass through."""
    rows = [
        {"symbol": "AAPL"},
        {"symbol": "IVV"},
        {"symbol": "MSFT"},
        {"symbol": "QQQ"},
        {"symbol": "VTI"},
        {"symbol": "NVDA"},
    ]
    with patch.object(tool, "_connect", return_value=_fake_connection(rows)):
        result = tool.list_portfolio_etfs(database=None)
    assert result == ["IVV", "QQQ", "VTI"]  # sorted, uppercased, non-ETFs dropped


def test_list_portfolio_etfs_returns_empty_on_db_error():
    """Graceful degradation: connect/read failure -> [] (no exception)."""
    with patch.object(tool, "_connect", side_effect=RuntimeError("DB down")):
        result = tool.list_portfolio_etfs(database=None)
    assert result == []


def test_list_portfolio_etfs_handles_uppercase_inconsistency():
    """Portfolio rows arriving in mixed case still resolve through KNOWN_ETFS."""
    rows = [{"symbol": "ivv"}, {"symbol": "Voo"}, {"symbol": "qqq"}]
    with patch.object(tool, "_connect", return_value=_fake_connection(rows)):
        result = tool.list_portfolio_etfs(database=None)
    assert result == ["IVV", "QQQ", "VOO"]


# ---------------------------------------------------------------------------
# resolve_universe: union + dedup + uppercase + skip-portfolio
# ---------------------------------------------------------------------------


def test_resolve_universe_unions_spdr_portfolio_extras():
    """All three sources should appear in the union, sorted."""
    with patch.object(tool, "list_portfolio_etfs", return_value=["IVV", "QQQ"]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=False,
            extra_etfs=["VOO", "DIA"],
        )
    expected_min = set(tool.SPDR_SECTORS) | {"IVV", "QQQ", "VOO", "DIA"}
    assert set(result) == expected_min
    assert result == sorted(result)


def test_resolve_universe_dedupes():
    """Same ETF arriving from multiple sources appears once."""
    with patch.object(tool, "list_portfolio_etfs", return_value=["XLK", "IVV"]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=False,
            extra_etfs=["XLK", "IVV", "VOO"],
        )
    # XLK is in SPDR_SECTORS AND portfolio AND extras -- still one entry
    assert result.count("XLK") == 1
    assert result.count("IVV") == 1


def test_resolve_universe_uppercases_and_strips_extras():
    """`--etfs ' ivv ,voo,'` -> {'IVV','VOO'}; blank tokens dropped."""
    with patch.object(tool, "list_portfolio_etfs", return_value=[]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=False,
            extra_etfs=[" ivv ", "voo", "", "  "],
        )
    assert "IVV" in result
    assert "VOO" in result
    assert "" not in result
    assert "  " not in result


def test_resolve_universe_skip_portfolio_drops_portfolio_etfs():
    """`--skip-portfolio` ignores Portfolio_Positions entirely."""
    with patch.object(tool, "list_portfolio_etfs", return_value=["IVV", "QQQ"]):
        result = tool.resolve_universe(
            database=None,
            skip_portfolio=True,
            extra_etfs=None,
        )
    assert "IVV" not in result
    assert "QQQ" not in result
    # SPDRs still present
    for spdr in tool.SPDR_SECTORS:
        assert spdr in result


# ---------------------------------------------------------------------------
# refresh_one_etf: dry-run / error handling / data_source extraction
# ---------------------------------------------------------------------------


def test_refresh_one_etf_dry_run_makes_no_obb_call():
    """Dry-run returns a zero tuple without ever touching obb."""
    with patch.dict(sys.modules, {"openbb": MagicMock()}) as mods:
        mods["openbb"].obb.etf.holdings = MagicMock(
            side_effect=AssertionError("obb must NOT be called in dry-run"),
        )
        result = tool.refresh_one_etf("XLK", dry_run=True, api_key=None)
    etf, row_count, data_source, elapsed_ms, error = result
    assert etf == "XLK"
    assert row_count == 0
    assert data_source is None
    assert elapsed_ms == 0.0
    assert error is None


def test_refresh_one_etf_catches_402_returns_error_tuple():
    """A 402 / any exception from obb is caught + returned in the error slot."""
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(
        side_effect=Exception("402 Restricted Endpoint (EtfHoldings)\nmore detail"),
    )
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        result = tool.refresh_one_etf("XLK", dry_run=False, api_key=None)
    etf, row_count, data_source, elapsed_ms, error = result
    assert etf == "XLK"
    assert row_count == 0
    assert data_source is None
    # Error message: first line only (newlines stripped)
    assert "402 Restricted Endpoint" in (error or "")
    assert "\n" not in (error or "")


def test_refresh_one_etf_extracts_data_source_from_first_row_object():
    """When rows are objects with .data_source attr, we read it for tier attribution."""
    fake_row = MagicMock()
    fake_row.data_source = "issuer_ssga"
    fake_result = MagicMock(results=[fake_row, MagicMock(data_source="issuer_ssga")])
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(return_value=fake_result)
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        result = tool.refresh_one_etf("XLK", dry_run=False, api_key=None)
    etf, row_count, data_source, _elapsed, error = result
    assert etf == "XLK"
    assert row_count == 2
    assert data_source == "issuer_ssga"
    assert error is None


def test_refresh_one_etf_extracts_data_source_from_first_row_dict():
    """When rows are dicts (some providers normalize to dicts), still works."""
    fake_result = MagicMock(results=[{"data_source": "fmp", "symbol": "AAPL"}])
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(return_value=fake_result)
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        _, row_count, data_source, _, _ = tool.refresh_one_etf(
            "XLK",
            dry_run=False,
            api_key=None,
        )
    assert row_count == 1
    assert data_source == "fmp"


def test_refresh_one_etf_empty_results_yields_zero_rows_no_error():
    """Empty results is a distinct outcome from an exception (counted as 'empty')."""
    fake_result = MagicMock(results=[])
    fake_obb = MagicMock()
    fake_obb.obb.etf.holdings = MagicMock(return_value=fake_result)
    with patch.dict(sys.modules, {"openbb": fake_obb}):
        _, row_count, data_source, _, error = tool.refresh_one_etf(
            "XLK",
            dry_run=False,
            api_key=None,
        )
    assert row_count == 0
    assert data_source is None
    assert error is None


# ---------------------------------------------------------------------------
# refresh_universe: aggregates stats correctly
# ---------------------------------------------------------------------------


def test_refresh_universe_aggregates_stats_correctly():
    """Mix of populated/errored/empty per-ETF outcomes rolls up into the right counts."""
    outcomes = {
        "XLK": ("XLK", 75, "issuer_ssga", 120.0, None),  # populated
        "XLF": ("XLF", 72, "issuer_ssga", 110.0, None),  # populated
        "IVV": ("IVV", 0, None, 15.0, "402 Restricted"),  # errored
        "QQQ": ("QQQ", 0, None, 20.0, "402 Restricted"),  # errored
        "VTI": ("VTI", 0, None, 80.0, None),  # empty (no rows, no err)
    }
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: outcomes[etf],
    ):
        stats = tool.refresh_universe(
            list(outcomes.keys()),
            dry_run=False,
            api_key=None,
        )
    assert stats == {
        "requested": 5,
        "populated": 2,
        "errored": 2,
        "empty": 1,
        "cancelled": False,
    }


# ---------------------------------------------------------------------------
# --api-key CLI flag runtime effect (bd-2k86)
# ---------------------------------------------------------------------------
#
# Pre-fix the --api-key flag's help text promised env-var override behavior
# ("Override FMP_API_KEY (else env FMP_API_KEY -> user_settings -> none)")
# but the flag was in fact stubbed: refresh_one_etf's api_key parameter had
# ``# noqa: ARG001 - reserved for future explicit-key plumbing`` and the
# resolved value was never threaded into obb.etf.holdings(). Users running
# ``python refresh_etf_holdings_cache.py --api-key TESTKEY`` saw no warning
# that their key was ignored; the tool silently used whatever FMP_API_KEY
# already sat in env / user_settings.
#
# Fix (bead option a): set os.environ['FMP_API_KEY'] in main() before the
# lazy ``from openbb import obb`` import fires, mirroring the --database →
# os.environ['DB_NAME'] pattern that's already present. The obb provider's
# own resolver picks up the env var.


def test_main_sets_fmp_api_key_env_when_flag_provided(monkeypatch):
    """main() must export --api-key to os.environ['FMP_API_KEY'] (bd-2k86).

    The refresh_one_etf collaborator is patched so no live network is hit;
    we only care about what main() did to the environment before that
    collaborator ran.
    """
    # Sentinel value so we can distinguish the CLI-supplied key from any
    # pre-existing env value.
    sentinel = "SENTINEL_FMP_KEY_FROM_CLI"
    # Ensure we start from a known baseline; monkeypatch.delenv + setenv
    # keep the surrounding session env unchanged post-test.
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    argv = [
        "refresh_etf_holdings_cache.py",
        "--dry-run",
        "--skip-portfolio",  # avoid the DB read path
        "--api-key",
        sentinel,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: (etf, 1, "issuer_ssga", 10.0, None),
    ):
        rc = tool.main()

    assert rc == 0
    # This is the load-bearing assertion: main() must have exported the
    # CLI-supplied key so downstream ``from openbb import obb`` sees it.
    assert os.environ.get("FMP_API_KEY") == sentinel, (
        "--api-key flag was not exported to os.environ['FMP_API_KEY']; "
        "the CLI flag remains a silent no-op (bd-2k86)."
    )


def test_main_does_not_export_fmp_api_key_when_flag_absent(monkeypatch):
    """Regression lock: main() must NOT clobber an ambient FMP_API_KEY when the flag is absent."""
    # Pre-existing env value that must survive main().
    monkeypatch.setenv("FMP_API_KEY", "AMBIENT_KEY")
    monkeypatch.delenv("DB_NAME", raising=False)

    argv = [
        "refresh_etf_holdings_cache.py",
        "--dry-run",
        "--skip-portfolio",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: (etf, 1, "issuer_ssga", 10.0, None),
    ):
        rc = tool.main()

    assert rc == 0
    # Ambient env-var must be untouched — the CLI flag is an override, not
    # a clobber-with-empty.
    assert os.environ.get("FMP_API_KEY") == "AMBIENT_KEY"


def test_main_whitespace_only_api_key_does_not_pollute_env(monkeypatch):
    """--api-key '  ' must NOT export whitespace to env (PR #341 review, P3 fix).

    Pre-fix the whitespace-only value was truthy under the ``if args.api_key:``
    guard, so it exported ``'  '`` into ``os.environ['FMP_API_KEY']``. The
    credentials loader's own ``if not value: continue`` truthy check would
    then accept the whitespace and hand it to the provider, which fails
    with an opaque error message far from the mis-configuration. The
    ``.strip()`` guard on both the check and the value blocks this.
    """
    monkeypatch.setenv("FMP_API_KEY", "AMBIENT_KEY")
    monkeypatch.delenv("DB_NAME", raising=False)

    argv = [
        "refresh_etf_holdings_cache.py",
        "--dry-run",
        "--skip-portfolio",
        "--api-key",
        "   ",  # whitespace-only — semantically empty
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: (etf, 1, "issuer_ssga", 10.0, None),
    ):
        rc = tool.main()

    assert rc == 0
    # Whitespace-only override is treated as "no override" — ambient env
    # survives untouched, matching the ``--api-key ""`` (argparse-native
    # falsy default) and no-flag behaviors.
    assert os.environ.get("FMP_API_KEY") == "AMBIENT_KEY"


def test_main_api_key_value_is_stripped(monkeypatch):
    """Leading/trailing whitespace on --api-key must NOT reach os.environ (PR #341 review)."""
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    argv = [
        "refresh_etf_holdings_cache.py",
        "--dry-run",
        "--skip-portfolio",
        "--api-key",
        "  TOKEN_WITH_WHITESPACE  ",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: (etf, 1, "issuer_ssga", 10.0, None),
    ):
        rc = tool.main()

    assert rc == 0
    # Stored value is stripped — no leading/trailing whitespace pollution.
    assert os.environ.get("FMP_API_KEY") == "TOKEN_WITH_WHITESPACE"


# ---------------------------------------------------------------------------
# refresh_universe: cancellation between ETFs (issue #1934)
# ---------------------------------------------------------------------------


def test_refresh_universe_stops_between_etfs_when_cancelled():
    """should_cancel is polled before each ETF; remaining ETFs are left unprocessed."""
    calls: list[str] = []

    def _fake_refresh_one_etf(etf, **_kw):
        calls.append(etf)
        return (etf, 5, "issuer_ssga", 10.0, None)

    # Cancel after the first ETF has been processed.
    cancel_after = {"count": 0}

    def _should_cancel():
        return cancel_after["count"] >= 1

    def _tracking_refresh_one_etf(etf, **kw):
        result = _fake_refresh_one_etf(etf, **kw)
        cancel_after["count"] += 1
        return result

    with patch.object(tool, "refresh_one_etf", side_effect=_tracking_refresh_one_etf):
        stats = tool.refresh_universe(
            ["XLK", "XLF", "XLE", "XLY"],
            dry_run=False,
            api_key=None,
            should_cancel=_should_cancel,
        )

    assert calls == ["XLK"]  # loop stopped before the 2nd ETF
    assert stats["cancelled"] is True
    assert stats["populated"] == 1
    assert stats["requested"] == 4


def test_refresh_universe_cancelled_before_first_etf_processes_nothing():
    """should_cancel() returning True immediately means zero ETFs are refreshed."""
    with patch.object(tool, "refresh_one_etf") as mock_refresh:
        stats = tool.refresh_universe(
            ["XLK", "XLF"],
            dry_run=False,
            api_key=None,
            should_cancel=lambda: True,
        )
    mock_refresh.assert_not_called()
    assert stats == {
        "requested": 2,
        "populated": 0,
        "errored": 0,
        "empty": 0,
        "cancelled": True,
    }


def test_refresh_universe_default_should_cancel_never_stops():
    """Omitting should_cancel behaves exactly as before (no cancellation)."""
    with patch.object(
        tool,
        "refresh_one_etf",
        side_effect=lambda etf, **_kw: (etf, 3, "issuer_ssga", 5.0, None),
    ):
        stats = tool.refresh_universe(["XLK", "XLF"], dry_run=False, api_key=None)
    assert stats["cancelled"] is False
    assert stats["populated"] == 2


def test_refresh_one_etf_holdings_fn_injection_bypasses_openbb_import():
    """holdings_fn lets callers avoid the lazy ``from openbb import obb`` import entirely."""
    fake_row = MagicMock(data_source="fmp_cached")
    fake_result = MagicMock(results=[fake_row])
    calls = []

    def _fake_holdings_fn(etf):
        calls.append(etf)
        return fake_result

    # No sys.modules["openbb"] patch here -- if the code path fell back to the
    # real lazy import it would raise/behave differently, proving injection worked.
    _, row_count, data_source, _, error = tool.refresh_one_etf(
        "XLK", dry_run=False, api_key=None, holdings_fn=_fake_holdings_fn
    )
    assert calls == ["XLK"]
    assert row_count == 1
    assert data_source == "fmp_cached"
    assert error is None


def test_refresh_universe_forwards_holdings_fn_to_each_etf():
    """holdings_fn passed to refresh_universe reaches every refresh_one_etf call."""
    seen_holdings_fns = []

    def _capture_refresh_one_etf(etf, *, dry_run, api_key, holdings_fn=None):
        seen_holdings_fns.append(holdings_fn)
        return (etf, 1, "issuer_ssga", 1.0, None)

    sentinel_fn = lambda etf: None  # noqa: E731
    with patch.object(tool, "refresh_one_etf", side_effect=_capture_refresh_one_etf):
        tool.refresh_universe(
            ["XLK", "XLF"], dry_run=False, api_key=None, holdings_fn=sentinel_fn
        )
    assert seen_holdings_fns == [sentinel_fn, sentinel_fn]


# ---------------------------------------------------------------------------
# run_etf_holdings_warm: structured, importable orchestration (issue #1934)
# ---------------------------------------------------------------------------


def test_run_etf_holdings_warm_success_builds_result():
    """A clean run returns an EtfHoldingsWarmResult with the aggregated counts."""
    result = tool.run_etf_holdings_warm(
        universe=["XLK", "XLF", "QQQ"],
        portfolio_etfs=["QQQ"],
        extra_etfs=None,
        skip_portfolio=False,
        dry_run=False,
        holdings_fn=lambda etf: MagicMock(results=[MagicMock(data_source="fmp")]),
    )
    assert result.requested == 3
    assert result.populated == 3
    assert result.errored == 0
    assert result.cancelled is False
    assert result.spdr_count == len(tool.SPDR_SECTORS)
    assert result.portfolio_etfs == ["QQQ"]
    summary = result.to_summary()
    assert summary["requested"] == 3
    assert summary["populated"] == 3
    # Never persists a credential.
    assert "api_key" not in summary
    assert "credential" not in str(summary).lower()


def test_run_etf_holdings_warm_partial_failure_is_reflected_in_errored_count():
    """A partial per-ETF failure is aggregated into errored, not raised."""

    def _holdings_fn(etf):
        if etf == "QQQ":
            raise RuntimeError("402 Restricted")
        return MagicMock(results=[MagicMock(data_source="fmp")])

    result = tool.run_etf_holdings_warm(
        universe=["XLK", "QQQ"],
        portfolio_etfs=[],
        extra_etfs=None,
        skip_portfolio=True,
        dry_run=False,
        holdings_fn=_holdings_fn,
    )
    assert result.requested == 2
    assert result.populated == 1
    assert result.errored == 1
    assert result.cancelled is False


def test_run_etf_holdings_warm_cancellation_stops_between_etfs():
    """should_cancel propagates from run_etf_holdings_warm through refresh_universe."""
    processed = []

    def _holdings_fn(etf):
        processed.append(etf)
        return MagicMock(results=[MagicMock(data_source="fmp")])

    calls = {"n": 0}

    def _should_cancel():
        calls["n"] += 1
        return calls["n"] > 1  # cancel after the first check passes (before 2nd ETF)

    result = tool.run_etf_holdings_warm(
        universe=["XLK", "XLF", "XLE"],
        portfolio_etfs=[],
        extra_etfs=None,
        skip_portfolio=True,
        dry_run=False,
        holdings_fn=_holdings_fn,
        should_cancel=_should_cancel,
    )
    assert processed == ["XLK"]
    assert result.cancelled is True
    assert result.requested == 3
    assert result.populated == 1


def test_run_etf_holdings_warm_resolves_universe_when_not_supplied():
    """When universe/portfolio_etfs are omitted, injectable resolver functions supply them."""
    resolved_calls = {}

    def _fake_resolve_universe(*, database, skip_portfolio, extra_etfs):
        resolved_calls["resolve_universe"] = (database, skip_portfolio, extra_etfs)
        return ["XLK", "XLF"]

    def _fake_list_portfolio_etfs(database):
        resolved_calls["list_portfolio_etfs"] = database
        return ["XLF"]

    result = tool.run_etf_holdings_warm(
        database="test_db",
        extra_etfs=["ARKK"],
        skip_portfolio=False,
        dry_run=False,
        list_portfolio_etfs_fn=_fake_list_portfolio_etfs,
        resolve_universe_fn=_fake_resolve_universe,
        holdings_fn=lambda etf: MagicMock(results=[MagicMock(data_source="fmp")]),
    )
    assert resolved_calls["resolve_universe"] == ("test_db", False, ["ARKK"])
    assert resolved_calls["list_portfolio_etfs"] == "test_db"
    assert result.universe == ["XLK", "XLF"]
    assert result.portfolio_etfs == ["XLF"]


def test_run_etf_holdings_warm_dry_run_never_calls_holdings_fn():
    """dry_run=True must not invoke the injected holdings_fn (no provider calls)."""
    holdings_fn = MagicMock()
    result = tool.run_etf_holdings_warm(
        universe=["XLK", "XLF"],
        portfolio_etfs=[],
        extra_etfs=None,
        skip_portfolio=True,
        dry_run=True,
        holdings_fn=holdings_fn,
    )
    holdings_fn.assert_not_called()
    assert result.dry_run is True
    assert result.requested == 2
    assert result.populated == 0
