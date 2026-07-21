"""Coverage gate for the fmp_cached ``@pytest.mark.record_http`` suite (#508).

Ensures every registered endpoint in ``fmp_cached_provider.fetcher_dict``
either has a checked-in VCR cassette OR is on the explicit
``_KNOWN_UNCOVERED`` allowlist.

Rationale: without this test, a contributor adding a new endpoint to the
provider (e.g. registering ``FMPCachedNewEndpointFetcher`` in
``__init__.py``) can forget to record a cassette. The offline test suite
would then hit live FMP on the first CI run — either surfacing as a 401
in CI, or as a wall-of-red only during code review, or as a silent live
call that leaks the CI env's key.

This test fails loud the moment coverage regresses.

The allowlist itself is technical debt — every entry should have a
follow-up issue explaining why that endpoint isn't fixture-covered yet
(usually: multi-symbol shape, POST body, or a subscription-tier
endpoint the recording key can't reach).
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "record" / "http" / "test_fmp_cached_fetchers"

# Endpoints known to be intentionally uncovered, with the follow-up
# issue tracking each. Do NOT add entries here without also filing a
# GH issue with the ``fmp-fixture-gap`` label.
#
# Every entry MUST have a follow-up issue cited; empty follow-up = merge
# blocker (the coverage-gate is meant to *surface* debt, not hide it).
_KNOWN_UNCOVERED: dict[str, str] = {
    # First-cut (#508) shipped 10 cassettes; batch 1 (#955) added 14 more.
    # 51 endpoints remaining — tracked in #955 for phased draining.
    # Each has "drain to zero via #955" as its citation. When a cassette
    # lands for one of these, remove the entry — the
    # test_kicked_out_of_allowlist_when_cassette_lands test will fail
    # loudly if you forget.
    "AftermarketQuote": "drain to zero via #955",
    "AftermarketTrade": "drain to zero via #955",
    # Calendar endpoints (Dividend/Earnings/Splits/Ipo): Fetcher.test()
    # asserts query params round-trip as strings, but the pydantic model
    # coerces str→date. Assertion fails even when HTTP round-trips fine.
    # Needs test-time param workaround. Follow-up via #955.
    "CalendarDividend": "drain to zero via #955 (Fetcher.test date-coercion assertion mismatch)",
    "CalendarEarnings": "drain to zero via #955 (Fetcher.test date-coercion assertion mismatch)",
    "CalendarIpo": "drain to zero via #955 (Fetcher.test date-coercion assertion mismatch)",
    "CalendarSplits": "drain to zero via #955 (Fetcher.test date-coercion assertion mismatch)",
    "CryptoHistorical": "drain to zero via #955",
    "CryptoSearch": "drain to zero via #955 (FMP 402 — paid subscription tier)",
    "CurrencyHistorical": "drain to zero via #955",
    "CurrencySnapshots": "drain to zero via #955 (FMP 402 — paid subscription tier)",
    "DiscoveryFilings": "drain to zero via #955",
    "EarningsCallTranscript": "drain to zero via #955 (FMP 402 — paid subscription tier)",
    "EconomicCalendar": "drain to zero via #955",
    "EquityActive": "drain to zero via #955 (FMP 402 — paid subscription tier)",
    "EquityIntradayHistorical": "drain to zero via #955",
    "EquityOwnership": "drain to zero via #955 (FMP 402 — endpoint requires paid subscription tier)",
    "EquityQuoteBatchShort": "drain to zero via #955",
    "EquityScreener": "drain to zero via #955",
    "EsgScore": "drain to zero via #955 (FMP 402 — endpoint requires paid subscription tier)",
    "EtfEquityExposure": "drain to zero via #955",
    "EtfHistorical": "drain to zero via #955",
    "EtfPricePerformance": "drain to zero via #955 (recording failed silently — cassette not produced; likely paid tier or 402)",
    "ExchangeMarketHours": "drain to zero via #955",
    "GovernmentTrades": "drain to zero via #955",
    "IndexConstituents": "drain to zero via #955",
    "IndexHistorical": "drain to zero via #955",
    "InsiderTrading": "drain to zero via #955",
    "InstitutionalOwnership": "drain to zero via #955",
    "MarketSnapshots": "drain to zero via #955 (FMP 402 — paid subscription tier)",
    "NportDisclosure": "drain to zero via #955",
    # PricePerformance: fetcher chunks HTTP calls (multi-symbol batching)
    # in a way pytest-recorder can't cleanly capture — batch 1 recording
    # SKIPPED. Needs a bespoke cassette approach OR the batch shim needs
    # reshaping to single-request. Follow-up in #955.
    "PricePerformance": "drain to zero via #955 (chunk-batching not captured by pytest-recorder — needs special handling)",
    "RiskPremium": "drain to zero via #955",
    "TechnicalIndicatorIntraday": "drain to zero via #955",
    "YieldCurve": "drain to zero via #955",
}

# Endpoint-name → test-function suffix. Most follow the convention
# ``CamelCaseName`` → ``camel_case_name``. Overrides live here for the
# few that don't (e.g. "EquityInfo" tests are named
# "test_fmp_cached_equity_profile_fetcher" because that's the model
# they exercise).
_ENDPOINT_TO_TEST_STEM_OVERRIDES: dict[str, str] = {
    # The registered key is EquityInfo but the model + fetcher class
    # + our test function all use "equity_profile" naming.
    "EquityInfo": "equity_profile",
    # CashFlowStatement → cash_flow (per test name convention)
    "CashFlowStatement": "cash_flow",
    "CashFlowStatementGrowth": "cash_flow_growth",
}


def _endpoint_to_test_stem(endpoint: str) -> str:
    """Convert CamelCase endpoint name to snake_case test-fn suffix."""
    if endpoint in _ENDPOINT_TO_TEST_STEM_OVERRIDES:
        return _ENDPOINT_TO_TEST_STEM_OVERRIDES[endpoint]
    out = []
    for i, c in enumerate(endpoint):
        if c.isupper() and i > 0:
            out.append("_")
        out.append(c.lower())
    return "".join(out)


def _cassette_exists_for(endpoint: str) -> bool:
    stem = _endpoint_to_test_stem(endpoint)
    # Cassette naming: test_fmp_cached_<stem>_fetcher_urllib3_v2.yaml
    candidates = list(FIXTURES_DIR.glob(f"test_fmp_cached_{stem}_fetcher_*.yaml"))
    return len(candidates) > 0


def test_every_registered_endpoint_has_cassette_or_is_allowlisted() -> None:
    """The core coverage gate — regresses loudly on any silent gap.

    Note: this is a documentation test, not a behavior test. It won't
    prevent someone from hitting live FMP if they run tests offline
    without cassettes — that would still fail-loud via
    pytest-recorder's own "no cassette" error. This test's job is to
    fail *in CI* on the PR that ADDS the uncovered endpoint, so the
    gap is caught pre-merge, not post-merge on the first offline run.
    """
    from openbb_fmp_cached import fmp_cached_provider

    registered = set(fmp_cached_provider.fetcher_dict.keys())
    covered = {e for e in registered if _cassette_exists_for(e)}
    allowlisted = set(_KNOWN_UNCOVERED)
    gap = registered - covered - allowlisted

    if gap:
        gap_list = "\n".join(f"  - {e}" for e in sorted(gap))
        pytest.fail(
            f"{len(gap)} fmp_cached endpoint(s) have no cassette AND no allowlist entry:\n"
            f"{gap_list}\n\n"
            "To fix, either:\n"
            "  1) Record a cassette: python scripts/pi_fmp_record.py --endpoint <stem>\n"
            "  2) Add to _KNOWN_UNCOVERED below with a follow-up GH issue number\n"
            "     (must have the 'fmp-fixture-gap' label; do not add blanket entries)\n"
        )


def test_allowlist_entries_have_follow_up_issue_citations() -> None:
    """Every _KNOWN_UNCOVERED entry must cite a GH issue number.

    Prevents drift where someone adds an allowlist entry to make CI
    green without accepting the debt formally.
    """
    for endpoint, note in _KNOWN_UNCOVERED.items():
        assert "#" in note or "gh-" in note, (
            f"allowlist entry for {endpoint!r} lacks a GH issue reference: "
            f"{note!r}. Every allowlist entry must cite the tracking issue "
            "(e.g. 'follow-up #NN')."
        )


def test_kicked_out_of_allowlist_when_cassette_lands() -> None:
    """Anti-drift: allowlist entries must correspond to REGISTERED endpoints
    that also lack a cassette. If someone adds a cassette but forgets to
    remove the allowlist entry, this test catches the stale entry.
    """
    from openbb_fmp_cached import fmp_cached_provider

    registered = set(fmp_cached_provider.fetcher_dict.keys())
    stale = []
    for endpoint in _KNOWN_UNCOVERED:
        if endpoint not in registered:
            stale.append(f"{endpoint} (not registered)")
        elif _cassette_exists_for(endpoint):
            stale.append(f"{endpoint} (has cassette — remove from allowlist)")
    assert not stale, "Stale _KNOWN_UNCOVERED entries — remove them: " + ", ".join(
        stale
    )
