"""Unit tests locking in ``query.model_copy(update=...)`` — bd-t7p2.

Every cached-fetcher aextract_data() in ``openbb_fmp_cached.models.*``
rebuilds the query object before delegating to the upstream FMP fetcher
for the not-yet-cached symbols. Pre-fix the rebuild hand-listed the known
fields on ``FMP<X>QueryParams``, e.g.::

    fetch_query = FMPFinancialRatiosQueryParams(
        symbol=",".join(symbols_to_fetch),
        ttm=query.ttm,
        period=query.period,
        limit=query.limit,
    )

Any future field added upstream (e.g. ``as_of``, ``fiscal_year``,
``page_size``) is silently dropped on the fetch path — the cached wrapper
would keep working but consistently return upstream data that ignores the
new parameter. Fix: rebuild via ``query.model_copy(update={"symbol":
",".join(symbols_to_fetch)})`` (pydantic v2), which forwards every
field the caller set, including future additions.

Coverage strategy
-----------------
Two complementary tests per fetcher:

1. **Behavioral** (``test_wrapper_forwards_all_query_fields_to_upstream``):
   asynchronously run the wrapper against a patched upstream fetcher AND a
   patched module-level cache-lookup helper (so all symbols route to the
   fetch path). Load-bearing assertions **fail loudly** when the upstream
   isn't reached — no silent skip. For every currently-declared field
   (including ``limit`` set to a distinguishable non-default value), the
   test asserts that field survives on ``fetch_query``. Fails when a new
   field on the upstream model is dropped by a stale hand-listed
   constructor.

2. **Source-level lint**
   (``test_fetch_query_is_built_via_model_copy_not_hand_listed_kwargs``):
   grep each wrapper module for any ``FMP<X>QueryParams(`` constructor
   call outside the ``transform_query`` staticmethod's safe ``(**params)``
   form. Catches the current-code bug even before any new upstream field
   is added — locks in the safe pattern so a future refactor can't
   silently regress to hand-listing.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from importlib import import_module
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared assertion — every wrapper follows the same rebuild pattern so
# one helper covers the whole cluster (bd-t7p2). All assertions are
# load-bearing; a missing seam causes a loud failure rather than a silent
# skip.
# ---------------------------------------------------------------------------


def _assert_query_fields_forwarded(
    fetcher_module_path: str,
    cached_fetcher_class_name: str,
    upstream_fetcher_class_path: str,
    query_class: type,
    base_kwargs: dict[str, Any],
    cache_helper_name: str,
    non_default_updates: dict[str, Any] | None = None,
) -> None:
    """Assert the cached wrapper forwards every input query field to upstream.

    Patches the cache-init + module-level cache-lookup helper so all symbols
    route to the fetch path (no real DB or network fires), then patches the
    upstream fetcher's ``aextract_data`` and inspects the ``fetch_query``
    argument it receives. All fields present on the input ``query``
    (including any set via ``non_default_updates``) must be preserved on
    the ``fetch_query`` — only ``symbol`` may differ (joined from the
    ``symbols_to_fetch`` list).

    The mock upstream is asserted-called (loud failure if the wrapper's
    code path never reaches it — this was PR #342's original P1: the
    silent-skip on ``call_count == 0`` masked the fact that the wrapper
    was crashing on missing cache helpers before ever reaching upstream).

    Parameters
    ----------
    fetcher_module_path
        Dotted import path of the ``FMPCached<X>Fetcher`` module.
    cached_fetcher_class_name
        Name of the class on ``fetcher_module_path`` whose ``aextract_data``
        is invoked. Explicit rather than auto-discovered so a bad discovery
        heuristic can't silently pick the wrong class.
    upstream_fetcher_class_path
        Dotted import path of the upstream ``FMP<X>Fetcher`` class whose
        ``aextract_data`` is patched.
    query_class
        The ``FMP<X>QueryParams`` class — used to construct the input query.
    base_kwargs
        Minimum kwargs required to instantiate ``query_class``.
    cache_helper_name
        Name of the module-level cache-lookup helper (e.g.
        ``_get_cached_financial_ratios``). Patched to return ``[]`` so all
        symbols route to the fetch path.
    non_default_updates
        Extra field overrides to apply via ``model_copy(update=...)``. Use
        this to lock in fields whose default is ``None`` (e.g. ``limit``)
        that would otherwise be filtered out by the ``non-None default``
        heuristic and go unasserted.
    """
    mod = import_module(fetcher_module_path)
    cached_fetcher_cls = getattr(mod, cached_fetcher_class_name, None)
    assert cached_fetcher_cls is not None, (
        f"{fetcher_module_path}.{cached_fetcher_class_name} not found — "
        "test wiring bug, not a source bug"
    )
    assert hasattr(mod, cache_helper_name), (
        f"{fetcher_module_path}.{cache_helper_name} not found — cache "
        "helper name is out of sync with the source (bd-t7p2 test wiring)"
    )

    # Build the input query with EVERY currently-declared field set to a
    # DISTINGUISHABLE-FROM-DEFAULT sentinel. Setting a field to its default
    # would silently pass even under the pre-fix hand-listed pattern (a
    # dropped field reconstructs with the same default → equal → false
    # green). See the ``non_default_updates`` docstring — the caller MUST
    # supply a non-default value for every non-symbol field so a drop is
    # observable.
    query = query_class(**base_kwargs)
    updates: dict[str, Any] = dict(non_default_updates or {})
    if updates:
        query = query.model_copy(update=updates)

    # Sanity: every non-symbol declared field MUST have a non-default
    # sentinel in ``updates``. If a field is missing, the test would
    # trivially pass for that field even under the buggy hand-listed
    # pattern — that's the PR #342 silent-failure-hunter finding.
    declared_non_symbol_fields = {
        name for name in query_class.model_fields if name != "symbol"
    }
    missing = declared_non_symbol_fields - set(updates)
    assert not missing, (
        f"{fetcher_module_path}: test parametrization is missing non-default "
        f"sentinels for fields {sorted(missing)!r} — the behavioral assertion "
        f"would trivially pass for these fields even under a hand-listed "
        f"drop (bd-t7p2, PR #342 review). Add distinguishable sentinels to "
        f"``non_default_updates``."
    )
    # And each sentinel MUST differ from the field default — otherwise the
    # assertion is trivial (see above).
    for field_name, sentinel in updates.items():
        default = query_class.model_fields[field_name].default
        assert sentinel != default, (
            f"{fetcher_module_path}: sentinel for field {field_name!r} is "
            f"the class default ({default!r}) — assertion would pass even "
            f"under a drop. Pick a different value."
        )

    # Load-bearing patches:
    # - init_database: no-op so the wrapper doesn't crash trying to open MySQL
    # - {cache_helper_name}: return [] so every symbol routes to the fetch path
    # - upstream aextract_data: AsyncMock so the fetch call is captured
    with patch(f"{fetcher_module_path}.init_database", return_value=None), patch(
        f"{fetcher_module_path}.{cache_helper_name}", return_value=[]
    ):
        with patch(
            f"{upstream_fetcher_class_path}.aextract_data",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_upstream:
            # NO try/except swallowing — if the wrapper crashes, the test
            # fails loudly with the underlying exception. This was PR #342's
            # P1 bug: a bare try/except: pass masked missing patches and let
            # the test PASS without asserting anything.
            asyncio.run(cached_fetcher_cls.aextract_data(query, credentials=None))

    # Load-bearing: upstream MUST have been called. call_count == 0 means
    # the wrapper's code path never reached the fetch branch (e.g. all
    # symbols came back from cache, contradicting our stub). This assertion
    # is what catches the class of silent-test-theater failures PR #342
    # review flagged.
    assert mock_upstream.call_count > 0, (
        f"{fetcher_module_path}: upstream fetcher was NEVER called — test "
        f"seams are wrong (cache helper {cache_helper_name!r} may not be "
        f"the right patch point for this wrapper)."
    )

    call = mock_upstream.call_args_list[-1]
    fetch_query = call.args[0] if call.args else call.kwargs.get("query")
    assert fetch_query is not None, (
        f"{fetcher_module_path}: upstream was called but with no query arg — "
        f"call.args={call.args!r}, call.kwargs={call.kwargs!r}"
    )
    for field_name in updates:
        input_val = getattr(query, field_name)
        fetch_val = getattr(fetch_query, field_name, None)
        assert fetch_val == input_val, (
            f"{fetcher_module_path}: field {field_name!r} was dropped on "
            f"the rebuild — input {input_val!r} vs fetch_query {fetch_val!r} "
            f"(bd-t7p2)."
        )


# ---------------------------------------------------------------------------
# Per-model behavioral tests — one thin wrapper per file so a failure
# names the specific fetcher whose rebuild is dropping fields.
#
# For each fetcher we pass a non-default ``limit`` (default None) so that
# the "future kwargs are dropped" invariant is exercised on a field whose
# default WAS None — this is exactly the class of drop the hand-listed
# constructor would silently commit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    (
        "fetcher_module, cached_class, upstream_fetcher, query_class_path, "
        "base_kwargs, cache_helper, non_default_updates"
    ),
    [
        (
            "openbb_fmp_cached.models.balance_sheet",
            "FMPCachedBalanceSheetFetcher",
            "openbb_fmp.models.balance_sheet.FMPBalanceSheetFetcher",
            "openbb_fmp.models.balance_sheet.FMPBalanceSheetQueryParams",
            {"symbol": "AAPL"},
            "_get_cached_balance_sheet",
            # ``limit`` default None → sentinel 7; ``period`` default 'annual' → 'quarter'.
            {"limit": 7, "period": "quarter"},
        ),
        (
            "openbb_fmp_cached.models.cash_flow",
            "FMPCachedCashFlowStatementFetcher",
            "openbb_fmp.models.cash_flow.FMPCashFlowStatementFetcher",
            "openbb_fmp.models.cash_flow.FMPCashFlowStatementQueryParams",
            {"symbol": "AAPL"},
            "_get_cached_cash_flow",
            # ``limit`` default 5 → sentinel 7; ``period`` default 'annual' → 'quarter'.
            {"limit": 7, "period": "quarter"},
        ),
        (
            "openbb_fmp_cached.models.financial_ratios",
            "FMPCachedFinancialRatiosFetcher",
            "openbb_fmp.models.financial_ratios.FMPFinancialRatiosFetcher",
            "openbb_fmp.models.financial_ratios.FMPFinancialRatiosQueryParams",
            {"symbol": "AAPL"},
            "_get_cached_financial_ratios",
            # All three fields need non-default sentinels.
            {"limit": 7, "ttm": "include", "period": "quarter"},
        ),
        (
            "openbb_fmp_cached.models.income_statement",
            "FMPCachedIncomeStatementFetcher",
            "openbb_fmp.models.income_statement.FMPIncomeStatementFetcher",
            "openbb_fmp.models.income_statement.FMPIncomeStatementQueryParams",
            {"symbol": "AAPL"},
            "_get_cached_income_statement",
            {"limit": 7, "period": "quarter"},
        ),
        (
            "openbb_fmp_cached.models.key_metrics",
            "FMPCachedKeyMetricsFetcher",
            "openbb_fmp.models.key_metrics.FMPKeyMetricsFetcher",
            "openbb_fmp.models.key_metrics.FMPKeyMetricsQueryParams",
            {"symbol": "AAPL"},
            "_get_cached_key_metrics",
            {"limit": 7, "ttm": "include", "period": "quarter"},
        ),
    ],
    ids=[
        "balance_sheet",
        "cash_flow",
        "financial_ratios",
        "income_statement",
        "key_metrics",
    ],
)
def test_wrapper_forwards_all_query_fields_to_upstream(
    fetcher_module,
    cached_class,
    upstream_fetcher,
    query_class_path,
    base_kwargs,
    cache_helper,
    non_default_updates,
):
    """Every field on the input query must survive the wrapper's rebuild (bd-t7p2)."""
    mod_path, cls_name = query_class_path.rsplit(".", 1)
    query_class = getattr(import_module(mod_path), cls_name)
    _assert_query_fields_forwarded(
        fetcher_module_path=fetcher_module,
        cached_fetcher_class_name=cached_class,
        upstream_fetcher_class_path=upstream_fetcher,
        query_class=query_class,
        base_kwargs=base_kwargs,
        cache_helper_name=cache_helper,
        non_default_updates=non_default_updates,
    )


# ---------------------------------------------------------------------------
# Source-level lint — catches the current hand-listed pattern EVEN before
# any new upstream field is added. The behavioral tests above only fail
# once a specific new field is dropped; this test locks in the correct
# construction shape so a future refactor can't quietly regress to
# hand-listing (bd-t7p2).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fetcher_module_path",
    [
        "openbb_fmp_cached.models.balance_sheet",
        "openbb_fmp_cached.models.cash_flow",
        "openbb_fmp_cached.models.equity_profile",
        "openbb_fmp_cached.models.equity_quote",
        "openbb_fmp_cached.models.etf_holdings",
        "openbb_fmp_cached.models.financial_ratios",
        "openbb_fmp_cached.models.income_statement",
        "openbb_fmp_cached.models.institutional_ownership",
        "openbb_fmp_cached.models.key_metrics",
    ],
)
def test_fetch_query_is_built_via_model_copy_not_hand_listed_kwargs(
    fetcher_module_path,
):
    """Wrapper rebuilds must use query.model_copy(...), not FMP<X>QueryParams(...) (bd-t7p2).

    The hand-listed pattern (``fetch_query = FMP<X>QueryParams(symbol=...,
    period=query.period, ...)``) silently drops any field the caller sets
    that isn't in the hand-listed set — including future upstream additions.
    The Pydantic v2 model_copy pattern (``fetch_query = query.model_copy(
    update={'symbol': ...})``) forwards every field the caller set,
    guaranteeing the wrapper is transparent to upstream field additions.

    This source-level check enforces the safe pattern at the file level
    so a future refactor can't silently regress. Any wrapper that must
    remain on the constructor pattern for a specific reason must add an
    explicit comment naming that reason next to the call — the test is a
    grep for the constructor form and will surface any such site for
    manual review during code review.
    """
    mod = import_module(fetcher_module_path)
    source = inspect.getsource(mod)

    # Match ``FMP<Something>QueryParams(`` — potentially unsafe. Allow the
    # ``transform_query`` staticmethod's ``FMP<X>QueryParams(**params)``
    # (single legit use — constructs from a raw params dict at the
    # provider boundary). Everything else is unsafe.
    constructor_calls = list(re.finditer(r"FMP[A-Za-z]+QueryParams\s*\(", source))
    bad: list[str] = []
    for m in constructor_calls:
        tail = source[m.end() : m.end() + 40]
        if tail.startswith("**params)"):
            continue  # safe transform_query shape
        line_start = source.rfind("\n", 0, m.start()) + 1
        line_end = source.find("\n", m.start())
        bad.append(source[line_start:line_end].strip())

    assert not bad, (
        f"{fetcher_module_path}: wrapper still hand-lists FMP<X>QueryParams "
        f"fields, silently dropping any future upstream additions (bd-t7p2). "
        f"Rebuild via ``query.model_copy(update={{'symbol': ...}})`` instead. "
        f"Offending lines:\n  " + "\n  ".join(bad)
    )
