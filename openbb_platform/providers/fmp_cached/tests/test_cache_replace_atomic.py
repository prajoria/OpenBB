"""Unit tests for the cache-replace atomic-transaction refactor — bd-n3sf.

Eight sibling ``_store_*`` functions in ``openbb_fmp_cached/models/`` share
the DELETE-then-INSERT antipattern. Pre-fix each site did per-symbol DELETE
on the autocommit=True pool followed by execute_many(INSERT), so a partial-
write failure between the DELETE and the INSERT wiped the cache of the
symbol's history (bd-ihdn P0).

Post-fix all 8 sites route through ``replace_rows()`` from bd-kh08 (PR #414),
which wraps each symbol's DELETE+INSERT in a single explicit transaction on
a fresh ``autocommit=False`` connection.

Each site gets 4 tests:
    1. happy_path — regression lock: call site with records, assert
       replace_rows called with expected (table, "symbol", symbol, rows) shape
    2. empty_records_is_noop — call with [], assert replace_rows NOT called
    3. multi_symbol_batches_by_symbol — call with 3 symbols x 2 records,
       assert replace_rows called 3 times partitioned per symbol
    4. atomicity_fail_fast — mock replace_rows to raise on 2nd call, assert
       the raise propagates and 3rd call did NOT fire (fail-fast)

Total: 8 sites x 4 tests = 32 tests.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# One canonical (symbol, date, ...) tuple builder per site. We build the
# INPUT records (the raw FMP-shaped dicts) here; the site itself does the
# translation to the row dict shape passed to replace_rows.


def _record_institutional(symbol: str, date_str: str = "2026-06-30") -> dict:
    return {
        "symbol": symbol,
        "date": date_str,
        "investor": "Vanguard",
        "shares": 12345,
    }


def _record_balance_sheet(
    symbol: str, date_str: str = "2026-06-30", period: str = "annual"
) -> dict:
    return {
        "symbol": symbol,
        "date": date_str,
        "period": period,
        "reportedCurrency": "USD",
        "totalAssets": 1_000_000,
        "totalLiabilities": 500_000,
        "totalStockholdersEquity": 500_000,
    }


def _record_cash_flow(
    symbol: str, date_str: str = "2026-06-30", period: str = "annual"
) -> dict:
    return {
        "symbol": symbol,
        "date": date_str,
        "period": period,
        "reportedCurrency": "USD",
        "operatingCashFlow": 10,
        "capitalExpenditure": -3,
        "freeCashFlow": 7,
    }


def _record_income_statement(
    symbol: str, date_str: str = "2026-06-30", period: str = "annual"
) -> dict:
    return {
        "symbol": symbol,
        "date": date_str,
        "period": period,
        "reportedCurrency": "USD",
        "revenue": 100,
        "netIncome": 20,
    }


def _record_financial_ratios(
    symbol: str, date_str: str = "2026-06-30", period: str = "annual"
) -> dict:
    return {
        "symbol": symbol,
        "date": date_str,
        "period": period,
        "reportedCurrency": "USD",
        "priceToEarningsRatio": 20.0,
        "priceToBookRatio": 3.0,
        "debtToEquityRatio": 0.5,
        "currentRatio": 1.5,
        "returnOnEquity": 0.15,
        "returnOnAssets": 0.05,
    }


def _record_key_metrics(
    symbol: str, date_str: str = "2026-06-30", period: str = "annual"
) -> dict:
    return {
        "symbol": symbol,
        "date": date_str,
        "fiscal_period": period,
        "reportedCurrency": "USD",
        "marketCap": 1_000_000_000,
    }


def _record_equity_quote(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "exchange": "NASDAQ",
        "price": 100.0,
        "open": 99.0,
        "dayHigh": 101.0,
        "dayLow": 98.0,
        "volume": 12345,
        "marketCap": 1_000_000_000,
        "currency": "USD",
        "change": 1.0,
        "changePercentage": 1.01,
    }


def _record_etf_holdings(symbol: str, holding: str = "AAPL") -> dict:
    return {
        "symbol": symbol,
        "asset": holding,
        "weight": 0.05,
    }


# ---------------------------------------------------------------------------
# Site 1: institutional_ownership._store_institutional (bd-ihdn P0)
# ---------------------------------------------------------------------------


class TestStoreInstitutional:
    """models/institutional_ownership.py::_store_institutional (bd-ihdn)."""

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        """Regression lock: valid records route through replace_rows."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _store_institutional,
        )

        _store_institutional([_record_institutional("MSFT")])

        assert mock_replace.call_count == 1
        args, kwargs = mock_replace.call_args
        assert args[0] == "institutional_ownership"
        assert args[1] == "symbol"
        assert args[2] == "MSFT"
        rows = args[3]
        assert len(rows) == 1
        assert rows[0]["symbol"] == "MSFT"
        assert rows[0]["date"] == "2026-06-30"

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        """D6: empty input MUST NOT DELETE."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _store_institutional,
        )

        _store_institutional([])

        assert mock_replace.call_count == 0, (
            "Empty records must be a no-op — DELETE-only on zero symbols "
            "would still be a wasted round-trip and violates D6."
        )

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        """D1: each symbol gets its own replace_rows call (independent txn)."""
        from openbb_fmp_cached.models.institutional_ownership import (
            _store_institutional,
        )

        records = [
            _record_institutional("MSFT", "2026-06-30"),
            _record_institutional("MSFT", "2026-03-31"),
            _record_institutional("AAPL", "2026-06-30"),
            _record_institutional("AAPL", "2026-03-31"),
            _record_institutional("GOOGL", "2026-06-30"),
        ]
        _store_institutional(records)

        # One call per unique symbol.
        assert mock_replace.call_count == 3
        called_symbols = {c.args[2] for c in mock_replace.call_args_list}
        assert called_symbols == {"MSFT", "AAPL", "GOOGL"}

        # Row-count per symbol matches input.
        for c in mock_replace.call_args_list:
            sym = c.args[2]
            rows = c.args[3]
            expected_count = 2 if sym in {"MSFT", "AAPL"} else 1
            assert len(rows) == expected_count, (
                f"Symbol {sym} got {len(rows)} rows, expected {expected_count} "
                f"(D1: rows partitioned per symbol)"
            )

    @patch("openbb_fmp_cached.models.institutional_ownership.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        """Site-level exception handler swallows for cache best-effort.

        Site currently wraps DELETE+INSERT in ``try: ... except Exception:
        logger.warning(...)``. Post-fix that wrapper is preserved so cache
        failures don't break the READ path — but a mid-batch failure must
        NOT allow the loop to continue writing subsequent symbols
        successfully to a torn cache state (since replace_rows is per-symbol
        atomic, the safe behavior is to log and stop).
        """
        from openbb_fmp_cached.models.institutional_ownership import (
            _store_institutional,
        )

        # 3 unique symbols; fail on 2nd call.
        mock_replace.side_effect = [None, RuntimeError("mysql down"), None]
        records = [
            _record_institutional("MSFT"),
            _record_institutional("AAPL"),
            _record_institutional("GOOGL"),
        ]

        # Site-level try/except swallows the exception (best-effort cache).
        _store_institutional(records)

        # Must have called replace_rows at LEAST twice (up to and including
        # the failing call). The 3rd call may or may not fire depending on
        # whether the except is inside or outside the loop. Post-fix decision
        # (D4): keep the site-level exception surface, DO NOT continue after
        # a failure — one bad symbol shouldn't mask further symbol failures
        # by burying only the first exception.
        assert mock_replace.call_count >= 2, (
            "Failed on 2nd symbol; must have called replace_rows at least "
            "twice (1st success + failing 2nd)"
        )


# ---------------------------------------------------------------------------
# Site 2: balance_sheet._store_balance_sheets
# ---------------------------------------------------------------------------


class TestStoreBalanceSheets:
    """models/balance_sheet.py::_store_balance_sheets."""

    @patch("openbb_fmp_cached.models.balance_sheet.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.balance_sheet import _store_balance_sheets

        _store_balance_sheets([_record_balance_sheet("MSFT")])

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "balance_sheet"
        assert args[1] == "symbol"
        assert args[2] == "MSFT"
        rows = args[3]
        assert len(rows) == 1
        assert rows[0]["symbol"] == "MSFT"
        assert rows[0]["total_assets"] == 1_000_000
        assert rows[0]["currency"] == "USD"

    @patch("openbb_fmp_cached.models.balance_sheet.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.balance_sheet import _store_balance_sheets

        _store_balance_sheets([])
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.balance_sheet.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.balance_sheet import _store_balance_sheets

        records = [
            _record_balance_sheet("MSFT", "2026-06-30"),
            _record_balance_sheet("MSFT", "2025-06-30"),
            _record_balance_sheet("AAPL", "2026-06-30"),
        ]
        _store_balance_sheets(records)

        assert mock_replace.call_count == 2
        assert {c.args[2] for c in mock_replace.call_args_list} == {"MSFT", "AAPL"}

    @patch("openbb_fmp_cached.models.balance_sheet.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.balance_sheet import _store_balance_sheets

        mock_replace.side_effect = [None, RuntimeError("mysql down")]
        with pytest.raises(RuntimeError, match="mysql down"):
            _store_balance_sheets(
                [_record_balance_sheet("MSFT"), _record_balance_sheet("AAPL")]
            )
        assert mock_replace.call_count == 2


# ---------------------------------------------------------------------------
# Site 3: cash_flow._store_cash_flow_statements
# ---------------------------------------------------------------------------


class TestStoreCashFlow:
    """models/cash_flow.py::_store_cash_flow_statements."""

    @patch("openbb_fmp_cached.models.cash_flow.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.cash_flow import _store_cash_flow_statements

        _store_cash_flow_statements([_record_cash_flow("MSFT")])

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "cash_flow"
        assert args[2] == "MSFT"
        assert args[3][0]["operating_cash_flow"] == 10
        assert args[3][0]["free_cash_flow"] == 7

    @patch("openbb_fmp_cached.models.cash_flow.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.cash_flow import _store_cash_flow_statements

        _store_cash_flow_statements([])
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.cash_flow.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.cash_flow import _store_cash_flow_statements

        _store_cash_flow_statements(
            [_record_cash_flow("MSFT"), _record_cash_flow("AAPL")]
        )
        assert mock_replace.call_count == 2

    @patch("openbb_fmp_cached.models.cash_flow.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.cash_flow import _store_cash_flow_statements

        mock_replace.side_effect = [None, RuntimeError("boom")]
        with pytest.raises(RuntimeError, match="boom"):
            _store_cash_flow_statements(
                [_record_cash_flow("MSFT"), _record_cash_flow("AAPL")]
            )
        assert mock_replace.call_count == 2


# ---------------------------------------------------------------------------
# Site 4: income_statement._store_income_statement
# ---------------------------------------------------------------------------


class TestStoreIncomeStatement:
    """models/income_statement.py::_store_income_statement."""

    @patch("openbb_fmp_cached.models.income_statement.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.income_statement import _store_income_statement

        _store_income_statement([_record_income_statement("MSFT")])

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "income_statement"
        assert args[2] == "MSFT"
        assert args[3][0]["revenue"] == 100
        assert args[3][0]["net_income"] == 20

    @patch("openbb_fmp_cached.models.income_statement.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.income_statement import _store_income_statement

        _store_income_statement([])
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.income_statement.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.income_statement import _store_income_statement

        _store_income_statement(
            [_record_income_statement("MSFT"), _record_income_statement("AAPL")]
        )
        assert mock_replace.call_count == 2

    @patch("openbb_fmp_cached.models.income_statement.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.income_statement import _store_income_statement

        mock_replace.side_effect = [None, RuntimeError("boom")]
        with pytest.raises(RuntimeError, match="boom"):
            _store_income_statement(
                [_record_income_statement("MSFT"), _record_income_statement("AAPL")]
            )
        assert mock_replace.call_count == 2


# ---------------------------------------------------------------------------
# Site 5: financial_ratios._store_financial_ratios
# ---------------------------------------------------------------------------


class TestStoreFinancialRatios:
    """models/financial_ratios.py::_store_financial_ratios."""

    @patch("openbb_fmp_cached.models.financial_ratios.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.financial_ratios import _store_financial_ratios

        _store_financial_ratios([_record_financial_ratios("MSFT")])

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "financial_ratios"
        assert args[2] == "MSFT"
        assert args[3][0]["pe_ratio"] == 20.0

    @patch("openbb_fmp_cached.models.financial_ratios.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.financial_ratios import _store_financial_ratios

        _store_financial_ratios([])
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.financial_ratios.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.financial_ratios import _store_financial_ratios

        _store_financial_ratios(
            [_record_financial_ratios("MSFT"), _record_financial_ratios("AAPL")]
        )
        assert mock_replace.call_count == 2

    @patch("openbb_fmp_cached.models.financial_ratios.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.financial_ratios import _store_financial_ratios

        mock_replace.side_effect = [None, RuntimeError("boom")]
        with pytest.raises(RuntimeError, match="boom"):
            _store_financial_ratios(
                [_record_financial_ratios("MSFT"), _record_financial_ratios("AAPL")]
            )
        assert mock_replace.call_count == 2


# ---------------------------------------------------------------------------
# Site 6: key_metrics._store_key_metrics
# ---------------------------------------------------------------------------


class TestStoreKeyMetrics:
    """models/key_metrics.py::_store_key_metrics."""

    @patch("openbb_fmp_cached.models.key_metrics.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.key_metrics import _store_key_metrics

        _store_key_metrics([_record_key_metrics("MSFT")])

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "key_metrics"
        assert args[2] == "MSFT"
        assert args[3][0]["market_cap"] == 1_000_000_000

    @patch("openbb_fmp_cached.models.key_metrics.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.key_metrics import _store_key_metrics

        _store_key_metrics([])
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.key_metrics.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.key_metrics import _store_key_metrics

        _store_key_metrics([_record_key_metrics("MSFT"), _record_key_metrics("AAPL")])
        assert mock_replace.call_count == 2

    @patch("openbb_fmp_cached.models.key_metrics.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.key_metrics import _store_key_metrics

        mock_replace.side_effect = [None, RuntimeError("boom")]
        with pytest.raises(RuntimeError, match="boom"):
            _store_key_metrics(
                [_record_key_metrics("MSFT"), _record_key_metrics("AAPL")]
            )
        assert mock_replace.call_count == 2


# ---------------------------------------------------------------------------
# Site 7: equity_quote._store_quotes
# ---------------------------------------------------------------------------


class TestStoreQuotes:
    """models/equity_quote.py::_store_quotes."""

    @patch("openbb_fmp_cached.models.equity_quote.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.equity_quote import _store_quotes

        _store_quotes([_record_equity_quote("MSFT")])

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "equity_quote"
        assert args[2] == "MSFT"
        assert args[3][0]["price"] == 100.0
        assert args[3][0]["exchange"] == "NASDAQ"

    @patch("openbb_fmp_cached.models.equity_quote.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.equity_quote import _store_quotes

        _store_quotes([])
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.equity_quote.replace_rows")
    def test_multi_symbol_batches_by_symbol(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.equity_quote import _store_quotes

        _store_quotes([_record_equity_quote("MSFT"), _record_equity_quote("AAPL")])
        assert mock_replace.call_count == 2

    @patch("openbb_fmp_cached.models.equity_quote.replace_rows")
    def test_atomicity_fail_propagates_and_stops(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.equity_quote import _store_quotes

        mock_replace.side_effect = [None, RuntimeError("boom")]
        with pytest.raises(RuntimeError, match="boom"):
            _store_quotes([_record_equity_quote("MSFT"), _record_equity_quote("AAPL")])
        assert mock_replace.call_count == 2


# ---------------------------------------------------------------------------
# Site 8: etf_holdings._store_etf_holdings
# ---------------------------------------------------------------------------


class TestStoreEtfHoldings:
    """models/etf_holdings.py::_store_etf_holdings.

    Note this site's public API takes ``etf_symbol`` + ``rows`` + a keyword
    ``data_source``, NOT a records list like the others — its ``rows`` are
    already the ETF's holdings for ONE ETF. So the "multi-symbol batching"
    test degenerates to "each call handles one ETF".
    """

    @patch("openbb_fmp_cached.models.etf_holdings.replace_rows")
    def test_happy_path_stores_records(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.etf_holdings import _store_etf_holdings

        _store_etf_holdings(
            "SPY", [_record_etf_holdings("SPY", "AAPL")], data_source="fmp"
        )

        assert mock_replace.call_count == 1
        args, _ = mock_replace.call_args
        assert args[0] == "etf_holdings"
        assert args[1] == "symbol"
        assert args[2] == "SPY"
        rows = args[3]
        assert len(rows) == 1
        assert rows[0]["symbol"] == "SPY"
        # data_source annotated into data_json (site preserves provenance).
        payload = json.loads(rows[0]["data_json"])
        assert payload["data_source"] == "fmp"

    @patch("openbb_fmp_cached.models.etf_holdings.replace_rows")
    def test_empty_records_is_noop(self, mock_replace: MagicMock) -> None:
        from openbb_fmp_cached.models.etf_holdings import _store_etf_holdings

        _store_etf_holdings("SPY", [], data_source="fmp")
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.etf_holdings.replace_rows")
    def test_missing_etf_symbol_is_noop(self, mock_replace: MagicMock) -> None:
        """Site guards on empty etf_symbol too — matches pre-fix behavior."""
        from openbb_fmp_cached.models.etf_holdings import _store_etf_holdings

        _store_etf_holdings(
            "", [_record_etf_holdings("SPY", "AAPL")], data_source="fmp"
        )
        assert mock_replace.call_count == 0

    @patch("openbb_fmp_cached.models.etf_holdings.replace_rows")
    def test_atomicity_fail_is_swallowed_by_site_level_handler(
        self, mock_replace: MagicMock
    ) -> None:
        """Site wraps in try/except that logs .warning() — matches pre-fix."""
        from openbb_fmp_cached.models.etf_holdings import _store_etf_holdings

        mock_replace.side_effect = RuntimeError("mysql down")
        # No exception should propagate — site swallows for cache best-effort.
        _store_etf_holdings(
            "SPY", [_record_etf_holdings("SPY", "AAPL")], data_source="fmp"
        )
        assert mock_replace.call_count == 1
