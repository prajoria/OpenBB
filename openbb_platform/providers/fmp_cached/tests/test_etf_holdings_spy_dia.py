"""Tests for #512 — SPY + DIA added to ISSUER_REGISTRY + recorded-fixture E2E.

Complements `test_etf_holdings_issuer.py` (synthetic fixtures) with:
- Recorded LIVE SSGA workbooks for SPY, DIA, XLK (~50KB each, dated 2026-07-19)
- Coverage assertion: portfolio_basket ETF universe fully addressable

Fixtures are byte-exact recordings under `tests/fixtures/etf_holdings/ssga/`.
Refresh cadence: manual, on schema drift — this suite's job is to fail loud
when SSGA changes their column layout, not to auto-refresh from live.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from openbb_fmp_cached.models.etf_holdings_issuer import (
    ISSUER_REGISTRY,
    _parse_ssga_xlsx,
    fetch_issuer_holdings,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "etf_holdings" / "ssga"

# ETFs the portfolio_basket demand set covers. When this list widens, the
# coverage test surfaces which are unregistered — no silent gaps.
PORTFOLIO_BASKET_ETFS: tuple[str, ...] = (
    # Sector SPDRs (11) — shipped in prior work
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    # Broad-market / index (this PR: SPY + DIA; others = follow-ups)
    "SPY",
    "DIA",
)

# Not yet in ISSUER_REGISTRY as of this PR; follow-ups per issuer.
NOT_YET_REGISTERED: tuple[str, ...] = (
    "QQQ",  # Invesco  — follow-up
    "IWM",  # BlackRock/iShares — follow-up
    "IVV",  # BlackRock/iShares — follow-up
    "VTI",  # Vanguard — follow-up
    "VOO",  # Vanguard — follow-up
    "ACWI",  # BlackRock/iShares — follow-up
    "EFA",  # BlackRock/iShares — follow-up
    "EEM",  # BlackRock/iShares — follow-up
)


# ---------------------------------------------------------------------------
# Registry membership (SPY + DIA — this PR's shipped additions)
# ---------------------------------------------------------------------------


def test_spy_registered_as_ssga() -> None:
    """SPY must be in ISSUER_REGISTRY under the SSGA parser (SPDR trust)."""
    assert "SPY" in ISSUER_REGISTRY
    spec = ISSUER_REGISTRY["SPY"]
    assert spec.issuer_id == "issuer_ssga"
    assert "spy" in spec.url.lower()


def test_dia_registered_as_ssga() -> None:
    """DIA must be in ISSUER_REGISTRY under the SSGA parser (SPDR trust)."""
    assert "DIA" in ISSUER_REGISTRY
    spec = ISSUER_REGISTRY["DIA"]
    assert spec.issuer_id == "issuer_ssga"
    assert "dia" in spec.url.lower()


# ---------------------------------------------------------------------------
# Recorded-fixture parse — production parser against real workbook bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ticker, min_rows",
    [
        ("spy", 400),  # S&P 500 → ~500 holdings; tolerate SSGA rebalance
        ("dia", 25),  # DJIA has 30 holdings; leave slack
        ("xlk", 50),  # sector SPDR; slack for reshuffle
    ],
)
def test_ssga_recorded_fixture_parses_to_expected_shape(
    ticker: str, min_rows: int
) -> None:
    """The prod SSGA parser handles real-world workbooks for SPY/DIA/XLK.

    Discriminating vs synthetic fixtures: exercises the real cell types,
    metadata-row placements, cash-row skip logic that live workbooks carry.
    """
    fixture = FIXTURES_DIR / f"{ticker}_ssga.xlsx"
    assert fixture.exists(), f"missing recorded fixture: {fixture}"
    content = fixture.read_bytes()
    rows = _parse_ssga_xlsx(content, ticker=ticker.upper())
    assert len(rows) >= min_rows, (
        f"{ticker.upper()} recorded fixture parsed to {len(rows)} rows "
        f"(expected >= {min_rows}); SSGA layout may have shifted — "
        "re-record fixture and update this bound."
    )
    # Every row must carry the fields the router+xray consume
    for r in rows:
        assert r["symbol"], f"row missing symbol: {r}"
        assert r["name"], f"row missing name: {r}"
        assert r["weight"] is not None, f"row missing weight: {r}"
        assert r["data_source"] == "issuer_ssga"


def test_spy_weights_sum_close_to_one_hundred_percent() -> None:
    """SSGA parser emits **percentages** (14.79 = 14.79%) — sums to ~100.

    Rationale: the FMPEtfHoldingsData validator runs a `/100`
    normalization in `mode='before'` at model construction, converting
    percent → fraction. The issuer parser must emit percentages so that
    single-normalize produces correct fractions end-to-end. Emitting
    fractions here would cause a double-divide (verified live for #512
    — SPY.total_weight came out at 0.01 instead of 1.0).

    Discriminating vs the R7.11 reverse-verify: reverting the parser to
    emit fractions makes this assertion fail (sum ≈ 1.0 not 100.0), and
    the separate E2E integration test fails simultaneously with
    sum(weight)=0.01.
    """
    content = (FIXTURES_DIR / "spy_ssga.xlsx").read_bytes()
    rows = _parse_ssga_xlsx(content, ticker="SPY")
    total = sum(r["weight"] for r in rows)
    assert 98.0 <= total <= 102.0, (
        f"SPY weights sum to {total:.4f}, expected ~100.0 (percentages) — "
        "SSGA layout drift OR parser normalization changed"
    )


# ---------------------------------------------------------------------------
# fetch_issuer_holdings — end-to-end with mocked http, using recorded bytes
# ---------------------------------------------------------------------------


def test_fetch_issuer_holdings_spy_end_to_end_with_recorded_bytes() -> None:
    """Full issuer-tier round-trip: URL lookup → HTTP → parser → dict rows."""
    content = (FIXTURES_DIR / "spy_ssga.xlsx").read_bytes()
    mock_http = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = content
    mock_response.raise_for_status.return_value = None
    mock_http.get.return_value = mock_response

    rows = fetch_issuer_holdings("SPY", http=mock_http)

    assert len(rows) > 400
    # URL was formatted from the registry spec
    called_url = mock_http.get.call_args[0][0]
    assert "holdings-daily-us-en-spy.xlsx" in called_url


def test_fetch_issuer_holdings_dia_end_to_end_with_recorded_bytes() -> None:
    """Same shape for DIA — smaller universe, same parser."""
    content = (FIXTURES_DIR / "dia_ssga.xlsx").read_bytes()
    mock_http = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = content
    mock_response.raise_for_status.return_value = None
    mock_http.get.return_value = mock_response

    rows = fetch_issuer_holdings("DIA", http=mock_http)

    assert len(rows) >= 25
    called_url = mock_http.get.call_args[0][0]
    assert "holdings-daily-us-en-dia.xlsx" in called_url


# ---------------------------------------------------------------------------
# Portfolio-basket coverage — must-cover set is either registered or xfail'd
# ---------------------------------------------------------------------------


def test_portfolio_basket_registered_etfs_have_ssga_spec() -> None:
    """Every ticker in the shipped subset must be in ISSUER_REGISTRY."""
    for t in PORTFOLIO_BASKET_ETFS:
        assert t in ISSUER_REGISTRY, (
            f"{t} in PORTFOLIO_BASKET_ETFS but missing from ISSUER_REGISTRY — "
            "add via a new IssuerSpec (and record its fixture) before merging"
        )


def test_not_yet_registered_universe_is_documented() -> None:
    """The deferred-issuer set is explicit; each ticker maps to a follow-up.

    This is a *documentation* test — if someone deletes NOT_YET_REGISTERED
    or removes a ticker, this fails so they can't silently expand scope
    without addressing the parser gap.
    """
    for t in NOT_YET_REGISTERED:
        assert t not in ISSUER_REGISTRY, (
            f"{t} was moved into ISSUER_REGISTRY — remove it from "
            "NOT_YET_REGISTERED (and close the corresponding follow-up issue)"
        )
    assert len(NOT_YET_REGISTERED) >= 5, (
        "NOT_YET_REGISTERED shrank — did you land follow-up parsers? "
        "Update the coverage test and this assertion."
    )


# ---------------------------------------------------------------------------
# End-to-end via obb.etf.holdings — the ACTUAL consumer path.
# ---------------------------------------------------------------------------


def test_obb_etf_holdings_spy_e2e_via_mocked_issuer_http() -> None:
    """End-to-end acid test at the CACHED-FETCHER level.

    Discriminates a whole class of "parser emits X, validator wants Y"
    silent-normalization bugs. Discovered live for #512 that the
    previous parser output produced total_weight = 0.01 instead of 1.0
    because SSGA-percent flowed through FMP's normalize_percent
    validator and got divided by 100 twice.

    We exercise ``FMPCachedEtfHoldingsFetcher.fetch_data`` directly
    (not the whole ``obb`` router) to avoid needing to route the whole
    OpenBBError-wrapping machinery around the mocked FMP failure.
    """
    from unittest.mock import MagicMock, patch

    from openbb_fmp.models.etf_holdings import FMPEtfHoldingsData

    content = (FIXTURES_DIR / "spy_ssga.xlsx").read_bytes()

    # Patch requests at issuer-tier module scope, skip FMP tier, and skip
    # cache-read so we go live through the tier chain to the issuer parser.
    # ALSO patch init_database + _store_etf_holdings so the test never
    # touches a real MySQL instance (would pollute the CI cache and
    # cross-contaminate other tests).
    with (
        patch("openbb_fmp_cached.models.etf_holdings_issuer.requests") as mock_requests,
        patch(
            "openbb_fmp_cached.models.etf_holdings._try_fmp",
            return_value=[],
        ),
        patch(
            "openbb_fmp_cached.models.etf_holdings._get_cached_etf_holdings",
            return_value=[],
        ),
        patch("openbb_fmp_cached.models.etf_holdings.init_database"),
        patch("openbb_fmp_cached.models.etf_holdings._store_etf_holdings"),
    ):
        response = MagicMock()
        response.status_code = 200
        response.content = content
        response.raise_for_status.return_value = None
        mock_requests.get.return_value = response

        # Directly invoke the cached fetcher's extract_data path.
        import asyncio

        from openbb_fmp_cached.models.etf_holdings import (
            FMPCachedEtfHoldingsFetcher,
        )

        query = FMPCachedEtfHoldingsFetcher.transform_query({"symbol": "SPY"})
        raw_rows = asyncio.run(
            FMPCachedEtfHoldingsFetcher.aextract_data(
                query=query,
                credentials={"fmp_api_key": "test-key"},
            )
        )

    assert len(raw_rows) > 400, f"expected >400 SPY rows, got {len(raw_rows)}"

    # Round-trip through the model validator to exercise the /100 normalize.
    models = [FMPEtfHoldingsData.model_validate(r) for r in raw_rows]
    weights = [m.weight for m in models if m.weight is not None]
    total = sum(weights)
    assert 0.98 <= total <= 1.02, (
        f"SPY total post-model weight is {total:.6f}, expected ~1.0. "
        "Likely a double-divide between issuer-parser format and "
        "FMPEtfHoldingsData.normalize_percent validator."
    )


# ---------------------------------------------------------------------------
# #512 fail-safe: stale pre-fix cache rows must be dropped on read
# ---------------------------------------------------------------------------


def test_cache_read_drops_suspicious_partial_sum_rows() -> None:
    """Pre-#512 rows (fraction-shaped weights summing to ~57 for SPY, ~17 for
    XLK, ~2.5 for DIA) must be treated as stale so the tier chain re-runs.

    The 2-50 sum window catches the "mixed-normalize" mode where the OLD
    parser output percentages for large holdings but fractions for small
    ones. A correctly-shipped payload sums to either ~100 (percent form)
    or ~1 (already normalized). Anything in (2, 50) is a bug signature.
    """
    from unittest.mock import patch

    from openbb_fmp_cached.models.etf_holdings import _get_cached_etf_holdings

    # 3 rows summing to ~10 — the failure mode we're guarding against
    suspicious = [
        {"symbol": "AAA", "weight": 5.0},
        {"symbol": "BBB", "weight": 3.0},
        {"symbol": "CCC", "weight": 2.0},
    ]
    fake_db_rows = [{"data_json": r} for r in suspicious]

    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query",
        return_value=fake_db_rows,
    ):
        loaded = _get_cached_etf_holdings("SPY")
    assert (
        loaded == []
    ), f"expected empty (drop suspicious pre-#512 rows); got {len(loaded)} rows"


def test_cache_read_accepts_valid_percent_form_rows() -> None:
    """A well-formed percent-form payload (sums to ~100) is served intact."""
    from unittest.mock import patch

    from openbb_fmp_cached.models.etf_holdings import _get_cached_etf_holdings

    valid_percent = [
        {"symbol": "AAA", "weight": 40.0},
        {"symbol": "BBB", "weight": 35.0},
        {"symbol": "CCC", "weight": 25.0},
    ]
    fake_db_rows = [{"data_json": r} for r in valid_percent]

    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query",
        return_value=fake_db_rows,
    ):
        loaded = _get_cached_etf_holdings("SPY")
    assert len(loaded) == 3


def test_cache_read_accepts_valid_fraction_form_rows() -> None:
    """A well-formed fraction-form payload (sums to ~1) is also served intact.

    (Some pre-existing FMP paths may have stored fractions directly.)
    """
    from unittest.mock import patch

    from openbb_fmp_cached.models.etf_holdings import _get_cached_etf_holdings

    valid_fraction = [
        {"symbol": "AAA", "weight": 0.40},
        {"symbol": "BBB", "weight": 0.35},
        {"symbol": "CCC", "weight": 0.25},
    ]
    fake_db_rows = [{"data_json": r} for r in valid_fraction]

    with patch(
        "openbb_fmp_cached.models.etf_holdings.execute_query",
        return_value=fake_db_rows,
    ):
        loaded = _get_cached_etf_holdings("SPY")
    assert len(loaded) == 3
