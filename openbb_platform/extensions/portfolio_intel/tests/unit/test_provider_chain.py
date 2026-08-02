"""Provider chain machinery tests (#1715).

Covers:

- :class:`ChainedFetcher` walk semantics: happy path, single fallback,
  full-chain failure, empty-result triggers next tier
- Trigger classification for auth (401), rate limit (429), timeout,
  network, http_5xx, unknown
- ``ChainOutcome`` shape: tier_used, transitions list, per-tier
  latency_ms
- :func:`probe_tier` status matrix: healthy, degraded (>1s),
  down/timeout, unknown (no registered prober)
- ``TierHealth.note`` allowlist rejection at construction time
- Registry immutability + shape

R7.11 reverse-verification patterns are called out inline for each
assertion that has a mutation twin.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from openbb_portfolio_intel.providers import (
    TIER_REGISTRY,
    ChainedFetcher,
    ChainedFetcherAllTiersFailed,
    ChainOutcome,
    TierHealth,
    Trigger,
    probe_tier,
    track_key,
)
from openbb_portfolio_intel.providers.probe import (
    ALLOWED_NOTES,
    register_prober,
    unregister_prober,
)

# ---------------------------------------------------------------------------
# ChainedFetcher — happy path
# ---------------------------------------------------------------------------


def _tiers_A() -> tuple[str, ...]:
    return ("fmp_cached", "fmp", "cboe", "sec", "yfinance-snapshot")


def test_chain_returns_first_tier_when_healthy() -> None:
    """Tier 1 succeeds: result is returned, no transitions, tier_used=tier1."""
    calls: list[str] = []

    def call_tier(tier: str, **kw: object) -> dict:
        calls.append(tier)
        return {"symbol": kw["symbol"], "tier": tier}

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    result, outcome = chain.fetch(symbol="AAPL")

    assert calls == ["fmp_cached"]  # only tier 1 called
    assert result == {"symbol": "AAPL", "tier": "fmp_cached"}
    assert outcome.tier_used == "fmp_cached"
    assert outcome.transitions == []  # zero transitions on happy path
    assert "fmp_cached" in outcome.latency_ms_per_tier


def test_chain_falls_through_to_tier_2_when_tier_1_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R7.11 twin: remove the ``except Exception`` guard in chain.py -> test fails."""

    def call_tier(tier: str, **kw: object) -> dict:
        if tier == "fmp_cached":
            raise RuntimeError("provider not available")
        return {"symbol": kw["symbol"], "tier": tier}

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    with caplog.at_level(logging.INFO, logger="openbb_portfolio_intel.providers.chain"):
        result, outcome = chain.fetch(symbol="AAPL")

    assert result == {"symbol": "AAPL", "tier": "fmp"}
    assert outcome.tier_used == "fmp"
    assert len(outcome.transitions) == 1
    t = outcome.transitions[0]
    assert t.from_tier == "fmp_cached"
    assert t.to_tier == "fmp"
    assert t.trigger == Trigger.NOT_AVAILABLE
    # Structured log line was emitted.
    assert any("chain.transition" in r.getMessage() for r in caplog.records)


def test_chain_walks_all_5_tiers_then_raises_loud() -> None:
    """R7.11 twin: swap ``raise ChainedFetcherAllTiersFailed`` for ``return None, outcome``.

    Under the mutation this test would silently succeed with None; under
    the guard it correctly raises. That's the load-bearing anti-silent-empty
    invariant.
    """

    def call_tier(tier: str, **_: object) -> dict:
        raise RuntimeError(f"{tier} down")

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    with pytest.raises(ChainedFetcherAllTiersFailed) as excinfo:
        chain.fetch(symbol="AAPL")

    outcome = excinfo.value.outcome
    assert outcome.tier_used is None
    # 4 transitions between 5 tiers.
    assert len(outcome.transitions) == 4
    assert outcome.transitions[0].from_tier == "fmp_cached"
    assert outcome.transitions[-1].to_tier == "yfinance-snapshot"
    # Latency measured for every tier attempted (all 5).
    assert set(outcome.latency_ms_per_tier) == set(_tiers_A())


def test_chain_treats_empty_result_as_a_transition() -> None:
    """Empty [] / .results=[] falls through to next tier with EMPTY_RESULT trigger."""

    def call_tier(tier: str, **_: object) -> list:
        if tier == "fmp_cached":
            return []  # empty response — anti-silent-empty guard
        if tier == "fmp":
            return [{"symbol": "AAPL"}]
        return []

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    result, outcome = chain.fetch()
    assert result == [{"symbol": "AAPL"}]
    assert outcome.tier_used == "fmp"
    assert outcome.transitions[0].trigger == Trigger.EMPTY_RESULT


def test_chain_treats_none_and_empty_results_container_as_transition() -> None:
    """``.results=[]`` on a wrapped response is also empty; ``None`` is empty."""

    class _Wrapped:
        def __init__(self, rows: list) -> None:
            self.results = rows

    def call_tier(tier: str, **_: object) -> object:
        if tier == "fmp_cached":
            return _Wrapped([])
        if tier == "fmp":
            return None
        return _Wrapped([{"x": 1}])

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    result, outcome = chain.fetch()
    assert outcome.tier_used == "cboe"
    # Both fmp_cached (wrapped empty) and fmp (None) trigger EMPTY_RESULT.
    assert [t.trigger for t in outcome.transitions] == [
        Trigger.EMPTY_RESULT,
        Trigger.EMPTY_RESULT,
    ]


# ---------------------------------------------------------------------------
# Trigger classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, expected",
    [
        (RuntimeError("401 Unauthorized"), Trigger.AUTH),
        (RuntimeError("Invalid API key"), Trigger.AUTH),
        (RuntimeError("HTTP 429 Too Many Requests"), Trigger.RATE_LIMIT),
        (RuntimeError("rate limit exceeded"), Trigger.RATE_LIMIT),
        (RuntimeError("read timeout"), Trigger.TIMEOUT),
        (asyncio.TimeoutError(), Trigger.TIMEOUT),
        (RuntimeError("502 Bad Gateway"), Trigger.HTTP_5XX),
        (RuntimeError("network unreachable"), Trigger.NETWORK),
        (RuntimeError("connection refused"), Trigger.NETWORK),
        (RuntimeError("provider not available"), Trigger.NOT_AVAILABLE),
        (RuntimeError("something else entirely"), Trigger.UNKNOWN),
    ],
)
def test_trigger_classification(exc: Exception, expected: Trigger) -> None:
    """R7.11 twin: change one substring in _classify_exception -> its row fails."""

    def call_tier(tier: str, **_: object) -> dict:
        if tier == "fmp_cached":
            raise exc
        return {"ok": True}

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    _, outcome = chain.fetch()
    assert outcome.transitions[0].trigger is expected


# ---------------------------------------------------------------------------
# ChainedFetcher constructor guards
# ---------------------------------------------------------------------------


def test_chain_rejects_invalid_track() -> None:
    with pytest.raises(ValueError, match="track"):
        ChainedFetcher(
            endpoint="equity/header",
            track="C",
            tiers=("fmp_cached",),
            call_tier=lambda t, **k: None,
        )


def test_chain_rejects_empty_tier_list() -> None:
    """Empty chains would silently fail every call — reject at construction."""
    with pytest.raises(ValueError, match="non-empty"):
        ChainedFetcher(
            endpoint="equity/header",
            track="A",
            tiers=(),
            call_tier=lambda t, **k: None,
        )


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_track_key_rejects_bad_track() -> None:
    with pytest.raises(ValueError, match="track"):
        track_key("equity/header", "C")


def test_track_key_builds_lookup_key() -> None:
    assert track_key("equity/header", "A") == "equity/header:A"
    assert track_key("news", "B") == "news:B"


def test_registry_is_readonly() -> None:
    """Programmatic mutation must fail — the map is immutable at runtime."""
    with pytest.raises(TypeError):
        TIER_REGISTRY["equity/header:A"] = ()  # type: ignore[index]


def test_registry_covers_default_families() -> None:
    """Every family the retrofit plan expects has BOTH tracks registered."""
    expected_families = [
        "equity/header",
        "equity/key-stats",
        "equity/financials",
        "equity/price-history",
        "equity/technicals",
        "equity/institutional-ownership",
        "equity/insider-trading",
        "equity/company-filings",
        "events/calendar",
        "news",
        "xray/sector",
        "risk/dashboard",
    ]
    for family in expected_families:
        assert track_key(family, "A") in TIER_REGISTRY, f"missing A for {family}"
        assert track_key(family, "B") in TIER_REGISTRY, f"missing B for {family}"


# ---------------------------------------------------------------------------
# TierHealth allowlist
# ---------------------------------------------------------------------------


def test_tier_health_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="status"):
        TierHealth(name="fmp", status="broken", latency_ms=0)


def test_tier_health_rejects_note_outside_allowlist() -> None:
    """R7.11 twin: remove the allowlist check -> raw exception strings can leak."""
    with pytest.raises(ValueError, match="ALLOWED_NOTES"):
        TierHealth(name="fmp", status="down", latency_ms=0, note="some raw exc")


def test_tier_health_accepts_every_allowlist_note() -> None:
    for note in ALLOWED_NOTES:
        TierHealth(name="fmp", status="degraded", latency_ms=50, note=note)


# ---------------------------------------------------------------------------
# probe_tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_tier_returns_unknown_when_no_prober_registered() -> None:
    """Cold-cache / no prober: never lies about health."""
    unregister_prober("some_tier")
    h = await probe_tier("some_tier")
    assert h.status == "unknown"
    assert h.note == "probe_failed_cold_cache"


@pytest.mark.asyncio
async def test_probe_tier_healthy_on_fast_success() -> None:
    async def _p() -> None:
        return None

    register_prober("fake_fast", _p)
    try:
        h = await probe_tier("fake_fast")
        assert h.status == "healthy"
        assert h.note is None
    finally:
        unregister_prober("fake_fast")


@pytest.mark.asyncio
async def test_probe_tier_degraded_on_slow_success() -> None:
    """Latency >= 1000ms downgrades to degraded with high_latency note."""

    async def _slow() -> None:
        await asyncio.sleep(1.05)

    register_prober("fake_slow", _slow)
    try:
        h = await probe_tier("fake_slow", timeout_s=2.0)
        assert h.status == "degraded"
        assert h.note == "high_latency"
        assert h.latency_ms >= 1000
    finally:
        unregister_prober("fake_slow")


@pytest.mark.asyncio
async def test_probe_tier_down_on_timeout() -> None:
    """R7.11 twin: remove the asyncio.TimeoutError catch -> probe raises instead."""

    async def _hang() -> None:
        await asyncio.sleep(5.0)

    register_prober("fake_hang", _hang)
    try:
        h = await probe_tier("fake_hang", timeout_s=0.1)
        assert h.status == "down"
        assert h.note == "timeout"
    finally:
        unregister_prober("fake_hang")


@pytest.mark.asyncio
async def test_probe_tier_never_leaks_raw_exception_string() -> None:
    """R7.11 twin: bypass _classify_probe_exception -> raw msg leaks into note."""

    async def _boom() -> None:
        raise RuntimeError("PII_LEAK: user=daaji password=hunter2")

    register_prober("fake_boom", _boom)
    try:
        h = await probe_tier("fake_boom", timeout_s=0.5)
        assert h.status == "down"
        # Note is from the allowlist — cannot contain the raw exc string.
        assert h.note in ALLOWED_NOTES
        assert "PII_LEAK" not in (h.note or "")
    finally:
        unregister_prober("fake_boom")


# ---------------------------------------------------------------------------
# ChainOutcome shape
# ---------------------------------------------------------------------------


def test_chain_outcome_records_latency_for_every_attempted_tier() -> None:
    attempted = []

    def call_tier(tier: str, **_: object) -> object:
        attempted.append(tier)
        if tier in ("fmp_cached", "fmp"):
            raise RuntimeError(f"{tier} down")
        return {"ok": True}

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    _, outcome = chain.fetch()
    # 3 tiers attempted before cboe succeeds; latency recorded for all 3.
    assert set(outcome.latency_ms_per_tier) == {"fmp_cached", "fmp", "cboe"}
    assert all(isinstance(v, int) for v in outcome.latency_ms_per_tier.values())


def test_chain_outcome_at_is_iso8601_utc() -> None:
    def call_tier(tier: str, **_: object) -> dict:
        return {"ok": True}

    chain = ChainedFetcher(
        endpoint="equity/header", track="A", tiers=_tiers_A(), call_tier=call_tier
    )
    _, outcome = chain.fetch()
    # 2026-08-02T14:00:00+00:00 shape — has both a T separator and a +tz.
    assert "T" in outcome.at
    assert "+" in outcome.at or outcome.at.endswith("Z")


def test_chain_outcome_is_dataclass_shape() -> None:
    """Sanity: ChainOutcome remains a dataclass (public consumer contract)."""
    outcome = ChainOutcome(endpoint="x", track="A", tier_used=None)
    assert outcome.endpoint == "x"
    assert outcome.transitions == []
    assert outcome.latency_ms_per_tier == {}
