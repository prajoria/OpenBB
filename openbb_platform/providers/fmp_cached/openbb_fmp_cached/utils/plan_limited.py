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
    "IncomeStatementTtm": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/income-statement-ttm (#1127 W1 drain)",
    },
    "BalanceSheetStatementTtm": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/balance-sheet-statement-ttm (#1128 W1 drain)",
    },
    "CashFlowStatementTtm": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/cash-flow-statement-ttm (#1129 W1 drain)",
    },
    "LatestFinancialStatements": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/latest-financial-statements (#1126 W1 drain)",
    },
    # W5 EtfAndMutualFunds - funds/disclosure family (all 4 Premium)
    "FundsDisclosureHoldersLatest": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/funds/disclosure-holders-latest (#1119 W5 drain)",
    },
    "FundsDisclosure": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/funds/disclosure (#1120 W5 drain)",
    },
    "FundsDisclosureHoldersSearch": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/funds/disclosure-holders-search (#1121 W5 drain)",
    },
    "FundsDisclosureDates": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/funds/disclosure-dates (#1122 W5 drain)",
    },
    # W8 ESG benchmark
    "EsgBenchmark": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/esg-benchmark (#1113 W8 drain)",
    },
    # W8 Bulk endpoints — 18 endpoints, all Premium
    "ProfileBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/profile-bulk (#1289 W8 drain)",
    },
    "RatingBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/rating-bulk (#1290 W8 drain)",
    },
    "DcfBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/dcf-bulk (#1291 W8 drain)",
    },
    "ScoresBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/scores-bulk (#1292 W8 drain)",
    },
    "PriceTargetSummaryBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/price-target-summary-bulk (#1293 W8 drain)",
    },
    "EtfHolderBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/etf-holder-bulk (#1294 W8 drain)",
    },
    "UpgradesDowngradesConsensusBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/upgrades-downgrades-consensus-bulk (#1295 W8 drain)",
    },
    "KeyMetricsTtmBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/key-metrics-ttm-bulk (#1296 W8 drain)",
    },
    "RatiosTtmBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/ratios-ttm-bulk (#1297 W8 drain)",
    },
    "PeersBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/peers-bulk (#1298 W8 drain)",
    },
    "EarningsSurprisesBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/earnings-surprises-bulk (#1299 W8 drain)",
    },
    "IncomeStatementBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/income-statement-bulk (#1300 W8 drain)",
    },
    "IncomeStatementGrowthBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/income-statement-growth-bulk (#1301 W8 drain)",
    },
    "BalanceSheetStatementBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/balance-sheet-statement-bulk (#1302 W8 drain)",
    },
    "BalanceSheetStatementGrowthBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/balance-sheet-statement-growth-bulk (#1303 W8 drain)",
    },
    "CashFlowStatementBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/cash-flow-statement-bulk (#1304 W8 drain)",
    },
    "CashFlowStatementGrowthBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/cash-flow-statement-growth-bulk (#1305 W8 drain)",
    },
    "EodBulk": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/eod-bulk (#1306 W8 drain)",
    },
    # W8 Partners — TipRanks (7 endpoints, all Premium)
    "TipranksSearch": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-search (#1307 W8 drain)",
    },
    "TipranksPitSymbol": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-pit-symbol (#1308 W8 drain)",
    },
    "TipranksPitAnalyst": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-pit-analyst (#1309 W8 drain)",
    },
    "TipranksSymbolSummary": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-symbol-summary (#1310 W8 drain)",
    },
    "TipranksAnalystSummary": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-analyst-summary (#1311 W8 drain)",
    },
    "TipranksFirmSummary": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-firm-summary (#1312 W8 drain)",
    },
    "TipranksAnalysts": {
        "tier": "Premium",
        "since": date(2026, 7, 22),
        "notes": "402 on Starter — /stable/tipranks-analysts (#1313 W8 drain)",
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
