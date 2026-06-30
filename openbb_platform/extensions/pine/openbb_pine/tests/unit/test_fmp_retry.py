"""Tests for ``openbb_pine.runtime.fmp_retry``.

D2 section 9: every FMP call goes through a 5-attempt exponential-backoff
envelope (base 0.4s, cap 6.0s, +/-25% jitter). Retryable on 429/5xx/
connection blips; fatal on auth/validation/EmptyDataError.

Tests inject a deterministic RNG so the jitter assertion is reproducible,
and a fake sleep so the retry loop is fast.
"""

from __future__ import annotations

import random

import pytest

from openbb_pine.errors import PineFMPUnreachableError
from openbb_pine.runtime import fmp_retry as fmp_retry_module
from openbb_pine.runtime.fmp_retry import (
    BACKOFF_BASE_S,
    BACKOFF_CAP_S,
    JITTER_FRAC,
    MAX_RETRIES,
    _fmp_unreachable_counters,
    call_with_retry,
    is_retryable,
    reset_metrics,
)


def _patch_sleep(monkeypatch):
    """Patch ``fmp_retry.time.sleep`` against the live module object.

    Patching via ``monkeypatch.setattr("openbb_pine.runtime.fmp_retry.time.sleep", ...)``
    resolves through the ``openbb_pine`` package attribute chain, which can
    fail intermittently if a sibling test has popped ``openbb_pine`` from
    ``sys.modules`` between collection and execution. Operating on the
    already-imported module object dodges that ordering hazard.
    """
    monkeypatch.setattr(fmp_retry_module.time, "sleep", lambda *_a, **_k: None)


# ---------- constants match D2 spec ---------------------------------------


def test_constants_match_d2_spec():
    """D2 section 9.1 -- 4 retries (5 attempts total), 0.4s/6.0s envelope,
    +/-25% jitter."""
    assert MAX_RETRIES == 4
    assert BACKOFF_BASE_S == 0.4
    assert BACKOFF_CAP_S == 6.0
    assert JITTER_FRAC == 0.25


# ---------- is_retryable classification -----------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        Exception("HTTP 429 Too Many Requests"),
        Exception("rate limit exceeded"),
        Exception("Connection refused"),
        Exception("connection reset by peer"),
        Exception("ReadTimeout"),
        Exception("502 Bad Gateway"),
        Exception("503 Service Unavailable"),
        Exception("504 Gateway Timeout"),
        # Tolerant repr() match -- httpx-wrapped errors per D2 section 9.2.
        Exception("OpenBBError('httpx.ConnectError: [Errno 111] Connection refused')"),
    ],
)
def test_retryable_classifications(exc):
    """The classifier matches the tolerant keyword list from D2 section 9.2."""
    assert is_retryable(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("authentication failed"),
        KeyError("symbol not found"),
        AttributeError("'NoneType' object has no attribute 'json'"),
        Exception("HTTP 401 Unauthorized"),
        Exception("HTTP 403 Forbidden"),
        Exception("HTTP 404 Not Found"),
        Exception("HTTP 400 Bad Request"),
        Exception("validation error: missing field 'symbol'"),
        Exception("EmptyDataError: no data returned"),
    ],
)
def test_fatal_classifications(exc):
    """Auth, validation, empty-data, and missing-attribute errors are fatal
    -- they must NOT be retried."""
    assert is_retryable(exc) is False


# ---------- retry-then-succeed --------------------------------------------


def test_retry_then_succeed_returns_result(monkeypatch):
    """First two attempts fail with retryable errors; third succeeds.
    ``call_with_retry`` must return that result."""
    _patch_sleep(monkeypatch)
    reset_metrics()
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Exception("HTTP 503 Service Unavailable")
        return "the-result"

    result = call_with_retry(flaky, label="primary")
    assert result == "the-result"
    assert attempts["n"] == 3
    # No unreachable metric increment on eventual success.
    assert _fmp_unreachable_counters.get("primary", 0) == 0


def test_retry_succeeds_on_last_attempt(monkeypatch):
    """The 5th and last attempt succeeds -- still a clean return."""
    _patch_sleep(monkeypatch)
    reset_metrics()
    attempts = {"n": 0}

    def almost_fatal():
        attempts["n"] += 1
        if attempts["n"] < MAX_RETRIES + 1:  # 5 attempts -> fail 4x, then ok
            raise Exception("connection blip")
        return "barely"

    result = call_with_retry(almost_fatal, label="last_chance")
    assert result == "barely"
    assert attempts["n"] == MAX_RETRIES + 1


# ---------- retry-then-exhaust -------------------------------------------


def test_retry_then_exhaust_raises_unreachable(monkeypatch):
    """Always-failing retryable call must exhaust the budget and raise
    PineFMPUnreachableError after MAX_RETRIES+1 attempts."""
    _patch_sleep(monkeypatch)
    reset_metrics()
    attempts = {"n": 0}

    def always_429():
        attempts["n"] += 1
        raise Exception("HTTP 429 rate limited")

    with pytest.raises(PineFMPUnreachableError) as excinfo:
        call_with_retry(always_429, label="primary", provider="fmp")

    # 5 total attempts (1 initial + MAX_RETRIES retries).
    assert attempts["n"] == MAX_RETRIES + 1
    # Metric incremented on exhaustion.
    assert _fmp_unreachable_counters.get("fmp", 0) == 1

    # Message mentions attempts + last error.
    msg = str(excinfo.value)
    assert "5" in msg or str(MAX_RETRIES + 1) in msg


def test_exhaust_attaches_provider_attempts_last_error(monkeypatch):
    """PineFMPUnreachableError should carry provider/attempts/last_error
    attributes per D2 section 7.1 init signature."""
    _patch_sleep(monkeypatch)
    reset_metrics()

    def boom():
        raise Exception("HTTP 504 timeout")

    with pytest.raises(PineFMPUnreachableError) as excinfo:
        call_with_retry(boom, label="secondary", provider="fmp_cached")
    err = excinfo.value
    assert getattr(err, "provider", None) == "fmp_cached"
    assert getattr(err, "attempts", None) == MAX_RETRIES + 1
    assert getattr(err, "last_error", None) is not None


# ---------- fatal-no-retry ------------------------------------------------


def test_fatal_error_not_retried(monkeypatch):
    """Auth error on attempt 1 must re-raise immediately, no retries."""
    _patch_sleep(monkeypatch)
    reset_metrics()
    attempts = {"n": 0}

    def auth_fail():
        attempts["n"] += 1
        raise ValueError("authentication failed: invalid API key")

    with pytest.raises(ValueError, match="authentication failed"):
        call_with_retry(auth_fail, label="primary")

    assert attempts["n"] == 1
    # No PineFMPUnreachableError metric increment for fatal classification.
    assert _fmp_unreachable_counters.get("primary", 0) == 0


def test_first_call_success_no_sleep(monkeypatch):
    """A clean first call must NOT sleep at all -- no retry budget consumed."""
    sleep_calls = {"n": 0}

    def fake_sleep(*_a, **_k):
        sleep_calls["n"] += 1

    monkeypatch.setattr(fmp_retry_module.time, "sleep", fake_sleep)
    reset_metrics()
    assert call_with_retry(lambda: 42, label="primary") == 42
    assert sleep_calls["n"] == 0


# ---------- jitter is reproducible + within +/-25% ------------------------


def test_jitter_within_bounds_seeded():
    """With a seeded RNG the backoff times stay inside the +/-25% window
    around the geometric base, capped at BACKOFF_CAP_S."""
    rng = random.Random(0xBEEF)
    # Helper -- inspect the backoff helper directly so jitter assertion
    # is decoupled from the retry loop.
    from openbb_pine.runtime.fmp_retry import _compute_backoff

    for attempt in range(MAX_RETRIES):
        base = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** attempt))
        delay = _compute_backoff(attempt, rng=rng)
        # Bounds: ``base * (1 - JITTER_FRAC) <= delay <= base * (1 + JITTER_FRAC)``,
        # clamped to >= 0.
        lo = max(0.0, base * (1.0 - JITTER_FRAC))
        hi = base * (1.0 + JITTER_FRAC)
        assert lo <= delay <= hi, (
            f"attempt={attempt} base={base:.3f} delay={delay:.3f} bounds=({lo:.3f},{hi:.3f})"
        )


def test_jitter_reproducible_with_same_seed():
    """Two RNGs seeded identically produce the same backoff sequence."""
    from openbb_pine.runtime.fmp_retry import _compute_backoff

    rng_a = random.Random(0xC0FFEE)
    rng_b = random.Random(0xC0FFEE)
    series_a = [_compute_backoff(i, rng=rng_a) for i in range(MAX_RETRIES)]
    series_b = [_compute_backoff(i, rng=rng_b) for i in range(MAX_RETRIES)]
    assert series_a == series_b


def test_backoff_capped_at_cap_seconds():
    """For large attempt counts the geometric base saturates at BACKOFF_CAP_S
    before jitter; jittered delay never exceeds cap * (1 + JITTER_FRAC)."""
    from openbb_pine.runtime.fmp_retry import _compute_backoff

    rng = random.Random(1)
    # attempt=10 -> 0.4 * 1024 = 409.6 -> capped to 6.0
    delay = _compute_backoff(10, rng=rng)
    assert delay <= BACKOFF_CAP_S * (1.0 + JITTER_FRAC)


# ---------- metric stub ---------------------------------------------------


def test_unreachable_counter_per_provider(monkeypatch):
    """Each exhaustion increments the per-provider stub counter -- standing
    in for the eventual Prometheus ``pine_fmp_unreachable_total{provider=...}``."""
    _patch_sleep(monkeypatch)
    reset_metrics()

    def boom():
        raise Exception("HTTP 503")

    with pytest.raises(PineFMPUnreachableError):
        call_with_retry(boom, label="a", provider="fmp")
    with pytest.raises(PineFMPUnreachableError):
        call_with_retry(boom, label="b", provider="fmp")
    with pytest.raises(PineFMPUnreachableError):
        call_with_retry(boom, label="c", provider="fmp_cached")

    assert _fmp_unreachable_counters["fmp"] == 2
    assert _fmp_unreachable_counters["fmp_cached"] == 1


def test_reset_metrics_clears_counters():
    """``reset_metrics()`` zeroes the counter dict for test isolation."""
    _fmp_unreachable_counters["fmp"] = 7
    reset_metrics()
    assert _fmp_unreachable_counters == {}
