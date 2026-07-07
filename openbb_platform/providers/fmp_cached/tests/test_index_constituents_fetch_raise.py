"""Unit tests for _fetch_from_fmp_api unexpected-response handling — bd-wwvk.

Pre-fix (bd-wwvk) ``_fetch_from_fmp_api`` at
``openbb_fmp_cached/models/index_constituents.py:615`` had:

    if not isinstance(data, list):
        return []

If FMP returned an error object, a rate-limit dict, or any non-list
payload WITHOUT the specific ``Error Message`` key (which line 612
already handled), the fetcher silently returned an empty list.
Downstream this looks identical to a legitimate empty index, and
``_store_in_cache([])`` early-returns without erroring, so the
caller gets an empty universe with no signal about the API
malfunction.

The sibling sync helper at line 420 does the RIGHT thing:

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected API response type: {type(data)}")

Fix: match the sync sibling — raise ``RuntimeError`` on any
non-list response.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from openbb_fmp_cached.models import index_constituents


class _FakeQuery:
    """Minimal stand-in for FMPCachedIndexConstituentsQueryParams."""

    symbol = "sp500"
    historical = False


def _run(coro):
    """Sync wrapper — sidesteps the pytest-asyncio inspect.getsource bug."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Contract 1 — a list response passes through (regression lock).
# ---------------------------------------------------------------------------


def test_fetch_from_fmp_api_list_response_returns_data():
    """A well-formed list response is returned verbatim (regression lock)."""
    expected = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]

    with patch(
        "openbb_core.provider.utils.helpers.amake_request",
        new_callable=AsyncMock,
        return_value=expected,
    ):
        result = _run(
            index_constituents._fetch_from_fmp_api(
                _FakeQuery(), {"fmp_api_key": "fake"}
            )
        )

    assert result == expected


# ---------------------------------------------------------------------------
# Contract 2 — FMP's own "Error Message" dict still raises (unchanged).
# ---------------------------------------------------------------------------


def test_fetch_from_fmp_api_error_message_dict_raises():
    """FMP's documented error-message dict continues to raise (regression lock)."""
    with patch(
        "openbb_core.provider.utils.helpers.amake_request",
        new_callable=AsyncMock,
        return_value={"Error Message": "Invalid API key"},
    ):
        with pytest.raises(RuntimeError, match="Invalid API key"):
            _run(
                index_constituents._fetch_from_fmp_api(
                    _FakeQuery(), {"fmp_api_key": "fake"}
                )
            )


# ---------------------------------------------------------------------------
# Contract 3 — bd-wwvk: unexpected non-list, non-error-message response RAISES.
# ---------------------------------------------------------------------------


def test_fetch_from_fmp_api_raises_on_unexpected_dict():
    """A dict response without 'Error Message' MUST raise (bd-wwvk).

    Pre-fix this returned [] which downstream code interpreted as "index
    has no members" — indistinguishable from a legitimate empty index.
    Post-fix (matching the sibling sync helper at line 420) raises
    RuntimeError so the caller learns about the API malfunction.
    """
    # Common real-world shapes: {"error": "..."}, {"message": "Too Many
    # Requests"}, {"status": "error"} — none use FMP's "Error Message" key.
    with patch(
        "openbb_core.provider.utils.helpers.amake_request",
        new_callable=AsyncMock,
        return_value={"message": "Too Many Requests"},
    ):
        with pytest.raises(RuntimeError, match="[Uu]nexpected|response type|dict"):
            _run(
                index_constituents._fetch_from_fmp_api(
                    _FakeQuery(), {"fmp_api_key": "fake"}
                )
            )


def test_fetch_from_fmp_api_raises_on_string_response():
    """A bare string response (e.g. HTML error page) MUST raise (bd-wwvk)."""
    with patch(
        "openbb_core.provider.utils.helpers.amake_request",
        new_callable=AsyncMock,
        return_value="<html>Service Unavailable</html>",
    ):
        with pytest.raises(RuntimeError, match="[Uu]nexpected|response type|str"):
            _run(
                index_constituents._fetch_from_fmp_api(
                    _FakeQuery(), {"fmp_api_key": "fake"}
                )
            )


def test_fetch_from_fmp_api_raises_on_none_response():
    """A ``None`` response MUST raise (bd-wwvk).

    Pre-fix ``None`` fell through the ``isinstance(data, dict)`` guard
    (None is not a dict), then the ``isinstance(data, list)`` guard
    (None is not a list), and returned [] silently.
    """
    with patch(
        "openbb_core.provider.utils.helpers.amake_request",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(RuntimeError, match="[Uu]nexpected|response type"):
            _run(
                index_constituents._fetch_from_fmp_api(
                    _FakeQuery(), {"fmp_api_key": "fake"}
                )
            )


# ---------------------------------------------------------------------------
# Contract 4 — the raise message MUST name the unexpected type (bd-wwvk).
# ---------------------------------------------------------------------------


def test_fetch_from_fmp_api_raise_message_includes_response_type():
    """The RuntimeError message names the unexpected type so operators can debug (bd-wwvk).

    ``str(type(x))`` gives ``<class 'dict'>`` style; the caller who
    hits this in production needs to know what shape came back to
    diagnose the API misbehavior.
    """
    with patch(
        "openbb_core.provider.utils.helpers.amake_request",
        new_callable=AsyncMock,
        return_value={"error": "some_error_key"},
    ):
        with pytest.raises(RuntimeError) as exc_info:
            _run(
                index_constituents._fetch_from_fmp_api(
                    _FakeQuery(), {"fmp_api_key": "fake"}
                )
            )
        msg = str(exc_info.value)
        assert "dict" in msg.lower(), (
            f"raise message doesn't name the unexpected response type — "
            f"operator has no signal to trace what FMP returned. Got: {msg!r}"
        )
