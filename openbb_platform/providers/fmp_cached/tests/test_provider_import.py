"""Regression tests for the class of import-time bugs that produced bd-c4h.

Two bugs shipped in PR #448 (Phase 0-3+5 merge) that were only caught by
a sibling repo trying to import ``openbb`` after a develop merge — the
existing fmp_cached test suite missed both because it mocks the DB and
uses AsyncMock-based ``Fetcher`` doubles that never hit the provider-
registration path.

This file locks the two failure modes at import time so any future
regression surfaces in per-PR CI, not in a downstream repo hours later:

  1. ``from openbb_fmp_cached.utils import cache_schema`` must not
     raise ``NameError`` (Bug 1: FLATTENED_TABLES forward-referenced 4
     later-defined ``create_*_table`` functions).

  2. ``from openbb_fmp_cached.utils.cache_schema import FLATTENED_TABLES``
     must expose every registered schema function as callable — a
     forward-ref would leave a NameError-shaped placeholder that only
     fires on invocation.

  3. ``FMPCachedExchangeMarketHoursFetcher`` — the shipped
     ``create_ttl_wrapper_class`` consumer — must resolve its
     ``Fetcher[Q, R]`` type params so ``RegistryMap._get_model`` can
     walk it without ``ValueError('~Q must be a subclass of QueryParams')``
     (Bug 2).

  4. ``from openbb import obb`` must not raise. The full-platform
     import is the empirical test for both bugs together; it's what
     the sibling repo was doing when it caught the regression.

Runtime: negligible for #1-#3, ~2-3 seconds for #4 (real ``openbb``
import). No live DB / network / secrets.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import get_args, get_origin

import pytest


class TestCacheSchemaImports:
    """Bug 1: forward-ref in FLATTENED_TABLES must not resurrect."""

    def test_cache_schema_module_imports_cleanly(self):
        """Direct import must not raise NameError.

        Regression for bd-c4h Bug 1: FLATTENED_TABLES referenced 4
        ``create_*_table`` functions defined AFTER it in the file.
        Python evaluates the dict body at import time -> NameError.
        """
        # Import in a fresh subprocess so a previously-cached broken
        # import in the current process doesn't mask a regression.
        script = "from openbb_fmp_cached.utils import cache_schema; print('OK')"
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"cache_schema import failed:\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_all_registered_schema_functions_are_callable(self):
        """Every FLATTENED_TABLES['schema'] must resolve to an actual
        callable, not just a name that would NameError on invocation.

        This catches a specific class of regression: someone adds a
        table entry pointing at ``create_foo_table`` but only defines
        the function much later. Bug 1 is the aggregate form of this.
        """
        from openbb_fmp_cached.utils import cache_schema

        for name, entry in cache_schema.FLATTENED_TABLES.items():
            schema_fn = entry.get("schema")
            assert schema_fn is not None, f"FLATTENED_TABLES[{name!r}] missing 'schema'"
            assert callable(schema_fn), (
                f"FLATTENED_TABLES[{name!r}]['schema'] not callable: {schema_fn!r}"
            )

    def test_ttl_cache_and_fmp_trading_state_registered(self):
        """Positive check: the two tables that revealed Bug 1 by their
        insertion order MUST both be present."""
        from openbb_fmp_cached.utils.cache_schema import FLATTENED_TABLES

        assert "ttl_cache" in FLATTENED_TABLES
        assert "fmp_trading_state" in FLATTENED_TABLES


class TestTTLWrapperGenericSpecialization:
    """Bug 2: ``create_ttl_wrapper_class`` must produce a class whose
    ``Fetcher[Q, R]`` params are RESOLVED, not TypeVars."""

    def test_shipped_exchange_market_hours_ttl_wrapper_has_resolved_generics(self):
        """The one production consumer of ``create_ttl_wrapper_class``
        must have resolved type params in its MRO.

        Regression for bd-c4h Bug 2: unspecialized ``Fetcher`` in the
        wrapper caused ``RegistryMap._get_model`` to raise
        ``ValueError('~Q must be a subclass of QueryParams')`` at
        provider registration time.
        """
        from openbb_core.provider.abstract.fetcher import Fetcher
        from openbb_fmp_cached.models.exchange_market_hours import (
            FMPCachedExchangeMarketHoursFetcher,
        )

        # Walk the MRO the same way base_cached._resolve_fetcher_type_params
        # does. Find at least one Fetcher[Q, R] with args that are NOT
        # TypeVars.
        found_resolved = False
        for klass in FMPCachedExchangeMarketHoursFetcher.__mro__:
            for base in getattr(klass, "__orig_bases__", ()):
                if get_origin(base) is Fetcher:
                    args = get_args(base)
                    if len(args) >= 2:
                        # A TypeVar has __class__.__name__ == 'TypeVar'
                        q_is_typevar = type(args[0]).__name__ == "TypeVar"
                        r_is_typevar = type(args[1]).__name__ == "TypeVar"
                        if not q_is_typevar and not r_is_typevar:
                            found_resolved = True
                            break
            if found_resolved:
                break

        assert found_resolved, (
            "FMPCachedExchangeMarketHoursFetcher's MRO has no "
            "Fetcher[Q, R] base with RESOLVED type params — the TTL "
            "wrapper's Generic specialization regressed. "
            "See bd-c4h Bug 2 and create_ttl_wrapper_class."
        )

    def test_resolve_type_params_walks_indirect_inheritance(self):
        """PR #464 pre-merge review fold-in: the MRO walk must catch
        specializations declared through an intermediate base class.

        Reviewer point: a single-level ``__orig_bases__`` inspection
        silently regresses to bare ``Fetcher`` for indirect inheritance
        patterns like::

            class _BaseFetcher(Fetcher[Q, R]): ...
            class ConcreteFetcher(_BaseFetcher[MyQuery, MyData]): ...

        The MRO walk in ``_resolve_fetcher_type_params`` must find the
        Fetcher[Q, R] in ``_BaseFetcher.__orig_bases__``.
        """
        from typing import TypeVar

        from openbb_core.provider.abstract.data import Data
        from openbb_core.provider.abstract.fetcher import Fetcher
        from openbb_core.provider.abstract.query_params import QueryParams
        from openbb_fmp_cached.models.base_cached import (
            _resolve_fetcher_type_params,
        )

        class _MyQ(QueryParams):
            pass

        class _MyD(Data):
            pass

        # Indirect inheritance: intermediate class specializes the generic
        class _Intermediate(Fetcher[_MyQ, _MyD]):
            pass

        class _Concrete(_Intermediate):
            pass

        q, r = _resolve_fetcher_type_params(_Concrete)
        assert q is _MyQ, (
            f"MRO walk failed to find Q on indirect inheritance: got {q!r}"
        )
        assert r is _MyD, (
            f"MRO walk failed to find R on indirect inheritance: got {r!r}"
        )

    def test_resolve_type_params_returns_none_for_bare_fetcher(self):
        """A class inheriting from bare ``Fetcher`` (no ``[Q, R]``)
        legitimately has no resolvable params — callers emit a WARN
        in that case."""
        from openbb_core.provider.abstract.fetcher import Fetcher
        from openbb_fmp_cached.models.base_cached import (
            _resolve_fetcher_type_params,
        )

        class _BareChild(Fetcher):
            pass

        q, r = _resolve_fetcher_type_params(_BareChild)
        assert q is None
        assert r is None


class TestFullPlatformImport:
    """Bug 1 + Bug 2 combined: the empirical test the sibling repo used
    to catch bd-g1i1 — ``from openbb import obb`` must not raise.

    Runs in a subprocess because ``openbb.build()`` mutates global state
    and would leave the current pytest process in a modified state that
    could mask a later regression.
    """

    def test_from_openbb_import_obb_does_not_raise(self):
        script = textwrap.dedent(
            """
            from openbb import obb
            # Access a fmp_trading-adjacent attribute to force provider
            # registration for the fmp_cached path this fix targets.
            _ = obb.provider
            print('OK')
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,  # openbb.build() can take a while cold
        )
        if result.returncode != 0:
            pytest.fail(
                "from openbb import obb failed — bd-c4h regression?\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        assert "OK" in result.stdout
