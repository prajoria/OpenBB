"""``risk_parity`` — risk-based allocation (component 10.4).

A :class:`~openbb_backtest.strategies.base.WeightStrategy` offering two
**long-only, sum-to-one** allocation schemes estimated from a trailing return
window:

- ``"inverse_vol"`` — plain inverse-volatility: each asset's weight is
  proportional to the reciprocal of its trailing return standard deviation, so a
  more volatile asset receives proportionally less capital.
- ``"hrp"`` — López de Prado's **Hierarchical Risk Parity**: build a
  correlation-distance matrix, cluster it with single linkage, reorder the
  covariance matrix so similar assets are adjacent (*quasi-diagonalization*), and
  split capital top-down by inverse-cluster-variance (*recursive bisection*).

The clustering uses :mod:`scipy.cluster.hierarchy` (BSD-licensed and already a
declared dependency of this package from component 8.1), so no pure-numpy linkage
re-implementation is required.

See ``docs/designs/backtest-design/10-strategy-library.md`` and
López de Prado, *Building Diversified Portfolios that Outperform Out of Sample*
(2016).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

from openbb_backtest.interfaces import MarketData
from openbb_backtest.registry import register_strategy
from openbb_backtest.strategies.base import WeightStrategy

#: Allocation schemes accepted by :class:`RiskParity`.
_METHODS = frozenset({"inverse_vol", "hrp"})


def quasi_diagonal_order(corr: np.ndarray) -> list[int]:
    """Return the López de Prado quasi-diagonalization order for ``corr``.

    The correlation matrix is converted to the distance metric
    ``d_ij = sqrt((1 - rho_ij) / 2)``, clustered with single linkage, and the
    resulting dendrogram is unrolled so that the most-correlated assets end up
    adjacent. The return value is a permutation of column indices into ``corr``.

    Parameters
    ----------
    corr
        A square (n, n) correlation matrix.

    Returns
    -------
    list[int]
        Column indices of ``corr`` in quasi-diagonal order.
    """
    corr = np.asarray(corr, dtype=float)
    n = corr.shape[0]
    if n <= 1:
        return list(range(n))
    # Correlation distance: perfectly correlated -> 0, perfectly anti -> 1.
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, None))
    np.fill_diagonal(dist, 0.0)
    link = linkage(squareform(dist, checks=False), method="single")
    return _unroll_linkage(link)


def _unroll_linkage(link: np.ndarray) -> list[int]:
    """Unroll a scipy linkage matrix into the quasi-diagonal leaf ordering."""
    link = link.astype(int)
    num_items = int(link[-1, 3])  # leaves in the final (root) cluster == n
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    while sort_ix.max() >= num_items:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)  # make room
        clusters = sort_ix[sort_ix >= num_items]  # rows still pointing at merges
        i = clusters.index
        j = clusters.to_numpy() - num_items
        sort_ix[i] = link[j, 0]  # replace with the merge's first child
        right = pd.Series(link[j, 1], index=i + 1)  # second child slots after
        sort_ix = pd.concat([sort_ix, right]).sort_index()
        sort_ix.index = range(sort_ix.shape[0])
    return [int(x) for x in sort_ix]


def _inverse_vol_weights(vol: pd.Series) -> pd.Series:
    """Weights proportional to ``1 / vol`` (inverse volatility), summing to one."""
    inv = 1.0 / vol
    return inv / inv.sum()


def _inverse_variance_weights(cov: pd.DataFrame) -> np.ndarray:
    """Inverse-variance portfolio weights for a covariance slice (sum to one)."""
    ivp = 1.0 / np.diag(cov.to_numpy())
    ivp /= ivp.sum()
    return ivp


def _cluster_variance(cov: pd.DataFrame, items: Sequence[str]) -> float:
    """Variance of the inverse-variance portfolio over ``items``."""
    sub = cov.loc[items, items]
    weights = _inverse_variance_weights(sub)
    return float(weights @ sub.to_numpy() @ weights)


def _hrp_weights(cov: pd.DataFrame, corr: pd.DataFrame) -> pd.Series:
    """Hierarchical Risk Parity weights via recursive bisection (sum to one)."""
    symbols = list(cov.index)
    order = quasi_diagonal_order(corr.to_numpy())
    ordered = [symbols[i] for i in order]
    weights = pd.Series(1.0, index=ordered)
    clusters: list[list[str]] = [ordered]
    while clusters:
        clusters = [
            cluster[start:end]
            for cluster in clusters
            for start, end in ((0, len(cluster) // 2), (len(cluster) // 2, len(cluster)))
            if len(cluster) > 1
        ]
        for left, right in zip(clusters[0::2], clusters[1::2]):
            var_left = _cluster_variance(cov, left)
            var_right = _cluster_variance(cov, right)
            alpha = 1.0 - var_left / (var_left + var_right)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
    return weights.reindex(symbols)


@register_strategy("risk_parity")
class RiskParity(WeightStrategy):
    """Long-only inverse-vol or HRP allocation over a trailing return window."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        method: str = "inverse_vol",
        lookback: int = 60,
        id: str = "risk_parity",  # noqa: A002 - mirrors the Strategy protocol field
    ) -> None:
        super().__init__(id)
        self.symbols = list(symbols)
        self.method = str(method)
        self.lookback = int(lookback)
        if not self.symbols:
            raise ValueError("risk_parity requires a non-empty symbol universe")
        if self.method not in _METHODS:
            raise ValueError(
                f"risk_parity method must be one of {sorted(_METHODS)}; got {self.method!r}"
            )
        if self.lookback < 2:
            raise ValueError("risk_parity needs lookback>=2")

    def target_weights(self, data: MarketData) -> pd.Series:
        """Long-only weights summing to one from the trailing return window."""
        rets, present = self._trailing_returns(data)
        if rets is None:
            return pd.Series(1.0 / len(present), index=present)
        if self.method == "inverse_vol":
            return _inverse_vol_weights(rets.std())
        return _hrp_weights(rets.cov(), rets.corr())

    def _trailing_returns(self, data: MarketData) -> tuple[pd.DataFrame | None, list[str]]:
        """Return (daily returns, present symbols); returns ``None`` if degenerate.

        A ``None`` returns frame signals that the caller should fall back to an
        equal-weight book (too few observations or a single usable symbol).
        """
        win = data.window(self.symbols, self.lookback + 1)
        closes = win.pivot_table(index="session", columns="symbol", values="close")
        present = [s for s in self.symbols if s in closes.columns]
        if len(present) <= 1:
            return None, present or list(self.symbols)
        rets = closes[present].pct_change().dropna(how="all")
        if len(rets) < 2:
            return None, present
        return rets, present
