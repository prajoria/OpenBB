"""Portfolio tools layer for OpenBB Agents.

Thin, LLM-safe wrappers over the **sanitized** ``portfolio_basket`` table
(via ``portfolio_app/src/data.py``). Per the data-access policy, only the
sanitized basket is exposed — raw lot-level tables (``Portfolio_Positions``,
``Account_Owner``) are never touched here, so account numbers and owner names
cannot leak through these tools.

Each function is a plain callable with type hints; ADK auto-generates tool
schemas from the signatures. Sector data is sourced from the ``fmp_cached``
provider's company profile (never raw SQL on provider tables).

Dependency injection
--------------------
The public functions accept optional ``_fetch`` / ``_profile`` callables so the
data layer and provider can be stubbed in unit tests without a DB or network.
When omitted, the real ``data.get_portfolio_basket_df`` and an fmp_cached
profile lookup are used.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openbb_agents._mcp_tool import mcp_tool

# ``data`` is importable because openbb_agents/__init__.py injects
# portfolio_app/src onto sys.path.


def _default_fetch():
    """Fetch the latest sanitized portfolio basket as a DataFrame."""
    from data import get_portfolio_basket_df  # type: ignore

    return get_portfolio_basket_df()


def _default_profile(symbol: str) -> dict:
    """Return {symbol, sector} for ``symbol`` via the fmp_cached provider."""
    try:
        from openbb import obb  # lazy — heavy import

        res = obb.equity.profile(symbol=symbol, provider="fmp_cached")
        rows = res.results if hasattr(res, "results") else res
        if rows:
            row = rows[0]
            sector = getattr(row, "sector", None)
            if sector is None and isinstance(row, dict):
                sector = row.get("sector")
            return {"symbol": symbol, "sector": sector or "Unknown"}
    except Exception:  # noqa: BLE001 — degrade gracefully to Unknown
        pass
    return {"symbol": symbol, "sector": "Unknown"}


@mcp_tool
def get_positions(
    *,
    _fetch: Callable[[], Any] | None = None,
) -> list[dict]:
    """Return all current positions from the sanitized portfolio basket.

    Returns
    -------
    list[dict]
        One dict per symbol with keys: ``symbol``, ``shares``, ``cost_basis``,
        ``current_value``, ``unrealized_gain_pct``, ``weight_pct``. Empty list
        when the basket has no rows.
    """
    df = (_fetch or _default_fetch)()
    if df is None or getattr(df, "empty", True):
        return []

    out: list[dict] = []
    for row in df.to_dict(orient="records"):
        out.append(
            {
                "symbol": row.get("symbol"),
                "shares": row.get("total_quantity"),
                "cost_basis": row.get("total_cost_basis"),
                "current_value": row.get("total_current_value"),
                "unrealized_gain_pct": row.get("pct_return"),
                "weight_pct": row.get("portfolio_weight_pct"),
            }
        )
    return out


@mcp_tool
def get_sector_exposure(
    *,
    _fetch: Callable[[], Any] | None = None,
    _profile: Callable[[str], dict] | None = None,
) -> list[dict]:
    """Aggregate portfolio market value by GICS sector.

    Returns
    -------
    list[dict]
        ``[{sector, market_value, weight_pct}, …]`` sorted by descending weight.
        ``weight_pct`` values sum to 100 (when total market value > 0).
    """
    positions = get_positions(_fetch=_fetch)
    if not positions:
        return []

    profile = _profile or _default_profile

    by_sector: dict[str, float] = {}
    for pos in positions:
        symbol = pos.get("symbol")
        value = pos.get("current_value") or 0.0
        sector = profile(symbol).get("sector", "Unknown") if symbol else "Unknown"
        by_sector[sector] = by_sector.get(sector, 0.0) + float(value)

    total = sum(by_sector.values())
    rows = [
        {
            "sector": sector,
            "market_value": market_value,
            "weight_pct": round(market_value / total * 100, 2) if total else 0.0,
        }
        for sector, market_value in by_sector.items()
    ]
    rows.sort(key=lambda r: r["weight_pct"], reverse=True)
    return rows
