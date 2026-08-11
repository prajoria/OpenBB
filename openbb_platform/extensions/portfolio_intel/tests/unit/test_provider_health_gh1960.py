"""Tests for #1960 — Provider Health strip self-contradicts on shared tiers.

Symptom: the strip rendered ``✕ cboe (0ms) (unknown_error)`` in Track A while
Track B showed ``● cboe`` healthy — the *same* tier, probed twice, disagreeing
within one render. Two defects, both covered here:

1. **Misclassification** — ``probe._classify_probe_exception`` matched only on
   ``str(exc)``. ``httpx.ConnectTimeout()`` (slow-TLS socket timeout) carries an
   EMPTY message, so it fell through to ``unknown_error`` instead of the accurate
   ``timeout``. Fix: classify by exception *type* (MRO names) before message.

2. **Double-probe** — ``cboe`` and ``sec`` live in BOTH tracks, so each render
   probed them twice concurrently; one probe could time out while the other
   succeeded. Fix: probe each *distinct* tier once, share the result across
   both tracks.

All hermetic: no network. Probers are injected fakes.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("PI_WIDGET_BACKEND_AUTH_MODE", "loopback-dev")

import httpx  # noqa: E402
import pytest  # noqa: E402
from openbb_portfolio_intel.providers.probe import (  # noqa: E402
    ALLOWED_NOTES,
    _classify_probe_exception,
    probe_tier,
    register_prober,
    unregister_prober,
)
from openbb_portfolio_intel.providers.registry import (  # noqa: E402
    TRACK_A_DEFAULT,
    TRACK_B_DEFAULT,
)
from openbb_portfolio_intel.widget_backend import widgets_endpoints as we  # noqa: E402
from starlette.requests import Request  # noqa: E402

_ALL_TIERS = tuple(dict.fromkeys(TRACK_A_DEFAULT + TRACK_B_DEFAULT))


def _stub_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/pi/health/providers",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.fixture(autouse=True)
def _clean_state():
    for t in _ALL_TIERS:
        unregister_prober(t)
    we._PROVIDER_HEALTH_CACHE.clear()
    yield
    for t in _ALL_TIERS:
        unregister_prober(t)
    we._PROVIDER_HEALTH_CACHE.clear()


# ---------------------------------------------------------------------------
# Defect 1 — type-aware exception classification
# ---------------------------------------------------------------------------


def test_empty_message_connect_timeout_classifies_as_timeout() -> None:
    """The live bug: ``httpx.ConnectTimeout()`` has an EMPTY ``str()`` so the
    old message-only classifier returned ``unknown_error``. It must now be
    ``timeout``. Reverse-verify: revert to message-only matching and this fails.
    """
    assert str(httpx.ConnectTimeout("")) == "", "precondition: empty message"
    assert _classify_probe_exception(httpx.ConnectTimeout("")) == "timeout"


def test_empty_message_read_timeout_classifies_as_timeout() -> None:
    assert _classify_probe_exception(httpx.ReadTimeout("")) == "timeout"


def test_empty_message_connect_error_classifies_as_network() -> None:
    """A connect error with no message must classify as ``network`` (via type),
    not ``unknown_error``.
    """
    assert _classify_probe_exception(httpx.ConnectError("")) == "network"


def test_random_exception_still_unknown_error() -> None:
    """Non-transport exceptions remain ``unknown_error`` — the type-aware path
    must not over-broaden. Also proves no raw-string leak.
    """
    note = _classify_probe_exception(RuntimeError("PII_LEAK user=daisy"))
    assert note == "unknown_error"
    assert note in ALLOWED_NOTES


def test_probe_tier_empty_timeout_renders_timeout_not_unknown() -> None:
    """End-to-end through probe_tier: a prober raising an empty-message
    ConnectTimeout yields note=``timeout`` (was ``unknown_error`` at 0ms).
    """

    async def _boom() -> None:
        raise httpx.ConnectTimeout("")

    register_prober("gh1960_tier", _boom)
    try:
        h = asyncio.run(probe_tier("gh1960_tier", timeout_s=0.5))
    finally:
        unregister_prober("gh1960_tier")
    assert h.status == "down"
    assert h.note == "timeout", h


# ---------------------------------------------------------------------------
# Defect 2 — distinct-tier dedupe + cross-track consistency
# ---------------------------------------------------------------------------


def test_shared_tier_probed_once_per_render() -> None:
    """``cboe`` (in both tracks) must be probed exactly ONCE per render, not
    twice. Reverse-verify: the pre-fix per-track probing calls it twice, so this
    ``== 1`` assertion fails at 2.
    """
    assert "cboe" in TRACK_A_DEFAULT and "cboe" in TRACK_B_DEFAULT, "precondition"
    calls: dict[str, int] = {}

    def _make(tier: str):
        async def _probe() -> None:
            calls[tier] = calls.get(tier, 0) + 1

        return _probe

    for t in _ALL_TIERS:
        register_prober(t, _make(t))
    try:
        asyncio.run(we.provider_health(_stub_request()))
    finally:
        for t in _ALL_TIERS:
            unregister_prober(t)
    assert calls.get("cboe") == 1, f"cboe probed {calls.get('cboe')}× (want 1)"
    assert calls.get("sec") == 1, f"sec probed {calls.get('sec')}× (want 1)"


def test_shared_tier_identical_status_across_tracks() -> None:
    """#1960 intent under the #1961 single-track UX: a healthy tier renders a
    single consistent badge with no contradictory ``✕`` for the same tier.

    Pre-#1960 a flaky shared tier could show ● in one track and ✕ in the other.
    Post-#1961 the strip renders Track A only, so the contradiction is
    structurally impossible — assert the single Track A row shows ``● cboe`` and
    the body never carries a contradictory ``✕ cboe``.
    """
    for t in _ALL_TIERS:

        async def _ok() -> None:
            return None

        register_prober(t, _ok)
    try:
        body = asyncio.run(we.provider_health(_stub_request()))
    finally:
        for t in _ALL_TIERS:
            unregister_prober(t)

    row = next(r for r in body if r["tier"] == "cboe")
    assert "healthy" in row["status"], row
    # #1961: no Track B-exclusive tier row is rendered at all.
    tiers = {r["tier"] for r in body}
    assert "yfinance" not in tiers, tiers
    # And never a contradictory down/unknown status for the shared tier.
    assert "down" not in row["status"] and "unknown" not in row["status"], row
