# Phase 0: FMP + fmp_cached Parity Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the six new intraday FMP fetchers in **both** `openbb_fmp` and `openbb_fmp_cached` (tier-2 passthrough) and stand up the two CI guardrails (parity + provider-purity) so the `openbb-fmp-trading` extension work in Phase 1+ has a clean substrate to build on.

**Architecture:** Two orthogonal deliverables land in the same phase. (a) Six new stateless FMP fetcher classes under `openbb_fmp/models/` — each targeting a `/stable/*` intraday endpoint (bars, aftermarket quote/trade, batch quote short, exchange market hours, technical indicator) — registered in `openbb_fmp/__init__.py`'s `fetcher_dict`. (b) Six matching entries in `openbb_fmp_cached/__init__.py` via the existing `create_fallback_fetcher_class` wrapper from `base_cached.py` (which handles the `fmp_cached_api_key → fmp_api_key` credential translation). Real tier-1 caching for two of the six (intraday bars + aftermarket quote) is deferred to Phase 2 per PRD §10; Phase 0 ships tier-2-safe versions everywhere so parity holds from day one.

**Tech Stack:** Python 3.10-3.13 (dev on 3.12), `openbb-core` v4.6.0+, Pydantic v2, `pytest`, `httpx` (via `openbb_core.provider.utils.helpers.amake_request`). Env: `.venv_win`.

## Global Constraints

- **Python interpreter:** always the project venv — `.venv_win\Scripts\python.exe`. Never system python; extensions are editable-installed only into `.venv_win`.
- **openbb-core:** v4.6.0+; every fetcher inherits `openbb_core.provider.abstract.fetcher.Fetcher[QueryParams, list[Data]]`.
- **Full parity is a CI invariant.** `set(fmp_provider.fetcher_dict.keys()) ⊂ set(fmp_cached_provider.fetcher_dict.keys())` — new architecture test in Task 2 enforces this on every commit.
- **Provider purity is a CI invariant.** No `provider="fmp"` string may appear in application/extension code — always `provider="fmp_cached"`. New architecture test in Task 1 enforces this via grep.
- **Every commit message ends with** `Co-Authored-By: Claude <noreply@anthropic.com>` per `CLAUDE.md`.
- **Reference issue in commit trailers:** epic #87 (P9 (future) — streaming/intraday + live broker) and the PRD path `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`.
- **`fmp_cached` credentials:** the wrapper translates `fmp_cached_api_key → fmp_api_key`. Tests that hit real network read from `~/.openbb_platform/user_settings.json`.
- **Do not touch generated code.** `openbb_platform/core/openbb/package/` churn stays out of every commit.

---

## File Structure

All paths relative to repo root `H:\masterswork\git\OpenBBTradingView\`:

| File | Responsibility |
|---|---|
| `openbb_platform/tests/architecture/__init__.py` | Test package marker (new subdir). |
| `openbb_platform/tests/architecture/test_provider_purity.py` | Grep guardrail — asserts no `provider="fmp"` in extension/app code. (P0.4) |
| `openbb_platform/tests/architecture/test_provider_parity.py` | Asserts `set(fmp) ⊂ set(fmp_cached)`. (P0.3) |
| `openbb_platform/providers/fmp/openbb_fmp/models/equity_intraday_historical.py` | Fetcher for `/stable/historical-chart/{interval}` — the highest-volume intraday endpoint. |
| `openbb_platform/providers/fmp/openbb_fmp/models/aftermarket_quote.py` | Fetcher for `/stable/aftermarket-quote`. |
| `openbb_platform/providers/fmp/openbb_fmp/models/aftermarket_trade.py` | Fetcher for `/stable/aftermarket-trade`. |
| `openbb_platform/providers/fmp/openbb_fmp/models/equity_quote_batch_short.py` | Fetcher for `/stable/batch-quote-short` — the "cheap poll" endpoint (uncached by design). |
| `openbb_platform/providers/fmp/openbb_fmp/models/exchange_market_hours.py` | Fetcher for `/stable/all-exchange-market-hours`. |
| `openbb_platform/providers/fmp/openbb_fmp/models/technical_indicator_intraday.py` | Fetcher for `/stable/technical-indicators/{indicator}`. |
| `openbb_platform/providers/fmp/openbb_fmp/__init__.py` | Add six new import lines + six new `fetcher_dict` entries. |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py` | Add six new import lines + six new `fetcher_mapping` entries (all tier-2 initially). |
| `docs/superpowers/plans/2026-07-06-fmp-trading-phase-0-parity.md` | This plan document itself. |

Modified (small edits only):
- `openbb_platform/providers/fmp/openbb_fmp/__init__.py` (append 6 imports + 6 dict rows)
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py` (append 6 imports + 6 mapping tuples)

> **Out of scope for Phase 0** (deferred to later phases per PRD §10):
> - Tier-1 caching upgrades for `EquityIntradayHistorical` + `AftermarketQuote` (Phase 2, P2.1)
> - `create_ttl_wrapper_class` in `base_cached.py` for `ExchangeMarketHours` (Phase 2, P2.2)
> - Extension scaffold `openbb_platform/extensions/fmp_trading/` (Phase 1)
> - Any signal, plan, or session code (Phases 2-6)

---

## Task 1: Provider-purity CI guardrail (P0.4) — RED-first

**Files:**
- Create: `openbb_platform/tests/architecture/__init__.py`
- Create: `openbb_platform/tests/architecture/test_provider_purity.py`

Land this **first**, before any extension code exists, so every subsequent PR is gated by it. The grep test scans repo-wide for `provider="fmp"` (or `provider='fmp'`) and asserts it appears **only** in approved locations (fmp/fmp_cached provider tests and provider docstrings). Any extension code that adds a bad `provider=` string fails CI immediately.

- [ ] **Step 1: Create the architecture test package marker**

Create `openbb_platform/tests/architecture/__init__.py`:

```python
"""Architecture-level CI guardrails (parity, purity, chokepoints)."""
```

- [ ] **Step 2: Write the failing test**

Create `openbb_platform/tests/architecture/test_provider_purity.py`:

```python
"""CI guardrail: no application/extension code may call `provider="fmp"` directly.

The fmp_trading extension and all downstream consumers must always route
through fmp_cached to preserve the caching invariants and bandwidth budget
(PRD §5.4). Only the provider packages themselves, provider tests, and this
architecture test may reference the bare "fmp" provider string.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]  # openbb_platform/tests/architecture -> repo

# Directories that MAY reference provider="fmp" (provider impls + their own tests):
ALLOWED_SUBTREES: tuple[str, ...] = (
    "openbb_platform/providers/fmp/",
    "openbb_platform/providers/fmp_cached/",
    "openbb_platform/tests/architecture/",  # this test file itself
)

# Directories that must be scanned (extension code + shared app code):
SCAN_SUBTREES: tuple[str, ...] = (
    "openbb_platform/extensions/",
    "Analysis/",
    "cli/",
)

# Matches:  provider="fmp"   provider='fmp'   provider = "fmp"
PATTERN = re.compile(r"""provider\s*=\s*["']fmp["']""")


def _iter_py_files(subtree: str) -> list[Path]:
    root = REPO_ROOT / subtree
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


@pytest.mark.parametrize("subtree", SCAN_SUBTREES)
def test_no_bare_fmp_provider_in_app_code(subtree: str) -> None:
    """Assert `provider="fmp"` never appears in extension/app code."""
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_py_files(subtree):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if any(rel.startswith(a) for a in ALLOWED_SUBTREES):
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if PATTERN.search(line):
                offenders.append((path, lineno, line.strip()))

    assert not offenders, (
        "Found `provider=\"fmp\"` in application/extension code; must use "
        '`provider="fmp_cached"` per PRD §5.4.\n\nOffenders:\n'
        + "\n".join(f"  {p}:{ln}: {src}" for p, ln, src in offenders)
    )
```

- [ ] **Step 3: Run to verify it PASSES (baseline is clean)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/tests/architecture/test_provider_purity.py -v`

Expected: `3 passed` (one per `SCAN_SUBTREES` entry). If any offender exists today, the test correctly fails and lists them — fix or add to `ALLOWED_SUBTREES` before proceeding.

- [ ] **Step 4: Commit the guardrail**

```bash
git add openbb_platform/tests/architecture/__init__.py openbb_platform/tests/architecture/test_provider_purity.py
git commit -m "test(architecture): CI guardrail against provider=\"fmp\" in app code (#87)

Grep-based architecture test — asserts no application or extension code
carries a bare provider=\"fmp\" string; only fmp_cached is permitted downstream
per fmp-day-trading PRD §5.4. Approved subtrees: providers/fmp/,
providers/fmp_cached/, tests/architecture/.

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.4

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Parity CI test (P0.3) — RED-first (drives Tasks 3-6)

**Files:**
- Create: `openbb_platform/tests/architecture/test_provider_parity.py`

Land this **before** the fetchers so the test drives their addition. Test fails until all six new fetcher keys appear in *both* `fmp_provider.fetcher_dict` and `fmp_cached_provider.fetcher_dict`.

- [ ] **Step 1: Write the failing test**

Create `openbb_platform/tests/architecture/test_provider_parity.py`:

```python
"""CI guardrail: every fmp fetcher key must exist in fmp_cached.

Enforces PRD §5 acceptance criterion AC-parity-1:
    set(fmp_provider.fetcher_dict) ⊂ set(fmp_cached_provider.fetcher_dict)

Also asserts the six new Phase-0 intraday fetchers land in both providers
in the same commit (no drift window).
"""

from __future__ import annotations

import pytest

# Fetcher keys introduced by the fmp-day-trading PRD Phase 0 (PRD §5.1 matrix).
# Each MUST land in both providers before this test goes green.
PRD_PHASE_0_FETCHERS: frozenset[str] = frozenset(
    {
        "EquityIntradayHistorical",
        "AftermarketQuote",
        "AftermarketTrade",
        "EquityQuoteBatchShort",
        "ExchangeMarketHours",
        "TechnicalIndicatorIntraday",
    }
)


@pytest.fixture(scope="module")
def fmp_keys() -> frozenset[str]:
    from openbb_fmp import fmp_provider

    return frozenset(fmp_provider.fetcher_dict.keys())


@pytest.fixture(scope="module")
def fmp_cached_keys() -> frozenset[str]:
    from openbb_fmp_cached import fmp_cached_provider

    return frozenset(fmp_cached_provider.fetcher_dict.keys())


def test_fmp_keys_subset_of_fmp_cached(
    fmp_keys: frozenset[str], fmp_cached_keys: frozenset[str]
) -> None:
    """AC-parity-1: fmp is a subset of fmp_cached."""
    missing = fmp_keys - fmp_cached_keys
    assert not missing, (
        f"{len(missing)} fmp fetcher(s) missing from fmp_cached: "
        f"{sorted(missing)}\n\n"
        "Every fmp fetcher MUST have an fmp_cached twin registered in the "
        "same commit (PRD §5, AC-parity-1)."
    )


def test_prd_phase_0_fetchers_in_fmp(fmp_keys: frozenset[str]) -> None:
    """All six Phase-0 fetchers registered in openbb_fmp."""
    missing = PRD_PHASE_0_FETCHERS - fmp_keys
    assert not missing, (
        f"Phase-0 fetchers not yet registered in openbb_fmp: {sorted(missing)}"
    )


def test_prd_phase_0_fetchers_in_fmp_cached(
    fmp_cached_keys: frozenset[str],
) -> None:
    """All six Phase-0 fetchers registered in openbb_fmp_cached."""
    missing = PRD_PHASE_0_FETCHERS - fmp_cached_keys
    assert not missing, (
        f"Phase-0 fetchers not yet registered in openbb_fmp_cached: "
        f"{sorted(missing)}"
    )
```

- [ ] **Step 2: Run to verify it FAILS on the six new keys**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/tests/architecture/test_provider_parity.py -v`

Expected:
- `test_fmp_keys_subset_of_fmp_cached` — **PASS** (existing keys are already parity-aligned)
- `test_prd_phase_0_fetchers_in_fmp` — **FAIL** listing all six missing keys
- `test_prd_phase_0_fetchers_in_fmp_cached` — **FAIL** listing all six missing keys

- [ ] **Step 3: Commit the failing test (drives the next tasks)**

```bash
git add openbb_platform/tests/architecture/test_provider_parity.py
git commit -m "test(architecture): parity contract for fmp/fmp_cached (#87)

RED-first parity test: asserts set(fmp) ⊂ set(fmp_cached), and pins the
six Phase-0 intraday fetchers (EquityIntradayHistorical, AftermarketQuote,
AftermarketTrade, EquityQuoteBatchShort, ExchangeMarketHours,
TechnicalIndicatorIntraday) as required keys in both providers.

Currently 2 of 3 assertions fail — drives Tasks 3-6 of Phase 0.

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.3

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: FMP fetchers 1-3 — intraday bars + aftermarket

**Files:**
- Create: `openbb_platform/providers/fmp/openbb_fmp/models/equity_intraday_historical.py`
- Create: `openbb_platform/providers/fmp/openbb_fmp/models/aftermarket_quote.py`
- Create: `openbb_platform/providers/fmp/openbb_fmp/models/aftermarket_trade.py`

- [ ] **Step 1: Create `equity_intraday_historical.py`** (fetcher #1)

```python
"""FMP Equity Intraday Historical Bar Model — /stable/historical-chart/{interval}."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

IntradayInterval = Literal["1min", "5min", "15min", "30min", "1hour", "4hour"]


class FMPEquityIntradayHistoricalQueryParams(QueryParams):
    """FMP Equity Intraday Historical Query.

    Source: https://site.financialmodelingprep.com/developer/docs#historical-chart
    """

    __alias_dict__ = {"start_date": "from", "end_date": "to"}
    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}

    symbol: str = Field(description="Symbol or comma-separated symbols.")
    interval: IntradayInterval = Field(
        default="5min", description="Bar interval."
    )
    start_date: datetime | None = Field(
        default=None, description="Start of bar window (inclusive)."
    )
    end_date: datetime | None = Field(
        default=None, description="End of bar window (inclusive)."
    )
    extended_hours: bool = Field(
        default=False, description="Include pre-/post-market bars."
    )


class FMPEquityIntradayHistoricalData(Data):
    """FMP Equity Intraday Historical Bar."""

    symbol: str = Field(description="Ticker symbol.")
    interval: IntradayInterval = Field(description="Bar interval.")
    date: datetime = Field(description="Bar-start timestamp (exchange local, tz-naive).")
    open: float = Field(description="Opening price of the bar.")
    high: float = Field(description="High price of the bar.")
    low: float = Field(description="Low price of the bar.")
    close: float = Field(description="Closing price of the bar.")
    volume: int = Field(description="Bar volume.")


class FMPEquityIntradayHistoricalFetcher(
    Fetcher[
        FMPEquityIntradayHistoricalQueryParams,
        list[FMPEquityIntradayHistoricalData],
    ]
):
    """FMP Equity Intraday Historical Bar Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPEquityIntradayHistoricalQueryParams:
        """Transform the query params."""
        return FMPEquityIntradayHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityIntradayHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return raw bars from FMP for one or many symbols."""
        # pylint: disable=import-outside-toplevel
        import asyncio

        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        base = (
            f"https://financialmodelingprep.com/stable/historical-chart/{query.interval}"
        )
        symbols = [s.strip() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        async def get_one(sym: str) -> None:
            url = f"{base}?symbol={sym}&apikey={api_key}"
            if query.start_date is not None:
                url += f"&from={query.start_date.date().isoformat()}"
            if query.end_date is not None:
                url += f"&to={query.end_date.date().isoformat()}"
            data = await amake_request(
                url, response_callback=response_callback, **kwargs
            )
            for row in data or []:
                row["symbol"] = sym
                row["interval"] = query.interval
                results.append(row)

        await asyncio.gather(*(get_one(s) for s in symbols))

        if not results:
            raise EmptyDataError("No intraday bars returned from FMP.")
        return results

    @staticmethod
    def transform_data(
        query: FMPEquityIntradayHistoricalQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEquityIntradayHistoricalData]:
        """Transform to typed rows, sorted (symbol, date)."""
        return [
            FMPEquityIntradayHistoricalData.model_validate(d)
            for d in sorted(data, key=lambda r: (r["symbol"], r["date"]))
        ]
```

- [ ] **Step 2: Create `aftermarket_quote.py`** (fetcher #2)

```python
"""FMP Aftermarket Quote Model — /stable/aftermarket-quote."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator


class FMPAftermarketQuoteQueryParams(QueryParams):
    """FMP Aftermarket Quote Query.

    Source: https://site.financialmodelingprep.com/developer/docs#aftermarket-quote
    """

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    symbol: str = Field(description="Symbol or comma-separated symbols.")


class FMPAftermarketQuoteData(Data):
    """FMP Aftermarket Quote."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Last aftermarket price.")
    bid: float | None = Field(default=None, description="Best bid.")
    ask: float | None = Field(default=None, description="Best ask.")
    bid_size: int | None = Field(default=None, description="Bid size.")
    ask_size: int | None = Field(default=None, description="Ask size.")
    volume: int | None = Field(default=None, description="Aftermarket volume.")
    timestamp: datetime | None = Field(
        default=None, description="Quote timestamp (UTC)."
    )

    @field_validator("timestamp", mode="before", check_fields=False)
    @classmethod
    def _epoch_ms_to_datetime(cls, v: int | str | None):
        """FMP returns epoch milliseconds — convert to naive UTC datetime."""
        if v in (None, ""):
            return None
        try:
            i = int(v)
            return datetime.utcfromtimestamp(i / 1000 if i > 10**11 else i)
        except (TypeError, ValueError):
            return None


class FMPAftermarketQuoteFetcher(
    Fetcher[
        FMPAftermarketQuoteQueryParams,
        list[FMPAftermarketQuoteData],
    ]
):
    """FMP Aftermarket Quote Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPAftermarketQuoteQueryParams:
        return FMPAftermarketQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPAftermarketQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        import asyncio

        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        base = "https://financialmodelingprep.com/stable/aftermarket-quote"
        symbols = [s.strip() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        async def get_one(sym: str) -> None:
            url = f"{base}?symbol={sym}&apikey={api_key}"
            data = await amake_request(
                url, response_callback=response_callback, **kwargs
            )
            for row in data or []:
                row.setdefault("symbol", sym)
                results.append(row)

        await asyncio.gather(*(get_one(s) for s in symbols))
        if not results:
            raise EmptyDataError("No aftermarket quotes returned from FMP.")
        return results

    @staticmethod
    def transform_data(
        query: FMPAftermarketQuoteQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPAftermarketQuoteData]:
        return [FMPAftermarketQuoteData.model_validate(d) for d in data]
```

- [ ] **Step 3: Create `aftermarket_trade.py`** (fetcher #3)

```python
"""FMP Aftermarket Trade Model — /stable/aftermarket-trade."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator


class FMPAftermarketTradeQueryParams(QueryParams):
    """FMP Aftermarket Trade Query.

    Source: https://site.financialmodelingprep.com/developer/docs#aftermarket-trade
    """

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    symbol: str = Field(description="Symbol or comma-separated symbols.")


class FMPAftermarketTradeData(Data):
    """FMP Aftermarket Trade (last print)."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Trade price.")
    size: int | None = Field(default=None, description="Trade size (shares).")
    timestamp: datetime | None = Field(
        default=None, description="Trade timestamp (UTC)."
    )

    @field_validator("timestamp", mode="before", check_fields=False)
    @classmethod
    def _epoch_ms_to_datetime(cls, v):
        if v in (None, ""):
            return None
        try:
            i = int(v)
            return datetime.utcfromtimestamp(i / 1000 if i > 10**11 else i)
        except (TypeError, ValueError):
            return None


class FMPAftermarketTradeFetcher(
    Fetcher[
        FMPAftermarketTradeQueryParams,
        list[FMPAftermarketTradeData],
    ]
):
    """FMP Aftermarket Trade Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPAftermarketTradeQueryParams:
        return FMPAftermarketTradeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPAftermarketTradeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        import asyncio

        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        base = "https://financialmodelingprep.com/stable/aftermarket-trade"
        symbols = [s.strip() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        async def get_one(sym: str) -> None:
            url = f"{base}?symbol={sym}&apikey={api_key}"
            data = await amake_request(
                url, response_callback=response_callback, **kwargs
            )
            for row in data or []:
                row.setdefault("symbol", sym)
                results.append(row)

        await asyncio.gather(*(get_one(s) for s in symbols))
        if not results:
            raise EmptyDataError("No aftermarket trades returned from FMP.")
        return results

    @staticmethod
    def transform_data(
        query: FMPAftermarketTradeQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPAftermarketTradeData]:
        return [FMPAftermarketTradeData.model_validate(d) for d in data]
```

- [ ] **Step 4: Verify all three modules import cleanly**

Run:
```bash
.venv_win\Scripts\python.exe -c "from openbb_fmp.models.equity_intraday_historical import FMPEquityIntradayHistoricalFetcher; from openbb_fmp.models.aftermarket_quote import FMPAftermarketQuoteFetcher; from openbb_fmp.models.aftermarket_trade import FMPAftermarketTradeFetcher; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 5: Commit fetchers 1-3**

```bash
git add openbb_platform/providers/fmp/openbb_fmp/models/equity_intraday_historical.py openbb_platform/providers/fmp/openbb_fmp/models/aftermarket_quote.py openbb_platform/providers/fmp/openbb_fmp/models/aftermarket_trade.py
git commit -m "feat(fmp): intraday bars + aftermarket quote/trade fetchers (#87)

Add three of six Phase-0 fetchers targeting FMP /stable endpoints:
  - EquityIntradayHistorical  → /stable/historical-chart/{interval}
  - AftermarketQuote          → /stable/aftermarket-quote
  - AftermarketTrade          → /stable/aftermarket-trade

Tier-2-safe (no caching yet) — Phase 2 upgrades bars + aftermarket-quote
to tier-1 dedicated caching per PRD §5.2.

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.1 (fetchers 1-3 of 6)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: FMP fetchers 4-6 — batch quote short + market hours + technical indicators

**Files:**
- Create: `openbb_platform/providers/fmp/openbb_fmp/models/equity_quote_batch_short.py`
- Create: `openbb_platform/providers/fmp/openbb_fmp/models/exchange_market_hours.py`
- Create: `openbb_platform/providers/fmp/openbb_fmp/models/technical_indicator_intraday.py`

- [ ] **Step 1: Create `equity_quote_batch_short.py`** (fetcher #4)

```python
"""FMP Equity Quote Batch Short Model — /stable/batch-quote-short.

Deliberately uncached (tier-2 passthrough forever) — this endpoint IS the
"cheap and fast" poll primitive per PRD §5.1 rationale.
"""

# pylint: disable=unused-argument

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class FMPEquityQuoteBatchShortQueryParams(QueryParams):
    """FMP Batch Quote Short Query.

    Source: https://site.financialmodelingprep.com/developer/docs#batch-quote-short
    """

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    symbol: str = Field(description="Comma-separated symbols (batch endpoint).")


class FMPEquityQuoteBatchShortData(Data):
    """FMP Batch Quote Short row."""

    symbol: str = Field(description="Ticker symbol.")
    price: float | None = Field(default=None, description="Last trade price.")
    change: float | None = Field(default=None, description="Change vs prev close.")
    volume: int | None = Field(default=None, description="Session volume.")


class FMPEquityQuoteBatchShortFetcher(
    Fetcher[
        FMPEquityQuoteBatchShortQueryParams,
        list[FMPEquityQuoteBatchShortData],
    ]
):
    """FMP Batch Quote Short Fetcher (single call, N symbols)."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPEquityQuoteBatchShortQueryParams:
        return FMPEquityQuoteBatchShortQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityQuoteBatchShortQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        symbols = ",".join(s.strip() for s in query.symbol.split(",") if s.strip())
        url = (
            "https://financialmodelingprep.com/stable/batch-quote-short?"
            f"symbols={symbols}&apikey={api_key}"
        )
        data = await amake_request(
            url, response_callback=response_callback, **kwargs
        )
        if not data:
            raise EmptyDataError("No batch quotes returned from FMP.")
        return list(data)

    @staticmethod
    def transform_data(
        query: FMPEquityQuoteBatchShortQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEquityQuoteBatchShortData]:
        return [FMPEquityQuoteBatchShortData.model_validate(d) for d in data]
```

- [ ] **Step 2: Create `exchange_market_hours.py`** (fetcher #5)

```python
"""FMP Exchange Market Hours Model — /stable/all-exchange-market-hours."""

# pylint: disable=unused-argument

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class FMPExchangeMarketHoursQueryParams(QueryParams):
    """FMP All Exchange Market Hours Query (no parameters).

    Source: https://site.financialmodelingprep.com/developer/docs#all-exchange-market-hours
    """


class FMPExchangeMarketHoursData(Data):
    """One row per exchange × session-status snapshot."""

    exchange: str = Field(description="Exchange code (e.g. NASDAQ, NYSE).")
    name: str | None = Field(default=None, description="Exchange full name.")
    opening_hour: str | None = Field(default=None, description="Regular open (local).")
    closing_hour: str | None = Field(default=None, description="Regular close (local).")
    timezone: str | None = Field(default=None, description="Exchange timezone.")
    is_market_open: bool | None = Field(
        default=None, description="True if currently in regular-hours session."
    )


class FMPExchangeMarketHoursFetcher(
    Fetcher[
        FMPExchangeMarketHoursQueryParams,
        list[FMPExchangeMarketHoursData],
    ]
):
    """FMP All Exchange Market Hours Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPExchangeMarketHoursQueryParams:
        return FMPExchangeMarketHoursQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPExchangeMarketHoursQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        url = (
            "https://financialmodelingprep.com/stable/"
            f"all-exchange-market-hours?apikey={api_key}"
        )
        data = await amake_request(
            url, response_callback=response_callback, **kwargs
        )
        if not data:
            raise EmptyDataError("No exchange hours returned from FMP.")
        return list(data)

    @staticmethod
    def transform_data(
        query: FMPExchangeMarketHoursQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPExchangeMarketHoursData]:
        return [FMPExchangeMarketHoursData.model_validate(d) for d in data]
```

- [ ] **Step 3: Create `technical_indicator_intraday.py`** (fetcher #6)

```python
"""FMP Technical Indicator (Intraday) Model — /stable/technical-indicators/{indicator}."""

# pylint: disable=unused-argument

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

IndicatorName = Literal[
    "ADX", "RSI", "EMA", "SMA", "WMA", "DEMA", "TEMA", "WilliamsR", "StdDev"
]
Timeframe = Literal["1min", "5min", "15min", "30min", "1hour", "4hour", "1day"]


class FMPTechnicalIndicatorIntradayQueryParams(QueryParams):
    """FMP Technical Indicator (Intraday) Query.

    Source: https://site.financialmodelingprep.com/developer/docs#technical-indicators
    """

    symbol: str = Field(description="Ticker symbol.")
    indicator: IndicatorName = Field(description="Indicator name (FMP taxonomy).")
    period_length: int = Field(default=14, description="Lookback period.")
    timeframe: Timeframe = Field(default="5min", description="Bar timeframe.")


class FMPTechnicalIndicatorIntradayData(Data):
    """One (symbol, indicator, bar) point."""

    symbol: str = Field(description="Ticker symbol.")
    indicator: str = Field(description="Indicator name.")
    date: datetime = Field(description="Bar-start timestamp.")
    value: float | None = Field(
        default=None, description="Indicator value (None during warmup)."
    )
    period_length: int = Field(description="Lookback period used.")
    timeframe: str = Field(description="Bar timeframe.")


class FMPTechnicalIndicatorIntradayFetcher(
    Fetcher[
        FMPTechnicalIndicatorIntradayQueryParams,
        list[FMPTechnicalIndicatorIntradayData],
    ]
):
    """FMP Technical Indicator (Intraday) Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPTechnicalIndicatorIntradayQueryParams:
        return FMPTechnicalIndicatorIntradayQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPTechnicalIndicatorIntradayQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_fmp.utils.helpers import response_callback

        api_key = credentials.get("fmp_api_key") if credentials else ""
        url = (
            "https://financialmodelingprep.com/stable/technical-indicators/"
            f"{query.indicator}?symbol={query.symbol}"
            f"&periodLength={query.period_length}"
            f"&timeframe={query.timeframe}"
            f"&apikey={api_key}"
        )
        data = await amake_request(
            url, response_callback=response_callback, **kwargs
        )
        if not data:
            raise EmptyDataError("No indicator values returned from FMP.")
        # Enrich each row with query context so downstream models are self-describing.
        for row in data:
            row.setdefault("symbol", query.symbol)
            row.setdefault("indicator", query.indicator)
            row.setdefault("period_length", query.period_length)
            row.setdefault("timeframe", query.timeframe)
            # FMP returns the indicator under a key matching its name; normalize.
            if "value" not in row and query.indicator in row:
                row["value"] = row[query.indicator]
        return list(data)

    @staticmethod
    def transform_data(
        query: FMPTechnicalIndicatorIntradayQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPTechnicalIndicatorIntradayData]:
        return [FMPTechnicalIndicatorIntradayData.model_validate(d) for d in data]
```

- [ ] **Step 4: Verify all three modules import cleanly**

Run:
```bash
.venv_win\Scripts\python.exe -c "from openbb_fmp.models.equity_quote_batch_short import FMPEquityQuoteBatchShortFetcher; from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher; from openbb_fmp.models.technical_indicator_intraday import FMPTechnicalIndicatorIntradayFetcher; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 5: Commit fetchers 4-6**

```bash
git add openbb_platform/providers/fmp/openbb_fmp/models/equity_quote_batch_short.py openbb_platform/providers/fmp/openbb_fmp/models/exchange_market_hours.py openbb_platform/providers/fmp/openbb_fmp/models/technical_indicator_intraday.py
git commit -m "feat(fmp): batch quote short + market hours + intraday indicators (#87)

Add the final three of six Phase-0 fetchers:
  - EquityQuoteBatchShort       → /stable/batch-quote-short
  - ExchangeMarketHours         → /stable/all-exchange-market-hours
  - TechnicalIndicatorIntraday  → /stable/technical-indicators/{indicator}

All three are tier-2 passthrough forever per PRD §5.1 (batch-short IS the
cheap poll; indicators are rarely used; hours changes daily and gets a 24h
TTL wrapper in Phase 2 P2.2).

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.1 (fetchers 4-6 of 6)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Register the six fetchers in `openbb_fmp/__init__.py`

**Files:**
- Modify: `openbb_platform/providers/fmp/openbb_fmp/__init__.py`

- [ ] **Step 1: Add the six imports (alphabetized) after the existing imports**

Insert next to their alphabetical neighbours in the import block (keep the file's existing sort order):

```python
from openbb_fmp.models.aftermarket_quote import FMPAftermarketQuoteFetcher
from openbb_fmp.models.aftermarket_trade import FMPAftermarketTradeFetcher
from openbb_fmp.models.equity_intraday_historical import (
    FMPEquityIntradayHistoricalFetcher,
)
from openbb_fmp.models.equity_quote_batch_short import (
    FMPEquityQuoteBatchShortFetcher,
)
from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher
from openbb_fmp.models.technical_indicator_intraday import (
    FMPTechnicalIndicatorIntradayFetcher,
)
```

- [ ] **Step 2: Add six new entries to `fetcher_dict`** (keep alphabetized within the dict)

Insert each key next to its alphabetical neighbour (example placement shown; match the file's existing ordering):

```python
    "AftermarketQuote": FMPAftermarketQuoteFetcher,
    "AftermarketTrade": FMPAftermarketTradeFetcher,
    # ... existing entries ...
    "EquityIntradayHistorical": FMPEquityIntradayHistoricalFetcher,
    # ... existing entries ...
    "EquityQuoteBatchShort": FMPEquityQuoteBatchShortFetcher,
    # ... existing entries ...
    "ExchangeMarketHours": FMPExchangeMarketHoursFetcher,
    # ... existing entries ...
    "TechnicalIndicatorIntraday": FMPTechnicalIndicatorIntradayFetcher,
```

- [ ] **Step 3: Verify the provider still imports and the six keys appear**

Run:
```bash
.venv_win\Scripts\python.exe -c "from openbb_fmp import fmp_provider; got = set(fmp_provider.fetcher_dict) & {'AftermarketQuote','AftermarketTrade','EquityIntradayHistorical','EquityQuoteBatchShort','ExchangeMarketHours','TechnicalIndicatorIntraday'}; assert len(got) == 6, sorted(got); print('fmp registrations ok:', sorted(got))"
```

Expected: `fmp registrations ok: ['AftermarketQuote', 'AftermarketTrade', 'EquityIntradayHistorical', 'EquityQuoteBatchShort', 'ExchangeMarketHours', 'TechnicalIndicatorIntraday']`

- [ ] **Step 4: Re-run the parity test — one of two failing assertions should now flip green**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/tests/architecture/test_provider_parity.py -v`

Expected:
- `test_fmp_keys_subset_of_fmp_cached` — **FAIL** (fmp now has 6 keys fmp_cached does not)
- `test_prd_phase_0_fetchers_in_fmp` — **PASS**
- `test_prd_phase_0_fetchers_in_fmp_cached` — **FAIL**

This is the expected mid-state; Task 6 closes the parity gap.

- [ ] **Step 5: Commit the fmp registrations**

```bash
git add openbb_platform/providers/fmp/openbb_fmp/__init__.py
git commit -m "feat(fmp): register six Phase-0 intraday fetchers in provider (#87)

Register the six new fetchers in fmp_provider.fetcher_dict so they resolve
from obb.provider='fmp'. Parity test now fails in the fmp_cached direction
only — closed by the next commit.

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.1 (registration)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Register the six fetchers in `openbb_fmp_cached/__init__.py` (tier-2)

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py`

All six start as tier-2 passthrough via `create_fallback_fetcher_class` — Phase 2 promotes two of them to tier-1 with real caching per PRD §5.2.

- [ ] **Step 1: Add the six imports from `openbb_fmp.models.*`**

Add next to the existing `from openbb_fmp.models.*` block (keep alphabetized):

```python
from openbb_fmp.models.aftermarket_quote import FMPAftermarketQuoteFetcher
from openbb_fmp.models.aftermarket_trade import FMPAftermarketTradeFetcher
from openbb_fmp.models.equity_intraday_historical import (
    FMPEquityIntradayHistoricalFetcher,
)
from openbb_fmp.models.equity_quote_batch_short import (
    FMPEquityQuoteBatchShortFetcher,
)
from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher
from openbb_fmp.models.technical_indicator_intraday import (
    FMPTechnicalIndicatorIntradayFetcher,
)
```

- [ ] **Step 2: Extend `fetcher_mapping` inside `create_all_cached_fetchers()`**

Append six entries to the `fetcher_mapping` list (near the end, before `("GovernmentTrades", ...)` or after any other entry that keeps rough alphabetization):

```python
        # Phase-0 intraday fetchers (PRD 2026-07-06 §5.1)
        # All tier-2 passthrough initially; Phase 2 promotes bars + aftermarket
        # quote to tier-1 dedicated caching (P2.1) and market hours to a 24h
        # TTL wrapper (P2.2).
        ("AftermarketQuote", FMPAftermarketQuoteFetcher),
        ("AftermarketTrade", FMPAftermarketTradeFetcher),
        ("EquityIntradayHistorical", FMPEquityIntradayHistoricalFetcher),
        ("EquityQuoteBatchShort", FMPEquityQuoteBatchShortFetcher),
        ("ExchangeMarketHours", FMPExchangeMarketHoursFetcher),
        ("TechnicalIndicatorIntraday", FMPTechnicalIndicatorIntradayFetcher),
```

The existing loop wraps each with `create_cached_fetcher_class(...)` which in this checkout delegates to `create_fallback_fetcher_class` (see `models/base_cached.py`) — credential translation only, no caching, exactly the tier-2 posture we want for Phase 0.

- [ ] **Step 3: Verify the cached provider carries all six keys**

Run:
```bash
.venv_win\Scripts\python.exe -c "from openbb_fmp_cached import fmp_cached_provider; got = set(fmp_cached_provider.fetcher_dict) & {'AftermarketQuote','AftermarketTrade','EquityIntradayHistorical','EquityQuoteBatchShort','ExchangeMarketHours','TechnicalIndicatorIntraday'}; assert len(got) == 6, sorted(got); print('fmp_cached registrations ok:', sorted(got))"
```

Expected: `fmp_cached registrations ok: ['AftermarketQuote', 'AftermarketTrade', 'EquityIntradayHistorical', 'EquityQuoteBatchShort', 'ExchangeMarketHours', 'TechnicalIndicatorIntraday']`

- [ ] **Step 4: Parity test goes fully GREEN**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/tests/architecture/test_provider_parity.py -v`

Expected: `3 passed` — all three assertions green (subset + both PRD-fetcher checks).

- [ ] **Step 5: Commit the fmp_cached registrations**

```bash
git add openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py
git commit -m "feat(fmp_cached): register six Phase-0 intraday fetchers (tier-2) (#87)

Add the six new intraday fetchers to fmp_cached_provider via the existing
create_fallback_fetcher_class wrapper (credential translation only). All
six ship as tier-2 passthrough initially — PRD §5.1 matrix; Phase 2 (P2.1
+ P2.2) promotes bars, aftermarket-quote, and exchange-market-hours to
tier-1 dedicated / TTL caching.

Parity CI test (tests/architecture/test_provider_parity.py) now green:
  set(fmp) ⊂ set(fmp_cached)  AND  all six Phase-0 keys present in both.

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.2

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Absorb epic #91 — 3-tier fallback code disposition (P0.5)

**Goal:** Decide the fate of the 1088-LoC 3-tier `fmp_cached → fmp → cboe` fallback code from epic #91 (3-tier FMP/CBOE historical-data fallback). PRD §1.1 says the code is "currently orphaned" and gets "repurposed as intraday 3-tier". Phase 0's job is to *locate*, *inventory*, and *decide*: (a) port into `openbb_fmp_cached/models/base_cached.py` as a reusable adapter for later phases, or (b) drop with a note in this plan documenting why. No new logic ships in Phase 0; the deliverable is a one-file `dispositions/91-3tier-fallback.md` capturing the decision + audit trail.

**Files:**
- Create: `docs/superpowers/dispositions/91-3tier-fallback.md`

- [ ] **Step 1: Locate the epic #91 code**

Search for the fallback code (it may live on an unmerged branch, a stale PR, or an issue attachment):

```bash
gh issue view 91 --repo <owner>/OpenBBTradingView --json body,comments
git log --all --oneline --grep="3-tier\|fallback\|cboe fallback\|#91" | head -20
git branch -a | grep -iE "91|fallback|3tier"
```

Expected: one of the three surfaces something. If nothing surfaces, note that in the disposition doc.

- [ ] **Step 2: Inventory what was there**

For each source you find (branch, commit, PR, gist), record in a scratch buffer:
- Path(s) of the fallback module(s)
- LoC + top-level classes/functions
- Which providers it wires (`fmp_cached`, `fmp`, `cboe`)
- Test coverage that exists / doesn't
- Whether cboe is a hard dependency (it should NOT be for intraday — cboe is options-only per PRD NG4)

- [ ] **Step 3: Write the disposition decision**

Create `docs/superpowers/dispositions/91-3tier-fallback.md`:

```markdown
# Epic #91 (3-tier FMP/CBOE historical-data fallback) — Disposition

**Status:** [decided-port | decided-drop | inventory-only-pending]
**Date:** <YYYY-MM-DD>
**Decided by:** <you>
**Related:** Phase 0 task P0.5 of
`docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`

## Inventory (what was found)

| Source | Path | LoC | Top-level exports |
|---|---|---|---|
| <branch/PR/commit> | <path> | <n> | <ClassNames> |
| ... | ... | ... | ... |

**Test coverage found:** <files, or "none">
**cboe dependency posture:** <hard | opt-in | absent>

## Decision

**Chosen path:** <port to adapter | drop>

### Rationale
<3-6 sentences>

### If ported: destination + shape
- Target file: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/<name>.py`
- Consumer(s): Phase-2 `EquityIntradayHistorical` tier-1 upgrade (P2.1)
- Public API kept: `<method signatures>`
- Removed / changed: `<list>`

### If dropped: what replaces it
- Fallback surface substituted by: `create_fallback_fetcher_class` (tier-2 for now)
  + Phase-2 dedicated-caching pattern from `equity_historical.py`
- cboe options context still filed under NG7 follow-up if/when Analysis
  Phase-D2 lands (PRD §1.1).

## Follow-up

- [ ] Close epic #91 with a comment linking to this disposition file.
- [ ] If port chosen: file Phase-2 sub-issue "wire ported adapter into
      EquityIntradayHistorical tier-1 promotion".
```

- [ ] **Step 4: Commit the disposition**

```bash
git add docs/superpowers/dispositions/91-3tier-fallback.md
git commit -m "docs(phase-0): disposition for epic #91 3-tier fallback code (#87)

Records the inventory + port-vs-drop decision for the 1088-LoC 3-tier
fmp_cached → fmp → cboe fallback code referenced in epic #91. Phase 0
closes P0.5 by landing this decision doc so Phase 2's tier-1 upgrades
know what (if anything) to build on.

Refs: docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md
      Phase 0 task P0.5

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Final acceptance gate + status report

- [ ] **Step 1: Both CI guardrails green**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/tests/architecture -v`

Expected: `6 passed` — 3 purity + 3 parity assertions.

- [ ] **Step 2: Neither provider's existing test suite regressed**

Run:
```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp/tests -m "not integration" -q
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests -m "not integration" -q
```

Expected: both suites pass with the same counts as before Phase 0.

- [ ] **Step 3: `import openbb` still clean; both providers still importable**

Run:
```bash
.venv_win\Scripts\python.exe -c "from openbb import obb; from openbb_fmp import fmp_provider; from openbb_fmp_cached import fmp_cached_provider; print('fmp keys:', len(fmp_provider.fetcher_dict), '| fmp_cached keys:', len(fmp_cached_provider.fetcher_dict))"
```

Expected: `import OK`; both key counts increased by exactly 6 relative to the pre-Phase-0 baseline.

- [ ] **Step 4: No generated-package churn staged**

Run: `git status --porcelain openbb_platform/core/openbb/package/`

If any files appear, run `git restore openbb_platform/core/openbb/package/` before pushing.

- [ ] **Step 5: Report status (do NOT push without user confirmation)**

Summarize:
- Files created/modified (12 new files, 2 modified `__init__.py`, 1 disposition doc)
- Test evidence: `6 passed` architecture, `N passed` fmp, `M passed` fmp_cached
- Phase 0 acceptance: P0.1 ✓, P0.2 ✓, P0.3 ✓, P0.4 ✓, P0.5 ✓ (per disposition)
- Ask the user before `git push`, before opening a Phase 0 PR, and before starting Phase 1.

---

## Self-Review Notes

**Spec coverage (PRD §10 Phase 0):**
- P0.1 (file 6 fetchers in openbb_fmp, tier-2-safe first) → Tasks 3, 4, 5. ✓
- P0.2 (register 6 in openbb_fmp_cached, all tier-2 initially via `create_fallback_fetcher_class`) → Task 6. ✓
- P0.3 (CI parity test `set(fmp) ⊂ set(fmp_cached)`) → Task 2. ✓
- P0.4 (CI provider-purity grep test — before code lands) → Task 1. ✓
- P0.5 (absorb #91 3-tier fallback code disposition) → Task 7. ✓

**Order-of-operations rationale:**
- Task 1 (purity) lands **before** any extension code so Phase 1 devs cannot regress the invariant.
- Task 2 (parity) lands RED so Tasks 3-6 have a driving test. Tasks 5 and 6 flip the two failing parity assertions green in the right sequence (fmp first, then fmp_cached).
- Task 7 (disposition) is documentation-only in Phase 0 by design — the port itself, if chosen, is a Phase 2 sub-issue.

**Constraint alignment:**
- Every code path uses the `.venv_win` interpreter (per repo convention). ✓
- Every fetcher inherits `openbb_core.provider.abstract.fetcher.Fetcher[QP, list[Data]]`. ✓
- No `provider="fmp"` string introduced anywhere in this plan's code (extension code doesn't exist yet; provider registration doesn't count — it's the provider *impl*). ✓
- Every commit message ends with `Co-Authored-By: Claude <noreply@anthropic.com>` per CLAUDE.md. ✓
- The tier-2 wrapper used is `create_fallback_fetcher_class` (found in `base_cached.py` line 15); the plan's Task 6 goes through the existing `fetcher_mapping` loop which invokes `create_cached_fetcher_class` (deprecated shim that delegates to `create_fallback_fetcher_class` per lines 79-82) — no wrapper change needed in Phase 0.

**Deferred to later phases (explicitly not in Phase 0):**
- Tier-1 dedicated caching for `EquityIntradayHistorical` + `AftermarketQuote` → Phase 2, P2.1.
- `create_ttl_wrapper_class` for `ExchangeMarketHours` 24h TTL → Phase 2, P2.2.
- Broker-chokepoint CI test (`tests/architecture/test_broker_chokepoint.py`) → Phase 2 (arrives with `IntradaySession` + `PaperBroker` wiring; nothing to chokepoint yet).
- Extension package `openbb_platform/extensions/fmp_trading/` → Phase 1, P1.1.
- Article-adjacent `/api/v3/*` → `/stable/*` migration for gainers/losers/actives → PRD §1.3 follow-up issue (behavior identical today; not blocking).
