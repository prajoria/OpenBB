"""Plan-limited endpoint registry (Wave 0 A3 / #1316).

Structured registry of endpoints where our current FMP plan tier
cannot successfully call the endpoint (typically 402 Payment Required
from FMP's paid-tier gate). Downstream wave-task authors read this
BEFORE writing a wrapper so they don't waste time recording a
cassette that will never succeed.

Contrast with ``_KNOWN_UNCOVERED`` in ``test_fetcher_dict_coverage.py``:
- ``_KNOWN_UNCOVERED`` is a flat string-note allowlist; the gate reads
  it as "these endpoints don't have cassettes; they're tracked".
- ``_PLAN_LIMITED`` here is a structured registry with per-entry
  ``tier`` + ``since`` + ``notes``. Downstream code can programmatically
  check ``is_plan_limited("EsgScore") -> True`` and decide to skip the
  entire wrapper.

Discovery process (used to build this registry):
1. Run ``python scripts/pi_fmp_record.py --endpoint <stem>`` against the
   fmp_cached test suite.
2. If cassette recording produces a 402 or fails with "Payment Required",
   add an entry here documenting (tier, discovery date, endpoint URL).
3. Downstream wave-task PR body cites this registry and skips fetcher
   authoring for plan-limited endpoints; those get filed as
   ``area:plan-limited`` follow-ups instead.

Seeded from the #955 fixture drain findings (2026-07-21):
10 endpoints identified as permanently 402 on our Starter tier.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict


class PlanLimitedEntry(TypedDict):
    """One row in the _PLAN_LIMITED registry."""

    tier: str  # FMP plan tier that WOULD unlock the endpoint (Starter / Premium / Ultimate)
    since: date  # When we discovered the block
    notes: str  # Free-form context (endpoint URL, related issue, etc.)


_PLAN_LIMITED: dict[str, PlanLimitedEntry] = {
    "CryptoSearch": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "CurrencySnapshots": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EarningsCallTranscript": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EquityActive": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EquityOwnership": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EsgScore": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EtfEquityExposure": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EtfPricePerformance": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter or recording anomaly (#955)",
    },
    "IndexConstituents": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "InstitutionalOwnership": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "MarketSnapshots": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter (#955 drain batch 2)",
    },
    "EarningsTranscriptList": {
        "tier": "Premium",
        "since": date(2026, 7, 21),
        "notes": "402 on Starter — /stable/earnings-transcript-list is a Premium-tier endpoint (#1051 W4 drain batch 5)",
    },
    "BatchIndexQuotes": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-index-quotes (#1161 #1260 W2 drain)",
    },
    "BatchCommodityQuotes": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-commodity-quotes (#1176 #1257 W2 drain)",
    },
    "BatchCryptoQuotes": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-crypto-quotes (#1185 #1258 W2 drain)",
    },
    "BatchForexQuotes": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-forex-quotes (#1200 #1259 W2 drain)",
    },
    "BatchMutualfundQuotes": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-mutualfund-quotes (#1255 W2 drain)",
    },
    "BatchEtfQuotes": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-etf-quotes (#1256 W2 drain)",
    },
    "BatchExchangeQuote": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/batch-exchange-quote (#1254 W2 drain)",
    },
}


def is_plan_limited(endpoint: str) -> bool:
    """Return True if the endpoint is known-blocked by our plan tier."""
    return endpoint in _PLAN_LIMITED


def get_plan_limit(endpoint: str) -> PlanLimitedEntry | None:
    """Return the full registry entry for an endpoint, or None."""
    return _PLAN_LIMITED.get(endpoint)


def all_plan_limited() -> dict[str, PlanLimitedEntry]:
    """Return a shallow copy of the full registry (for reporting)."""
    return dict(_PLAN_LIMITED)
