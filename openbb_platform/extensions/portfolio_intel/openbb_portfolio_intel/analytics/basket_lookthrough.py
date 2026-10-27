"""Basket look-through, sector roll-up and concentration (#2313).

The math behind the portfolio notebook series' x-ray chapter
(``notebooks/portfolio/03-basket-xray-and-risk.ipynb`` §3-§8), lifted out
of the notebook so the MCP story adapters and the notebook compute the
same numbers. Pure functions: data arrives through injected callables
(``holdings_for``, ``sector_for_name``, ``sector_for_symbol``), so nothing
here touches the network or the filesystem.

Weights are plain fractions (floats), matching the notebook. The Decimal
engine in :mod:`openbb_portfolio_intel.analytics.xray` serves the
``/xray/look_through`` route and is unrelated.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

HoldingsFor = Callable[[str], list[dict]]
SectorFor = Callable[[str], "str | None"]

FIXED_INCOME_CATEGORIES = frozenset(
    {
        "DBT",
        "ABS-APCP",
        "ABS-CBDO",
        "ABS-MBS",
        "ABS-O",
        "ABS-CDO",
        "ABS-CMBS",
        "ABS-RMBS",
        "LOAN",
    }
)
_CATEGORY_BUCKETS = {
    "STIV": "Short-Term / Cash",
    "RE": "Real Estate (direct)",
    "COMM": "Commodity",
}
_EPS = 1e-15
_CORP_SUFFIXES = (
    ", Inc.", ", Inc", " Inc.", " Inc", " Corp.", " Corp", " Corporation",
    " Co.", " Co", " Ltd.", " Ltd", " PLC", " plc", " LLC", " N.V.", " NV",
    " S.A.", " SA", " AG", " AB", " SE", " KGaA",
)  # fmt: skip


class NportUnavailable(LookupError):
    """Symbol is not an SEC N-PORT filer.

    For example a commodity grantor trust, a non-'40-Act fund, an ADR or
    foreign listing, or a fund not yet in the SEC fund map.
    """


def strip_corp_suffix(name: str) -> str:
    """Drop one trailing corporate suffix, for a second issuer-name search."""
    for suffix in _CORP_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def _symbol(position: Mapping[str, Any]) -> str:
    return position.get("symbol") or position.get("ticker")  # type: ignore[return-value]


def _weight(row: Mapping[str, Any]) -> float:
    return float(row.get("weight") or 0.0)


def category_bucket(asset_category: str | None) -> str | None:
    """Bucket an N-PORT ``asset_category`` that needs no sector lookup."""
    if asset_category in FIXED_INCOME_CATEGORIES:
        return "Fixed Income"
    return _CATEGORY_BUCKETS.get(asset_category or "")


@dataclass(frozen=True)
class EffectivePositions:
    """A basket flattened through its funds' N-PORT holdings."""

    effective: dict[str, float]
    non_nport: list[str]
    opaque: list[tuple[str, str]]


def effective_positions(
    basket: Iterable[Mapping[str, Any]],
    holdings_for: HoldingsFor,
    *,
    equity_etfs: set[str],
    bond_etfs: set[str],
    commodity_trusts: set[str],
    top_n_per_etf: int = 100,
) -> EffectivePositions:
    """Flatten a basket into effective positions.

    Equity funds expand to their top ``top_n_per_etf`` issuers (keyed by
    issuer name) plus one ``TAIL_<ETF>`` row; bond funds collapse to one
    ``BOND_<ETF>`` row; commodity trusts and funds whose ``holdings_for``
    raises :class:`NportUnavailable` stay opaque at face weight. Anything
    else is a single name and passes through.
    """
    positions = list(basket)
    effective: dict[str, float] = {}
    non_nport: list[str] = []
    opaque: list[tuple[str, str]] = []

    def _add(key: str, weight: float) -> None:
        effective[key] = effective.get(key, 0.0) + weight

    for position in positions:
        symbol = _symbol(position)
        weight = _weight(position)
        if symbol in commodity_trusts:
            _add(symbol, weight)
            opaque.append((symbol, "commodity trust — no look-through"))
            continue
        if symbol not in equity_etfs and symbol not in bond_etfs:
            _add(symbol, weight)
            continue
        try:
            rows = holdings_for(symbol)
        except NportUnavailable as exc:
            non_nport.append(symbol)
            _add(symbol, weight)
            opaque.append((symbol, str(exc)))
            continue

        ranked = sorted(rows, key=lambda r: -_weight(r))
        for row in ranked[:top_n_per_etf]:
            row_weight = _weight(row)
            if row_weight <= 0:
                continue
            # A bond fund stays one opaque bucket; equity funds key by issuer.
            key = (
                f"BOND_{symbol}"
                if symbol in bond_etfs
                else row.get("name") or row.get("cusip") or f"UNK_{symbol}"
            )
            _add(key, weight * row_weight)
        tail = sum(_weight(r) for r in ranked[top_n_per_etf:])
        if tail > 0:
            _add(f"TAIL_{symbol}", weight * tail)

    if positions and not effective:
        logger.warning(
            "effective_positions: no effective positions from a %d-position "
            "basket — every weight was zero or every fund was empty",
            len(positions),
        )
    return EffectivePositions(effective, non_nport, opaque)


def sector_rollup(
    holdings: Iterable[Mapping[str, Any]],
    sector_for_name: SectorFor,
    *,
    weight_scale: float = 1.0,
    top_n_resolve: int = 60,
) -> tuple[dict[str, float], dict[str, int]]:
    """Bucket one fund's holdings into sector weights.

    Non-equity categories bucket directly (see :func:`category_bucket`).
    The ``top_n_resolve`` heaviest remaining rows resolve through
    ``sector_for_name`` (``"Unknown"`` when it returns nothing); lighter
    rows become ``"Other (small)"``. Returns ``(weights, row_counts)``.
    """
    weights: dict[str, float] = {}
    counts: dict[str, int] = {}
    ranked = sorted(holdings, key=lambda r: -_weight(r))
    for index, row in enumerate(ranked):
        weight = _weight(row) * weight_scale
        if weight <= 0:
            continue
        bucket = category_bucket(row.get("asset_category"))
        if bucket is None:
            if index < top_n_resolve and row.get("name"):
                bucket = sector_for_name(row["name"]) or "Unknown"
            else:
                bucket = "Other (small)"
        weights[bucket] = weights.get(bucket, 0.0) + weight
        counts[bucket] = counts.get(bucket, 0) + 1
    return weights, counts


@dataclass(frozen=True)
class SectorView:
    """Look-through sector weights for a whole basket."""

    sectors: dict[str, float]
    # Rows that ended as "Unknown" or "Other (small)" inside equity funds.
    unknown_count: int


def basket_sector_view(
    basket: Iterable[Mapping[str, Any]],
    *,
    holdings_for: HoldingsFor,
    sector_for_name: SectorFor,
    sector_for_symbol: SectorFor,
    equity_etfs: set[str],
    bond_etfs: set[str],
    commodity_trusts: set[str],
    top_n_resolve: int = 30,
) -> SectorView:
    """Sector weights after look-through (notebook §4).

    Commodity trusts count as ``"Commodity"`` and bond funds as
    ``"Fixed Income"``. Equity funds roll up through :func:`sector_rollup`;
    one without a filing stays keyed by its own symbol. Single names use
    ``sector_for_symbol``.
    """
    sectors: dict[str, float] = {}
    unknown = 0

    def _add(key: str, weight: float) -> None:
        sectors[key] = sectors.get(key, 0.0) + weight

    for position in basket:
        symbol = _symbol(position)
        weight = _weight(position)
        if symbol in commodity_trusts:
            _add("Commodity", weight)
        elif symbol in bond_etfs:
            _add("Fixed Income", weight)
        elif symbol in equity_etfs:
            try:
                rows = holdings_for(symbol)
            except NportUnavailable:
                _add(symbol, weight)
                continue
            fund, counts = sector_rollup(
                rows,
                sector_for_name,
                weight_scale=weight,
                top_n_resolve=top_n_resolve,
            )
            for key, value in fund.items():
                _add(key, value)
            unknown += counts.get("Unknown", 0) + counts.get("Other (small)", 0)
        else:
            _add(sector_for_symbol(symbol) or "Unknown", weight)
    return SectorView(sectors, unknown)


@dataclass(frozen=True)
class Concentration:
    """HHI, effective-N, top-K weights and a single-name shock."""

    hhi: float
    effective_n: float | None
    top1: float
    top5: float
    top10: float
    largest: str | None
    largest_weight: float
    # Portfolio loss if the largest position falls by ``kill_shot_drop``.
    kill_shot: float


def concentration(
    weights: Mapping[str, float], *, kill_shot_drop: float = 0.20
) -> Concentration:
    """Concentration of a weight map (notebook §5 and §7)."""
    hhi = sum(w * w for w in weights.values())
    ranked = sorted(weights.values(), reverse=True)
    largest = max(weights, key=lambda k: weights[k]) if weights else None
    largest_weight = weights[largest] if largest is not None else 0.0
    return Concentration(
        hhi=hhi,
        effective_n=1.0 / hhi if hhi > 0 else None,
        top1=sum(ranked[:1]),
        top5=sum(ranked[:5]),
        top10=sum(ranked[:10]),
        largest=largest,
        largest_weight=largest_weight,
        kill_shot=largest_weight * kill_shot_drop,
    )


def _waterfill(weights: dict[str, float], cap: float, max_iter: int = 200) -> float:
    """Cap each weight and spread the excess pro-rata onto names below the cap.

    Mutates ``weights``; returns the weight that could not be placed.
    """
    for _ in range(max_iter):
        excess = 0.0
        under: dict[str, float] = {}
        for name, value in weights.items():
            if value > cap + _EPS:
                excess += value - cap
                weights[name] = cap
            elif value < cap - _EPS:
                under[name] = value
        if excess <= _EPS:
            return 0.0
        pool = sum(under.values())
        if pool <= _EPS:
            return excess
        for name, value in under.items():
            weights[name] += excess * (value / pool)
    return sum(max(0.0, value - cap) for value in weights.values())


def _enforce_top5(
    weights: dict[str, float], cap5: float, name_cap: float, max_iter: int = 200
) -> float:
    """Trim the top five to ``cap5``, placing the trim on names ranked 6+.

    Mutates ``weights``; returns the weight that could not be placed.
    """
    for _ in range(max_iter):
        ranked = sorted(weights, key=lambda n: -weights[n])
        top = ranked[:5]
        top_sum = sum(weights[n] for n in top)
        if top_sum <= cap5 + _EPS:
            return 0.0
        trim = top_sum - cap5
        for name in top:
            weights[name] -= trim * (weights[name] / top_sum)
        headroom = {
            n: name_cap - weights[n] for n in ranked[5:] if weights[n] < name_cap - _EPS
        }
        pool = sum(headroom.values())
        if pool <= _EPS:
            return trim
        placed = min(trim, pool)
        for name, room in headroom.items():
            weights[name] += placed * (room / pool)
        if placed < trim - 1e-12:
            return trim - placed
    return 0.0


@dataclass(frozen=True)
class Construction:
    """Rules-based target bands with enforced concentration caps."""

    refused: bool
    coverage: float
    # name -> {current, target, band_lo, band_hi, status}; None when refused.
    targets: dict[str, dict[str, Any]] | None
    residual: float
    top5: float
    capped_names: int
    redistributed: float


def construction_targets(
    effective: Mapping[str, float],
    *,
    max_single_name: float = 0.06,
    top5_cap: float = 0.35,
    band_abs: float = 0.015,
    min_coverage: float = 0.90,
) -> Construction:
    """Target bands and caps over effective positions (notebook §8).

    Refuses (``targets=None``) when the attributed coverage is below
    ``min_coverage``. Otherwise both caps are enforced by redistribution;
    weight that cannot fit under the caps is reported as ``residual``,
    never dropped, so ``sum(targets) + residual == coverage``.
    """
    coverage = sum(effective.values())
    capped = sum(1 for v in effective.values() if v > max_single_name + 1e-12)
    if coverage < min_coverage:
        return Construction(True, coverage, None, 0.0, 0.0, capped, 0.0)

    original = dict(effective)
    work = dict(effective)
    residual = _waterfill(work, max_single_name)
    residual += _enforce_top5(work, top5_cap, max_single_name)

    ordered = sorted(work.items(), key=lambda kv: -kv[1])
    targets: dict[str, dict[str, Any]] = {}
    for name, target in ordered:
        current = original[name]
        if target < current - 1e-9:
            status = "TRIM"
        elif target > current + 1e-9:
            status = "boost"
        else:
            status = "ok"
        targets[name] = {
            "current": current,
            "target": target,
            "band_lo": max(0.0, target - band_abs),
            "band_hi": target + band_abs,
            "status": status,
        }
    moved = sum(max(0.0, original[n] - targets[n]["target"]) for n in original)
    return Construction(
        refused=False,
        coverage=coverage,
        targets=targets,
        residual=residual,
        top5=sum(w for _, w in ordered[:5]),
        capped_names=capped,
        redistributed=moved - residual,
    )
