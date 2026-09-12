"""X-Ray look-through and rollup analytics for portfolio_intel.

Recursive holdings unwrap ("look-through") turns a portfolio of ETFs
into effective single-security exposures, then rolls those exposures
up along multiple dimensions (sector, country, market-cap bucket,
overlap counts). Herfindahl-Hirschman Index (HHI) computed on the
rolled exposures gives a single-number concentration metric.

Design notes:
- All I/O deliberately absent. This module operates on plain
  in-memory dicts/dataframes so unit tests are deterministic and the
  real fmp_cached provider integration (see #518 EtfHoldings /
  EtfSectorWeightings) can wire in independently.
- Recursion depth-capped (default 5) so a pathological
  fund-of-fund-of-fund can't stack-overflow.
- Exposures are float weights that sum to 1.0 within a
  configurable tolerance; drift outside tolerance triggers a
  ValueError so silent errors don't propagate.

Issues shipped by this module:
- #526  X-Ray look-through algorithm (recursive unwrap)
- #535  X-Ray rollups (sector / country / mcap / overlap)
- #536  Concentration + HHI endpoint
"""

# pylint: disable=too-few-public-methods

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal

# Fund-of-fund recursion safety cap. Real ETFs don't nest this deep; if
# we ever see one, something is wrong (or someone modeled cash as a
# fund-of-cash).
DEFAULT_MAX_DEPTH = 5

# Allowed drift of position-weight sum from 1.0 before we raise. Real
# holdings tables have rounding; 1bp tolerance is generous but bounded.
DEFAULT_WEIGHT_TOLERANCE = Decimal("0.0001")

# Provider holdings commonly omit a small cash residual or carry rounded
# percentages. Accept at most 2% drift, matching the provider contract,
# then normalize before composition.
DEFAULT_UNDERLYING_WEIGHT_TOLERANCE = Decimal("0.02")


@dataclass(frozen=True)
class Holding:
    """One line in a portfolio: a symbol with a weight (fraction of total)."""

    symbol: str
    weight: Decimal
    sector: str | None = None
    country: str | None = None
    mcap_bucket: str | None = None  # e.g. "large", "mid", "small"


@dataclass
class LookThroughResult:
    """Output of the recursive unwrap.

    Attributes
    ----------
    effective : dict[str, Decimal]
        Underlying single-security exposures. Values sum to 1.0 within
        tolerance.
    unresolved : list[str]
        Symbols we couldn't unwrap (missing holdings data). Their
        weight lives in `effective` at face value.
    depth_reached : int
        Deepest recursion level hit (0 = no unwrap needed).
    """

    effective: dict[str, Decimal] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    depth_reached: int = 0


def look_through(
    portfolio: list[Holding],
    holdings_provider: dict[str, list[Holding]],
    max_depth: int = DEFAULT_MAX_DEPTH,
    weight_tolerance: Decimal = DEFAULT_WEIGHT_TOLERANCE,
) -> LookThroughResult:
    """Recursively unwrap `portfolio` using `holdings_provider`.

    Parameters
    ----------
    portfolio : list[Holding]
        Top-level positions. Weights must sum to 1.0 within tolerance.
    holdings_provider : dict[str, list[Holding]]
        Mapping ETF/fund symbol → its underlying holdings (each with
        weights that sum to 1.0). Symbols missing from this dict are
        treated as terminal (single-security).
    max_depth : int
        Recursion safety cap.
    weight_tolerance : Decimal
        Allowed drift of the top-level weight sum from 1.0.

    Returns
    -------
    LookThroughResult

    Raises
    ------
    ValueError
        If portfolio weights don't sum to 1.0 within tolerance.
    """
    _validate_weights(portfolio, weight_tolerance)

    effective: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    normalized_provider: dict[str, list[Holding]] = {}
    unresolved: list[str] = []
    depth_reached = 0

    def _unwrap(h: Holding, parent_weight: Decimal, depth: int) -> None:
        nonlocal depth_reached
        depth_reached = max(depth_reached, depth)
        effective_weight = parent_weight * h.weight

        # Terminal cases in priority order:
        # 1. Depth cap reached — stop and treat h as a terminal leaf.
        # 2. Symbol not in provider — h is a real single-security holding.
        # 3. Symbol in provider but empty list — h is a known fund whose
        #    underlying data we don't have; note in `unresolved` and keep
        #    at face value.
        # 4. Otherwise recurse.
        if depth >= max_depth:
            effective[h.symbol] += effective_weight
            return
        if h.symbol not in holdings_provider:
            effective[h.symbol] += effective_weight
            return
        underlying = holdings_provider[h.symbol]
        if not underlying:
            unresolved.append(h.symbol)
            effective[h.symbol] += effective_weight
            return

        normalized = normalized_provider.get(h.symbol)
        if normalized is None:
            normalized = _normalize_underlying_weights(h.symbol, underlying)
            normalized_provider[h.symbol] = normalized

        # Recurse.
        for child in normalized:
            _unwrap(child, effective_weight, depth + 1)

    for holding in portfolio:
        _unwrap(holding, Decimal("1"), 0)

    return LookThroughResult(
        effective=dict(effective),
        unresolved=unresolved,
        depth_reached=depth_reached,
    )


def _validate_weights(portfolio: list[Holding], tolerance: Decimal) -> None:
    """Raise if the sum of portfolio weights drifts more than `tolerance` from 1.0."""
    total = sum((h.weight for h in portfolio), Decimal("0"))
    if abs(total - Decimal("1")) > tolerance:
        raise ValueError(
            f"portfolio weights must sum to 1.0 (±{tolerance}); got {total}. "
            "Normalize inputs before calling look_through()."
        )


def _normalize_underlying_weights(
    parent_symbol: str,
    holdings: list[Holding],
    tolerance: Decimal = DEFAULT_UNDERLYING_WEIGHT_TOLERANCE,
) -> list[Holding]:
    """Validate and normalize one non-empty provider holdings vector."""
    if any(not holding.weight.is_finite() or holding.weight < 0 for holding in holdings):
        raise ValueError(
            f"{parent_symbol}: holdings weights must be finite and non-negative"
        )

    total = sum((holding.weight for holding in holdings), Decimal("0"))
    if total <= 0 or abs(total - Decimal("1")) > tolerance:
        raise ValueError(
            f"{parent_symbol}: holdings weights must sum to 1.0 "
            f"(±{tolerance}); got {total}"
        )

    if total == Decimal("1"):
        return holdings
    return [replace(holding, weight=holding.weight / total) for holding in holdings]


# ---------------------------------------------------------------------------
# Rollups (#535)
# ---------------------------------------------------------------------------


def rollup_by(
    effective: dict[str, Decimal],
    attribute_provider: dict[str, Holding],
    attribute: str,
) -> dict[str, Decimal]:
    """Sum exposures grouped by an attribute of the underlying security.

    Parameters
    ----------
    effective : dict[str, Decimal]
        Output of `look_through()`.effective — symbol → weight.
    attribute_provider : dict[str, Holding]
        Mapping symbol → Holding-like carrying the attribute we group by
        (sector / country / mcap_bucket). Symbols missing here roll up
        into the "(unknown)" bucket.
    attribute : str
        Name of the attribute on Holding to group by ("sector",
        "country", "mcap_bucket").

    Returns
    -------
    dict[str, Decimal]
        Attribute value → summed weight.
    """
    rolled: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for symbol, weight in effective.items():
        h = attribute_provider.get(symbol)
        key = getattr(h, attribute, None) if h is not None else None
        rolled[key or "(unknown)"] += weight
    return dict(rolled)


def overlap_count(portfolios: list[dict[str, Decimal]]) -> dict[str, int]:
    """Count how many input portfolios each symbol appears in.

    Useful for "which of my ETFs overlap on which underlying stocks?"
    (a common look-through question).

    Parameters
    ----------
    portfolios : list[dict[str, Decimal]]
        Each dict is a portfolio's effective exposures.

    Returns
    -------
    dict[str, int]
        Symbol → count of portfolios that contain it.
    """
    counts: dict[str, int] = defaultdict(int)
    for portfolio in portfolios:
        for symbol in portfolio:
            counts[symbol] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Concentration / HHI (#536)
# ---------------------------------------------------------------------------


def herfindahl_hirschman(
    exposures: dict[str, Decimal],
    gross: bool = False,
) -> Decimal:
    """Compute HHI — the sum of squared weights.

    Interpretation:
      * 1.0        → fully concentrated (all in one holding)
      * 1/N        → perfectly diversified across N equal holdings
      * < 0.15     → generally "not concentrated"
      * > 0.25     → generally "highly concentrated"

    Reference: standard antitrust / portfolio-concentration formula.
    HHI is on the [0, 1] scale here (not the 0-10000 scale used by
    US antitrust for market shares in percent).

    Parameters
    ----------
    exposures : dict[str, Decimal]
        Symbol → weight. On a long-only book these are signed and
        already sum to ~1.0; the caller is responsible for normalization.
    gross : bool, default False
        If True, compute HHI on **gross weights** — each weight is
        first normalized by ``Σ|w_j|`` before squaring. Use this on
        signed books where a long+short pair should count as *two*
        concentrated positions rather than netting to zero (#904).

        The default ``gross=False`` preserves the initial-ship
        behavior — HHI is computed on the raw weights as-supplied.
        For long-only books, ``gross=False`` and ``gross=True``
        produce identical output because ``|w_i| == w_i``.
    """
    if gross:
        total_abs = sum((abs(w) for w in exposures.values()), Decimal("0"))
        if total_abs == 0:
            return Decimal("0")
        return sum(
            ((abs(w) / total_abs) * (abs(w) / total_abs) for w in exposures.values()),
            Decimal("0"),
        )
    return sum((w * w for w in exposures.values()), Decimal("0"))


def effective_n(hhi: Decimal) -> Decimal:
    """Effective number of holdings implied by HHI (Reciprocal HHI).

    A portfolio with HHI = 0.05 has effective-N = 20 — behaves like 20
    equally-weighted holdings even if the raw count is 100.
    """
    if hhi <= 0:
        raise ValueError("HHI must be positive to compute effective-N")
    return Decimal("1") / hhi
