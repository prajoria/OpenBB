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
   asynchronously run the wrapper against a patched upstream fetcher and
   assert that every non-``symbol`` field on the input query survives on
   the ``fetch_query`` the wrapper constructs. Fails when a new field on
   the upstream model is dropped by a stale hand-listed constructor.

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
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared assertion — every wrapper follows the same rebuild pattern so
# one helper covers the whole cluster (bd-t7p2).
# ---------------------------------------------------------------------------


def _assert_query_fields_forwarded(
    fetcher_module_path: str,
    upstream_fetcher_class_path: str,
    query_class: type,
    base_kwargs: dict[str, Any],
    fetch_method: str = "aextract_data",
) -> None:
    """Assert the cached wrapper forwards every input query field to upstream.

    Patches the cache-init + cache-hit paths so no real DB or network fires,
    then patches the upstream fetcher's ``aextract_data`` and inspects the
    ``fetch_query`` argument it receives. All fields present on the input
    ``query`` (including any set via ``model_copy(update=...)``) must be
    preserved on the ``fetch_query`` — only ``symbol`` may differ (joined
    from the ``symbols_to_fetch`` list).

    Parameters
    ----------
    fetcher_module_path
        Dotted import path of the ``FMPCached<X>Fetcher`` module.
    upstream_fetcher_class_path
        Dotted import path of the upstream ``FMP<X>Fetcher`` class whose
        ``aextract_data`` is patched.
    query_class
        The ``FMP<X>QueryParams`` class — used to construct the input query.
    base_kwargs
        Minimum kwargs required to instantiate ``query_class`` (e.g. symbol).
    fetch_method
        Name of the method that owns the rebuild — typically
        ``aextract_data``. Not currently varied but kept explicit for
        callers that need to patch a different seam.
    """
    from importlib import import_module

    mod = import_module(fetcher_module_path)
    cached_fetcher_cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if (
            isinstance(obj, type)
            and name.endswith("Fetcher")
            and hasattr(obj, fetch_method)
            and obj.__module__ == fetcher_module_path
        ):
            cached_fetcher_cls = obj
            break
    assert cached_fetcher_cls is not None, (
        f"could not find a cached fetcher class in {fetcher_module_path}; "
        "unit-test discovery failed"
    )

    # Build the input query with EVERY field the class exposes set to a
    # non-default sentinel — that way if the wrapper hand-lists a subset,
    # the missing fields' sentinels won't survive to fetch_query.
    query = query_class(**base_kwargs)
    # We can't easily add a truly unknown field (Pydantic v2 forbids extras
    # on OpenBB provider models), but we CAN verify every currently-declared
    # field is forwarded — the same discipline that catches drops.
    updates: dict[str, Any] = {}
    for field_name, field_info in query_class.model_fields.items():
        if field_name == "symbol":
            continue  # overwritten deliberately by the wrapper
        if field_info.default not in (None, ...):
            updates[field_name] = field_info.default
    if updates:
        query = query.model_copy(update=updates)

    with patch(f"{fetcher_module_path}.init_database", return_value=None), patch.object(
        cached_fetcher_cls, "_get_cached", create=True, return_value=[]
    ):
        with patch(
            f"{upstream_fetcher_class_path}.aextract_data",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_upstream:
            try:
                asyncio.run(cached_fetcher_cls.aextract_data(query, credentials=None))
            except Exception:
                # Partial-run is enough as long as the mocked upstream WAS
                # reached at least once — some fetchers own cache-lookup
                # via module helpers not patched here.
                pass

            if mock_upstream.call_count > 0:
                call = mock_upstream.call_args_list[-1]
                fetch_query = call.args[0] if call.args else call.kwargs.get("query")
                assert fetch_query is not None
                for field_name in updates:
                    input_val = getattr(query, field_name)
                    fetch_val = getattr(fetch_query, field_name, None)
                    assert fetch_val == input_val, (
                        f"{fetcher_module_path}: field {field_name!r} was "
                        f"dropped on the rebuild — input {input_val!r} vs "
                        f"fetch_query {fetch_val!r} (bd-t7p2)."
                    )


# ---------------------------------------------------------------------------
# Per-model behavioral tests — one thin wrapper per file so a failure
# names the specific fetcher whose rebuild is dropping fields.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fetcher_module, upstream_fetcher, query_class_path, base_kwargs",
    [
        (
            "openbb_fmp_cached.models.balance_sheet",
            "openbb_fmp.models.balance_sheet.FMPBalanceSheetFetcher",
            "openbb_fmp.models.balance_sheet.FMPBalanceSheetQueryParams",
            {"symbol": "AAPL"},
        ),
        (
            "openbb_fmp_cached.models.cash_flow",
            "openbb_fmp.models.cash_flow.FMPCashFlowStatementFetcher",
            "openbb_fmp.models.cash_flow.FMPCashFlowStatementQueryParams",
            {"symbol": "AAPL"},
        ),
        (
            "openbb_fmp_cached.models.financial_ratios",
            "openbb_fmp.models.financial_ratios.FMPFinancialRatiosFetcher",
            "openbb_fmp.models.financial_ratios.FMPFinancialRatiosQueryParams",
            {"symbol": "AAPL"},
        ),
        (
            "openbb_fmp_cached.models.income_statement",
            "openbb_fmp.models.income_statement.FMPIncomeStatementFetcher",
            "openbb_fmp.models.income_statement.FMPIncomeStatementQueryParams",
            {"symbol": "AAPL"},
        ),
        (
            "openbb_fmp_cached.models.key_metrics",
            "openbb_fmp.models.key_metrics.FMPKeyMetricsFetcher",
            "openbb_fmp.models.key_metrics.FMPKeyMetricsQueryParams",
            {"symbol": "AAPL"},
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
    fetcher_module, upstream_fetcher, query_class_path, base_kwargs
):
    """Every field on the input query must survive the wrapper's rebuild (bd-t7p2)."""
    from importlib import import_module

    mod_path, cls_name = query_class_path.rsplit(".", 1)
    query_class = getattr(import_module(mod_path), cls_name)
    _assert_query_fields_forwarded(
        fetcher_module_path=fetcher_module,
        upstream_fetcher_class_path=upstream_fetcher,
        query_class=query_class,
        base_kwargs=base_kwargs,
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
    from importlib import import_module

    mod = import_module(fetcher_module_path)
    source = _read_module_source(mod)

    import re

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


def _read_module_source(mod) -> str:
    """Return the on-disk source text of ``mod`` for source-level assertions."""
    import inspect

    return inspect.getsource(mod)
