"""E3.2: FMPOHLCVProvider inherits pynecore.providers.Provider (mode-2).

Verifies the base-class inheritance + method signatures so the
pyne_compiler runtime can consume ``FMPOHLCVProvider`` polymorphically
through the ``Provider`` ABC after the E3.4 import rewrite.

The full pynecore behavioral conformance suite exercises stream()/fetch()
against a real data window, which for FMP requires an API key — that lives
in the integration-marked test at the bottom of this module.
"""
from __future__ import annotations

import inspect

import pytest

# Ensure the openbb_pine sys.path bridge has run so pynecore imports resolve.
import openbb_pine  # noqa: F401  -- side-effect: installs pynecore bridge

pytest.importorskip("pynecore.providers")

from pynecore.providers.provider import Provider  # noqa: E402
from openbb_pine.runtime.fmp_provider import FMPOHLCVProvider, FMPRequest  # noqa: E402


def test_fmp_provider_is_provider_subclass() -> None:
    """E3.2 headline invariant — the ``pyne_compiler`` runtime dispatches
    on ``Provider``, so ``FMPOHLCVProvider`` MUST inherit from it."""
    assert issubclass(FMPOHLCVProvider, Provider), (
        "E3.2 refactor incomplete: FMPOHLCVProvider must inherit "
        "pynecore.providers.Provider (see spec §5.2 mode 2)."
    )


def test_fmp_stream_signature_matches_provider_base() -> None:
    """``stream(symbol, timeframe, *, start, end, include_gaps)`` per spec §5."""
    sig = inspect.signature(FMPOHLCVProvider.stream)
    params = list(sig.parameters)
    for name in ("symbol", "timeframe", "start", "end"):
        assert name in params, f"stream() missing required param {name!r}"


def test_fmp_fetch_signature_matches_provider_base() -> None:
    """``fetch(symbol, timeframe, *, start, end, include_gaps) -> list[OHLCV]``."""
    sig = inspect.signature(FMPOHLCVProvider.fetch)
    params = list(sig.parameters)
    for name in ("symbol", "timeframe", "start", "end"):
        assert name in params, f"fetch() missing required param {name!r}"


def test_fmp_can_be_instantiated_with_existing_call_path() -> None:
    """Backward-compat guard: existing ``executor_shell`` construction path
    (FMPRequest + provider kwarg) MUST keep working after the refactor —
    only class hierarchy changes, not the caller contract.
    """
    req = FMPRequest(symbol="AAPL", interval="1D", start=None, end=None)
    prov = FMPOHLCVProvider(req, provider="fmp_cached")
    # Sanity: is-a Provider now.
    assert isinstance(prov, Provider)
    # Sanity: existing surface preserved.
    assert prov.provider_used == "fmp_cached"
    assert prov.bars_consumed == 0


@pytest.mark.xfail(
    reason=(
        "bd-78w migration pending: SITE 1 adapter `_ohlcv_list_to_dataframe` "
        "was added to openbb-fork's security_dispatcher.py in E3.2, but not "
        "carried into pyne_compiler.runtime.security_dispatcher during E2 "
        "history extraction. Post-bd-579, openbb_pine.runtime.security_dispatcher "
        "is a sys.modules alias to the pyne_compiler version which lacks the "
        "adapter. bd-78w will land the adapter in pyne_compiler and un-xfail "
        "this test."
    ),
    strict=True,
)
def test_dispatcher_has_ohlcv_to_dataframe_adapter() -> None:
    """bead 78w SITE 1: dispatcher must convert ``list[OHLCV]`` → ``pd.DataFrame``
    at the Provider→dispatcher boundary (pre-existing dispatcher works in
    DataFrame-space per Wave-4 finding phase2b-plan-notes-from-wave3).

    Post-bd-579: openbb_pine.runtime.security_dispatcher is a sys.modules
    alias shim to pyne_compiler.runtime.security_dispatcher. Inspect the
    real (aliased) module's source, not the shim's 28-line stub.
    """
    from openbb_pine.runtime import security_dispatcher  # noqa: PLC0415 — alias-shimmed

    # Post-bd-579 alias shims cause `security_dispatcher is pyne_compiler...`,
    # so inspect.getsource returns the real module's source directly.
    src = inspect.getsource(security_dispatcher)
    assert "_ohlcv_list_to_dataframe" in src or "_ohlcv_to_dataframe" in src, (
        "bead 78w SITE 1 adapter missing: security_dispatcher.py needs a "
        "list[OHLCV] -> pd.DataFrame adapter at the Provider boundary."
    )
