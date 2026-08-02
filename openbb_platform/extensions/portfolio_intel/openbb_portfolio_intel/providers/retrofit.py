"""Retrofit helper: route stub endpoints through ChainedFetcher (#1715).

Each widget-backend endpoint that was pure stub can now call
:func:`route_through_chain` to (a) attempt every tier in its family's
registered chain, (b) fall back to the endpoint's own stub function on
chain exhaustion, and (c) always record which tier finally served the
request into the ``_TIER_IN_USE`` ledger so the provider-health widget
reflects reality.

Design goals:

- **Zero behavior change when no tiers are wired** — the chain
  exhausts, we fall to the stub, ``record_tier_used(endpoint, "stub")``
  fires, the widget response is byte-identical to today.
- **Progressive enhancement** — as each ``(family, tier)`` gets a real
  ``call_tier`` implementation in a follow-up PR, the chain starts
  serving live data for that combination without touching any endpoint
  code.
- **Loud diagnostics** — every chain exhaustion emits a WARNING log
  with the endpoint, family, and last trigger. The provider-health
  widget's "Currently serving:" section names every endpoint currently
  falling to stub.

The initial dispatch table is empty — every ``(family, tier)`` raises
``NotImplementedError`` which the chain classifies as ``NOT_AVAILABLE``
and treats as a transition. Family authors register real calls with
:func:`register_tier_call`.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from openbb_portfolio_intel.providers.chain import (
    ChainedFetcher,
    ChainedFetcherAllTiersFailed,
)
from openbb_portfolio_intel.providers.registry import TIER_REGISTRY, track_key

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-(family, tier) dispatch table
# ---------------------------------------------------------------------------


#: A ``TierCall`` receives the resolved kwargs the endpoint passes to the
#: chain (e.g. ``symbol="AAPL"``) and returns whatever the tier's provider
#: gave back. The chain treats the return value as a candidate result;
#: raising is a transition, empty is a transition, non-empty is served.
TierCall = Callable[..., Any]


_TIER_CALLS: dict[tuple[str, str], TierCall] = {}


def register_tier_call(family: str, tier: str, call: TierCall) -> None:
    """Register a real provider call for one ``(family, tier)`` combination.

    Args:
        family: Endpoint family (matches TIER_REGISTRY keys without the
            track suffix, e.g. ``"equity/header"``)
        tier: Tier name (e.g. ``"fmp_cached"``)
        call: Callable that executes the tier's fetch. Receives the
            endpoint's kwargs; returns the tier's response or raises.
    """
    _TIER_CALLS[(family, tier)] = call


def _dispatch(tier: str, family: str, **kwargs: Any) -> Any:
    """Look up (family, tier) in the dispatch table and invoke it.

    Missing entries raise ``NotImplementedError`` which the chain
    classifies as ``NOT_AVAILABLE`` — the intended baseline for
    everything that isn't wired yet.
    """
    call = _TIER_CALLS.get((family, tier))
    if call is None:
        raise NotImplementedError(
            f"tier {tier!r} for family {family!r} not registered (falls "
            "through to next tier per chain semantics)"
        )
    return call(**kwargs)


# ---------------------------------------------------------------------------
# The one wrapper the endpoint bodies call
# ---------------------------------------------------------------------------


def route_through_chain(
    *,
    endpoint: str,
    family: str,
    stub_fallback: Callable[[], Any],
    record_tier_used: Callable[[str, str], None],
    track: str = "A",
    shape_result: Callable[[Any], Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Route an endpoint through its registered tier chain, with stub fallback.

    Every non-basket endpoint should call this exactly once, passing
    itself as ``endpoint`` (the string used in the provider-health
    ledger) and its family from ``TIER_REGISTRY`` (used to look up the
    tier list).

    Args:
        endpoint: Ledger key for the provider-health widget's
            "Currently serving:" section (e.g. ``"pi/equity/header"``).
        family: TIER_REGISTRY family (e.g. ``"equity/header"``).
        stub_fallback: A zero-arg callable returning the existing stub
            response. Called only when the chain exhausts every tier.
        record_tier_used: The ``widgets_endpoints.record_tier_used``
            hook — passed in explicitly to avoid an import cycle.
        track: ``"A"`` (paid) or ``"B"`` (free). Default ``"A"``.
        shape_result: Optional post-processor applied to the tier's raw
            response before returning. Passthrough when omitted.
        **kwargs: Whatever the endpoint's provider needs (``symbol=``,
            ``horizon_days=``, etc.). Forwarded to ``call_tier``.

    Returns:
        The tier's response (possibly shaped), or the stub fallback.
    """
    tiers = TIER_REGISTRY.get(track_key(family, track))
    if not tiers:
        # No tiers registered for this family — treat identically to
        # chain exhaustion. Should never happen in practice because
        # every retrofit-eligible endpoint has a registered family.
        logger.warning(
            "chain.no_tiers endpoint=%s family=%s track=%s — falling to stub",
            endpoint,
            family,
            track,
        )
        record_tier_used(endpoint, "stub")
        return stub_fallback()

    chain = ChainedFetcher(
        endpoint=family,
        track=track,
        tiers=tiers,
        call_tier=lambda tier, **kw: _dispatch(tier, family, **kw),
    )
    try:
        result, outcome = chain.fetch(**kwargs)
    except ChainedFetcherAllTiersFailed as exc:
        last_trigger = (
            exc.outcome.transitions[-1].trigger.value
            if exc.outcome.transitions
            else "no_tiers_wired"
        )
        logger.warning(
            "chain.exhausted endpoint=%s family=%s last_trigger=%s "
            "— falling to stub",
            endpoint,
            family,
            last_trigger,
        )
        record_tier_used(endpoint, "stub")
        return stub_fallback()

    # Chain served — record which tier and return.
    if outcome.tier_used is None:  # invariant of successful fetch
        raise RuntimeError(
            "unreachable: chain returned without raising but tier_used is None"
        )
    record_tier_used(endpoint, outcome.tier_used)
    return shape_result(result) if shape_result else result


# ---------------------------------------------------------------------------
# Decorator sugar: one-liner retrofit
# ---------------------------------------------------------------------------


def with_chain(
    *,
    endpoint: str,
    family: str,
    record_tier_used: Callable[[str, str], None],
    track: str = "A",
    kwargs_from: Callable[..., dict] | None = None,
    require_auth: Callable[..., None] | None = None,
    validate_kwargs: Callable[..., None] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Build a decorator that routes an endpoint through its tier chain.

    Wrap the ORIGINAL stub function; the decorator uses the wrapped
    function as the ``stub_fallback`` on chain exhaustion. Zero
    behavior change today (no tiers wired) — every call falls through
    to the wrapped stub and the ledger records ``"stub"``. As tiers
    get registered via :func:`register_tier_call`, they start winning.

    **Security invariants (#1715 security review):**

    - ``require_auth`` runs BEFORE any tier is dispatched. Without it,
      a registered live tier would serve unauthenticated requests
      because the ``_require_auth(request)`` call inside the stub body
      would be bypassed on chain success.
    - ``validate_kwargs`` runs BEFORE any tier is dispatched. Without
      it, a registered tier would receive un-sanitized user-supplied
      params (e.g. ``symbol="<script>"``) because ``_validate_symbol``
      inside the stub body would be bypassed on chain success.

    Both hooks receive the endpoint's ``*args, **kwargs`` verbatim so
    the caller reuses the same auth/validation helpers the stub body
    already calls. When the chain exhausts and falls back to the stub,
    those in-body calls fire again — redundant but harmless (dictates
    that the security posture holds identically for the stub path and
    the wired-tier path).

    Args:
        endpoint: Ledger key for the health widget (e.g.
            ``"pi/equity/header"``).
        family: TIER_REGISTRY family (e.g. ``"equity/header"``).
        record_tier_used: The widgets_endpoints hook, passed in to
            avoid a circular import.
        track: ``"A"`` (paid, default) or ``"B"`` (free).
        kwargs_from: Optional callable that extracts the fetcher's
            kwargs from the endpoint's own args. Signature matches the
            decorated function; return dict is passed as kwargs to
            each tier's dispatch. When omitted, the decorator passes
            ``symbol=`` when present in the function signature.
        require_auth: Optional auth hook. Receives ``*args, **kwargs``
            of the endpoint call. Should raise ``HTTPException(401)``
            (or equivalent) when unauthorized. When omitted, no auth
            check runs in the wrapper — the stub body is expected to
            handle it (safe only while no tiers are wired).
        validate_kwargs: Optional input-validation hook. Receives
            ``*args, **kwargs`` of the endpoint call. Should raise
            ``HTTPException(400)`` on invalid input. When omitted,
            validation lives entirely in the stub body (safe only while
            no tiers are wired).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **fn_kwargs: Any) -> Any:
            # Security gates BEFORE chain dispatch (#1715 review).
            if require_auth is not None:
                require_auth(*args, **fn_kwargs)
            if validate_kwargs is not None:
                validate_kwargs(*args, **fn_kwargs)
            chain_kwargs = (
                kwargs_from(*args, **fn_kwargs)
                if kwargs_from is not None
                else {k: v for k, v in fn_kwargs.items() if k == "symbol"}
            )
            return route_through_chain(
                endpoint=endpoint,
                family=family,
                stub_fallback=lambda: func(*args, **fn_kwargs),
                record_tier_used=record_tier_used,
                track=track,
                **chain_kwargs,
            )

        return wrapper

    return decorator
