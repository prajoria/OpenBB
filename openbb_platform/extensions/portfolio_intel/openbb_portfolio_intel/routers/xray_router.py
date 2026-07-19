"""X-Ray look-through route (#541).

Recursively unwraps ETFs in an inline portfolio basket to underlying
single-security exposures + sector/country rollups + concentration
metrics (HHI / effective-N / top-K).

Composes:
- ``obb.etf.holdings(symbol, provider=<provider>)`` for the per-ETF
  holdings fetch (paths through the shipped ``fmp_cached`` multi-tier
  fetcher: FMP → SSGA issuer file → SEC N-PORT stub).
- ``openbb_portfolio_intel.analytics.xray.look_through`` + ``rollup_by``
  + ``herfindahl_hirschman`` + ``effective_n`` for the pure math.

Design: ``docs/superpowers/specs/2026-07-19-xray-route-design.md``.

Scope narrowed vs original PRD §11:

- **Inline basket only** — no saved ``portfolio_basket`` SQL table
  lookup (deferred, follow-up will add ``basket_id`` param).
- **No qty + price** — basket rows carry pre-normalized ``weight``
  fractions summing to ~1.0. Follow-up will add ``qty`` support once
  the paper-trading account model lands.
- **No shorts** — negative weights raise ``ValueError`` (same posture
  as What-If #904).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_portfolio_intel.analytics.xray import (
    DEFAULT_MAX_DEPTH,
    Holding,
    effective_n,
    herfindahl_hirschman,
    look_through as _xray_look_through,
    rollup_by,
)
from openbb_portfolio_intel.models import (
    BasketPosition,
    ConcentrationSummary,
    XRayLookThroughResult,
)

logger = logging.getLogger(__name__)

router = Router(
    prefix="/xray",
    description=(
        "Recursively unwrap an ETF-containing portfolio to underlying "
        "single-security exposures + sector/country rollups + concentration."
    ),
)


# ---------------------------------------------------------------------------
# Collaborator seams (patched in unit tests; lazy in production)
# ---------------------------------------------------------------------------


def _fetch_holdings(symbol: str, provider: str | None = None):
    """Fetch ETF holdings via ``obb.etf.holdings``.

    Seam: unit tests patch this to avoid importing ``obb`` (which triggers
    the full extension build) and to inject deterministic fixtures. In
    production this calls into the shipped ``fmp_cached`` multi-tier
    fetcher (FMP → issuer file → N-PORT stub).
    """
    from openbb import obb  # noqa: PLC0415 — lazy so `import openbb` stays light

    return obb.etf.holdings(symbol=symbol, provider=provider)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_basket(basket: list[BasketPosition]) -> None:
    """Enforce non-empty + all-non-negative-weights invariants."""
    if not basket:
        raise ValueError("basket must contain at least one position (got empty)")
    for pos in basket:
        if pos.weight < 0:
            raise ValueError(
                f"{pos.symbol}: negative weight ({pos.weight}) — short positions "
                "are not supported in this cut (follow-up planned)"
            )


def _extract_rows(response) -> list:
    """Unwrap ``.results`` if the response is an OBBject-like envelope."""
    return getattr(response, "results", response) or []


def _build_holdings_provider(
    unique_symbols: set[str],
    provider: str | None,
    unresolved: list[str],
    warnings: list[str],
) -> tuple[dict[str, list[Holding]], dict[str, Holding]]:
    """Populate the ``holdings_provider`` + ``attribute_provider`` maps.

    Iteratively expands: starts from basket-top symbols, then for every
    ETF whose holdings included a sub-symbol, re-queries that sub-symbol
    to see if it too is an ETF (fund-of-fund case). Bounded by
    ``DEFAULT_MAX_DEPTH`` to avoid pathological recursion.

    On any exception (provider outage, invalid ETF, etc.) the symbol is
    tagged ``unresolved`` with a warning and kept at face weight
    downstream. Symbols that return ``[]`` are treated as terminal
    single-securities (no error, no warning).
    """
    holdings_provider: dict[str, list[Holding]] = {}
    attribute_provider: dict[str, Holding] = {}
    seen: set[str] = set()

    frontier = set(unique_symbols)
    for _depth in range(DEFAULT_MAX_DEPTH):
        if not frontier:
            break
        next_frontier: set[str] = set()

        for sym in sorted(frontier):
            if sym in seen:
                continue
            seen.add(sym)

            try:
                rows = _extract_rows(_fetch_holdings(sym, provider=provider))
            except Exception as exc:  # noqa: BLE001
                logger.warning("xray: holdings fetch failed for %s: %s", sym, exc)
                unresolved.append(sym)
                warnings.append(
                    f"{sym}: holdings fetch raised ({type(exc).__name__}); "
                    "kept at face weight"
                )
                continue

            if not rows:
                # Terminal single-security — no ETF unwrap needed.
                continue

            sub_holdings: list[Holding] = []
            for row in rows:
                row_symbol = getattr(row, "symbol", None)
                row_weight = getattr(row, "weight", None)
                if not row_symbol or row_weight is None:
                    continue
                up = str(row_symbol).upper()
                sub_holdings.append(
                    Holding(
                        symbol=up,
                        weight=Decimal(str(row_weight)),
                        sector=getattr(row, "sector", None),
                        country=getattr(row, "country", None),
                    )
                )
                # First-write-wins for attribute lookup.
                if up not in attribute_provider:
                    attribute_provider[up] = Holding(
                        symbol=up,
                        weight=Decimal("1"),
                        sector=getattr(row, "sector", None),
                        country=getattr(row, "country", None),
                    )
                # Any sub-symbol we haven't fetched yet becomes a
                # frontier candidate — will be tested for ETF-ness on
                # the next depth loop.
                if up not in seen:
                    next_frontier.add(up)

            if sub_holdings:
                holdings_provider[sym] = sub_holdings

        frontier = next_frontier

    return holdings_provider, attribute_provider


def _compute_concentration(effective: dict[str, Decimal]) -> ConcentrationSummary:
    """Compute HHI + effective-N + top-K on the effective weight dict."""
    if not effective:
        return ConcentrationSummary(
            hhi=0.0, effective_n=0.0, top1=0.0, top5=0.0, top10=0.0
        )
    hhi = float(herfindahl_hirschman(effective))
    en = float(effective_n(Decimal(str(hhi)))) if hhi > 0 else 0.0
    sorted_w = sorted((float(w) for w in effective.values()), reverse=True)

    def _top(k: int) -> float:
        return float(sum(sorted_w[:k]))

    return ConcentrationSummary(
        hhi=hhi,
        effective_n=en,
        top1=_top(1),
        top5=_top(5),
        top10=_top(10),
    )


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Unwrap a 60/40 SPY-plus-AAPL basket to underlyings.",
            code=[
                "from decimal import Decimal",
                "positions = [",
                '    {"symbol": "SPY", "weight": Decimal("0.6")},',
                '    {"symbol": "AAPL", "weight": Decimal("0.4")},',
                "]",
                'result = obb.portfolio_intel.xray.look_through(basket=positions, provider="fmp_cached").results',
                "print(sorted(result.effective.items(), key=lambda kv: -kv[1])[:5])",
            ],
        ),
    ],
)
def look_through(
    basket: list[dict],
    provider: str | None = None,
) -> OBBject:
    """Recursively unwrap ETFs in ``basket`` to underlying single-security exposures.

    Fetches ETF holdings via ``obb.etf.holdings(symbol, provider=<provider>)``
    for every symbol in the basket whose holdings are queryable, then calls
    :func:`openbb_portfolio_intel.analytics.xray.look_through` to unwrap.
    Non-ETFs (single securities) pass through unchanged.

    ``basket`` is a list of ``{"symbol": str, "weight": float | Decimal}``
    dicts. Weights are fractions of 1.0 (not percentages) and must sum to
    ~1.0 within ``xray.DEFAULT_WEIGHT_TOLERANCE``. This dict shape is
    intentional: OpenBB's static-package generator does not import
    extension-local Pydantic models by name, so a typed
    ``list[BasketPosition]`` surface would break the runtime dispatcher
    (verified live during #541 phase-6 verify — model class name leaked
    into generated code unimported).

    Returns
    -------
    OBBject[:class:`~openbb_portfolio_intel.models.XRayLookThroughResult`]
        Exposure per underlying, sector + country rollups, concentration
        (HHI + effective-N + top-K), plus depth/unresolved/warnings.
        Return type is ``OBBject`` (unparameterized) at the signature level
        for the same generator-compatibility reason as the input surface;
        the actual ``.results`` value is always an ``XRayLookThroughResult``.

    Raises
    ------
    ValueError
        - If ``basket`` is empty.
        - If any position weight is negative (shorts not supported this cut).
        - If ``basket`` weights don't sum to ~1.0 (propagated from
          :func:`xray.look_through`).
    """
    positions = [
        BasketPosition(symbol=str(r["symbol"]), weight=Decimal(str(r["weight"])))
        for r in basket
    ]
    _validate_basket(positions)

    unresolved: list[str] = []
    warnings: list[str] = []

    unique = {p.symbol.upper() for p in positions}
    holdings_provider, attribute_provider = _build_holdings_provider(
        unique, provider, unresolved, warnings
    )

    # Convert basket to xray Holdings (sum-to-1 validation happens in look_through).
    portfolio = [Holding(symbol=p.symbol.upper(), weight=p.weight) for p in positions]

    lt_result = _xray_look_through(
        portfolio, holdings_provider, max_depth=DEFAULT_MAX_DEPTH
    )

    # Merge unresolved from xray (unknown ETF returning empty list from provider)
    # into our route-level unresolved. Note xray's "unresolved" is ETFs whose
    # holdings_provider entry was empty; ours is symbols whose fetch raised.
    for u in lt_result.unresolved:
        if u not in unresolved:
            unresolved.append(u)

    # Coerce effective weights to float for the response.
    effective_float: dict[str, float] = {
        s: float(w) for s, w in lt_result.effective.items()
    }
    effective_dec: dict[str, Decimal] = dict(lt_result.effective)

    # Sector + country rollups.
    sector_rolled = rollup_by(effective_dec, attribute_provider, "sector")
    country_rolled = rollup_by(effective_dec, attribute_provider, "country")

    unknown_count = float(sector_rolled.get("(unknown)", Decimal("0")))
    if unknown_count > 0:
        warnings.append(
            f"{sum(1 for k in effective_dec if k not in attribute_provider)} "
            f"symbol(s) had no sector/country attribute (rolled up as '(unknown)')"
        )

    concentration = _compute_concentration(effective_dec)

    result = XRayLookThroughResult(
        effective=effective_float,
        sector_rollup={k: float(v) for k, v in sector_rolled.items()},
        country_rollup={k: float(v) for k, v in country_rolled.items()},
        concentration=concentration,
        unresolved=unresolved,
        depth_reached=lt_result.depth_reached,
        warnings=warnings,
    )
    return OBBject(results=result)
