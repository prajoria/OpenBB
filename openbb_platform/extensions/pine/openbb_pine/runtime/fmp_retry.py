"""FMP retry budget for the Pine runtime.

Per D2 section 9.

Every FMP / fmp_cached call goes through :func:`call_with_retry`, which
gives the call up to ``MAX_RETRIES + 1 = 5`` attempts before raising
:class:`PineFMPUnreachableError`. Backoff between attempts is exponential
with a +/-``JITTER_FRAC`` jitter band, capped at ``BACKOFF_CAP_S``.

Retryable vs fatal classification (D2 section 9.2) is keyword-tolerant
because OpenBB wraps ``httpx`` errors in ``OpenBBError`` and the wrapped
``repr()`` usually preserves the status code or condition keyword.

Worst-case wall-clock when every attempt fails: ``0.4 + 0.8 + 1.6 + 3.2
~~ 6.0 s`` (the fourth retry hits the cap). One request that triggers
the primary fetch plus N ``request.security`` fetches can therefore
worst-case ``(N + 1) * 6.0 s`` -- per-call, not pooled (D2 section 9.3).

# TODO(P4): wire ``_fmp_unreachable_counters`` into a real Prometheus
# Counter (``pine_fmp_unreachable_total{provider=...}``) when the MCP /
# observability bead lands. Until then, the dict here doubles as a
# test hook and an in-memory operator-debug surface.
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

from openbb_pine.errors import PineFMPUnreachableError

T = TypeVar("T")


# --- Tunables (D2 section 9.1) ------------------------------------------------

MAX_RETRIES: int = 4
"""Number of retries after the initial attempt. ``MAX_RETRIES = 4`` means up
to 5 attempts total."""

BACKOFF_BASE_S: float = 0.4
"""Geometric backoff base. Attempt 0 sleeps ~0.4s, attempt 1 ~0.8s, attempt
2 ~1.6s, attempt 3 ~3.2s."""

BACKOFF_CAP_S: float = 6.0
"""Per-sleep ceiling. Once the geometric series passes the cap, every
subsequent sleep stays at this value (plus/minus jitter)."""

JITTER_FRAC: float = 0.25
"""Fractional jitter band. Each backoff is multiplied by a uniform random
in ``[1 - JITTER_FRAC, 1 + JITTER_FRAC]`` so concurrent clients do not
synchronize their retries."""


# --- Retryable-vs-fatal classifier (D2 section 9.2) ---------------------------

_RETRYABLE_KEYWORDS = (
    "429",
    "rate",
    "timeout",
    "503",
    "502",
    "504",
    "connection",
)

_FATAL_KEYWORDS = (
    "401",
    "403",
    "404",
    "400",
    "auth",
    "validation",
    "emptydataerror",
    "no data",
    "symbol not found",
)


def is_retryable(exc: BaseException) -> bool:
    """Return True if the exception is in the "retry helps" bucket.

    Implementation note: we walk both the exception's ``repr()`` (which
    typically embeds the underlying httpx message after OpenBB wraps it
    in OpenBBError) and the exception type name, lowercased. Fatal
    keywords take precedence over retryable ones so that, e.g., a
    ``ValueError("auth + timeout while loading")`` is classified fatal.
    """
    text = repr(exc).lower()
    for kw in _FATAL_KEYWORDS:
        if kw in text:
            return False
    for kw in _RETRYABLE_KEYWORDS:
        if kw in text:
            return True
    return False


# --- Backoff helper -----------------------------------------------------------

# Module-level RNG so tests can re-seed for reproducible jitter assertions.
_rng = random.Random()


def _compute_backoff(attempt: int, *, rng: random.Random | None = None) -> float:
    """Return the sleep duration for the given retry attempt index.

    ``attempt`` is 0-indexed -- attempt 0 is the *first* retry (i.e. the
    sleep that precedes attempt-number-2 of the underlying call).
    """
    use_rng = rng if rng is not None else _rng
    base = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** attempt))
    jitter_multiplier = 1.0 + use_rng.uniform(-JITTER_FRAC, JITTER_FRAC)
    return max(0.0, base * jitter_multiplier)


# --- Metric stub (D2 section 9.5; real Prometheus wiring is a P4 task) -------

_fmp_unreachable_counters: dict[str, int] = {}
"""``pine_fmp_unreachable_total{provider=...}`` stand-in. Keyed by the
``provider`` argument to :func:`call_with_retry` (typically ``"fmp"`` or
``"fmp_cached"``). Replaced with a real ``prometheus_client.Counter``
when the MCP / observability bead lands."""


def reset_metrics() -> None:
    """Zero the in-memory unreachable counters -- exposed for test isolation
    and for operators who want to clear state between runs."""
    _fmp_unreachable_counters.clear()


# --- Public API ---------------------------------------------------------------


def call_with_retry(
    fn: Callable[[], T],
    *,
    label: str,
    provider: str | None = None,
) -> T:
    """Invoke ``fn()`` with the D2 section 9 retry budget.

    Parameters
    ----------
    fn
        Zero-arg callable that performs one FMP call and returns its result.
        Wrap a parametrised call with ``functools.partial`` or a lambda.
    label
        Human-readable label for the call, used in error messages. Typically
        ``"primary"`` or ``"secondary:<symbol>:<tf>"``.
    provider
        The provider name (``"fmp"`` / ``"fmp_cached"``) for metric
        attribution. Falls back to ``label`` when omitted so the counter
        dict is never keyed by ``None``.

    Returns
    -------
    ``fn()``'s return value when any of the attempts succeed.

    Raises
    ------
    PineFMPUnreachableError
        After ``MAX_RETRIES + 1`` retryable failures.
    Exception
        Any fatal exception (per :func:`is_retryable`) is re-raised
        immediately on the first attempt -- the budget is not consumed.
    """
    metric_key = provider if provider is not None else label
    last_exc: BaseException | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except PineFMPUnreachableError:
            # Already a terminal "we gave up" -- don't re-wrap it.
            raise
        except Exception as exc:  # noqa: BLE001  -- intentional broad catch
            last_exc = exc
            if not is_retryable(exc):
                # Fatal: surface immediately, do not increment unreachable
                # metric (this is a different failure mode).
                raise
            if attempt == MAX_RETRIES:
                # Budget exhausted. Increment the metric stub and raise the
                # terminal "unreachable" error. The shared error class
                # (openbb_pine.errors) wraps OpenBBError and takes a single
                # message arg, so attach the structured fields directly to
                # the instance per D2 section 7.1 init signature.
                _fmp_unreachable_counters[metric_key] = (
                    _fmp_unreachable_counters.get(metric_key, 0) + 1
                )
                err = PineFMPUnreachableError(
                    f"FMP provider {provider!r} unreachable after "
                    f"{MAX_RETRIES + 1} attempt(s) (label={label!r}); "
                    f"last error: {exc!r}"
                )
                err.provider = provider
                err.attempts = MAX_RETRIES + 1
                err.last_error = exc
                err.label = label
                raise err from exc

            # Sleep with jittered backoff before the next attempt. ``attempt``
            # here is the index of the FAILED attempt; the geometric series
            # starts at 0 -> ~0.4s.
            time.sleep(_compute_backoff(attempt))

    # Defensive -- the loop always returns or raises before falling through.
    raise PineFMPUnreachableError(  # pragma: no cover
        f"FMP provider {provider!r} unreachable after "
        f"{MAX_RETRIES + 1} attempt(s) (label={label!r}); "
        f"last error: {last_exc!r}"
    )


__all__ = [
    "MAX_RETRIES",
    "BACKOFF_BASE_S",
    "BACKOFF_CAP_S",
    "JITTER_FRAC",
    "call_with_retry",
    "is_retryable",
    "reset_metrics",
]
