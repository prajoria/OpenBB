"""Candidate trades and weight-space what-if diffs (#2315).

The arithmetic behind the portfolio notebooks' what-if chapter
(``notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`` §2-§4):
turning a smart-money conviction ranking into candidate trades, and
previewing how those trades move the basket's weights and concentration.

Unlike the notebook, nothing here guesses. A symbol without a price is an
error rather than a neutral $100, and a trade that would leave a negative
share count is rejected rather than producing negative weights. The full
``run_whatif`` engine in :mod:`openbb_portfolio_intel.analytics.whatif`
(covariance, benchmark, risk deltas) is separate and unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# HHI moves smaller than this read as "unchanged" (notebook §4).
HHI_TOLERANCE = 0.001


def _field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def candidate_trades(
    top_conviction: Iterable[Any],
    *,
    top_n: int = 3,
    buy_shares: int = 5,
    close_shares: int = 20,
    label: str | None = None,
) -> list[dict[str, Any]]:
    """Turn the heaviest conviction names into candidate trades.

    Each of the first ``top_n`` items (dicts or objects with ``symbol``,
    ``composite`` and ``signal_count``) becomes a buy of ``buy_shares`` when
    its composite is positive, otherwise a close of ``close_shares``. A
    ``label`` (for example a fixture's) is appended to every rationale. An
    empty ranking gives no trades; nothing is invented.
    """
    trades = []
    for item in list(top_conviction)[:top_n]:
        composite = float(_field(item, "composite", 0.0))
        signals = int(_field(item, "signal_count", 0))
        if composite > 0:
            action, delta = "buy", buy_shares
        else:
            action, delta = "close", -close_shares
        trades.append(
            {
                "symbol": _field(item, "symbol"),
                "action": action,
                "delta_shares": delta,
                "rationale": (
                    f"smart_money composite {composite:+.2f} ({signals} signals)"
                    + (f" — {label}" if label else "")
                ),
            }
        )
    return trades


@dataclass(frozen=True)
class WhatIfDiff:
    """Weights and concentration before and after a set of trades."""

    weights_before: dict[str, float]
    weights_after: dict[str, float]
    hhi_before: float
    hhi_after: float
    effective_n_before: float | None
    effective_n_after: float | None
    # "concentrated", "diversified" or "unchanged".
    verdict: str


def _weights(
    shares: Mapping[str, float], prices: Mapping[str, float]
) -> dict[str, float]:
    values = {symbol: count * prices[symbol] for symbol, count in shares.items()}
    total = sum(values.values())
    return (
        {symbol: value / total for symbol, value in values.items()} if total > 0 else {}
    )


def _hhi(weights: Mapping[str, float]) -> float:
    return sum(w * w for w in weights.values())


def whatif_weight_diff(
    basket: Iterable[Mapping[str, Any]],
    prices: Mapping[str, float],
    trades: Iterable[Mapping[str, Any]],
    *,
    account_size: float = 100_000.0,
) -> WhatIfDiff:
    """Preview how share trades move a weighted basket (notebook §3-§4).

    The basket's weights become share counts at ``prices`` for an account of
    ``account_size``; each trade adds ``delta_shares``; weights are then
    recomputed from market values.

    Raises :class:`ValueError` when a basket or trade symbol has no positive
    price, or when a trade would leave a negative share count.
    """
    positions = list(basket)
    moves = list(trades)
    needed = {p["symbol"] for p in positions} | {t["symbol"] for t in moves}
    missing = sorted(s for s in needed if not prices.get(s, 0) > 0)
    if missing:
        raise ValueError(f"no positive price for: {', '.join(missing)}")

    before = {
        p["symbol"]: account_size * float(p["weight"]) / prices[p["symbol"]]
        for p in positions
    }
    after = dict(before)
    for trade in moves:
        symbol = trade["symbol"]
        after[symbol] = after.get(symbol, 0.0) + float(trade["delta_shares"])
        if after[symbol] < -1e-9:
            raise ValueError(
                f"{symbol}: trade of {trade['delta_shares']} shares would go short "
                f"(holding {before.get(symbol, 0.0):.4f})"
            )

    weights_before = _weights(before, prices)
    weights_after = _weights(after, prices)
    hhi_before, hhi_after = _hhi(weights_before), _hhi(weights_after)
    change = hhi_after - hhi_before
    if change > HHI_TOLERANCE:
        verdict = "concentrated"
    elif change < -HHI_TOLERANCE:
        verdict = "diversified"
    else:
        verdict = "unchanged"
    return WhatIfDiff(
        weights_before=weights_before,
        weights_after=weights_after,
        hhi_before=hhi_before,
        hhi_after=hhi_after,
        effective_n_before=1 / hhi_before if hhi_before > 0 else None,
        effective_n_after=1 / hhi_after if hhi_after > 0 else None,
        verdict=verdict,
    )
