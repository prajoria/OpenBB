"""Backtest handoff route (#573).

One command:
- ``obb.portfolio_intel.backtest.run(basket, start, end, provider, live)``
  When ``live=True`` and ``openbb-backtest`` is installed, delegates to
  ``obb.backtest.portfolio(weights=..., start=..., end=...)`` and
  surfaces its result. Otherwise, returns a deterministic JSON dump
  (``mode="stub"``) the caller can persist and re-run later without
  changing signature.

Feature-flag rationale: portfolio-intel ships regardless of whether
openbb-backtest is present. The stub path guarantees a route that
never breaks; when the backtest extension lands, callers get real
results with no code change.
"""

from __future__ import annotations

# pylint: disable=unused-argument
import logging
from datetime import date
from decimal import Decimal

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_portfolio_intel.models import BacktestHandoffResult, BasketPosition
from openbb_portfolio_intel.routers.xray_router import _validate_basket

logger = logging.getLogger(__name__)

router = Router(
    prefix="/backtest",
    description=(
        "Handoff to openbb-backtest for basket-level backtests. Falls back "
        "to a deterministic JSON stub when the backtest extension is not "
        "installed or when live=False."
    ),
)


# ---------------------------------------------------------------------------
# Seam — dynamically resolves obb.backtest.portfolio, patched by tests.
# ---------------------------------------------------------------------------


def _resolve_backtest_endpoint():
    """Return ``obb.backtest.portfolio`` if installed, else ``None``.

    The lookup is deliberately dynamic per-call so a mid-session
    ``pip install openbb-backtest`` picks up on the next request.
    """
    try:
        from openbb import (
            obb,
        )  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        return None
    endpoint = getattr(getattr(obb, "backtest", None), "portfolio", None)
    return endpoint


def _weights_dict(positions: list[BasketPosition]) -> dict[str, float]:
    return {p.symbol: float(p.weight) for p in positions}


def _positions_from_basket(basket: list[dict]) -> list[BasketPosition]:
    positions = [
        BasketPosition(symbol=str(r["symbol"]), weight=Decimal(str(r["weight"])))
        for r in basket
    ]
    _validate_basket(positions)
    return positions


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Stub call — always safe, returns portable JSON dump.",
            code=[
                "obb.portfolio_intel.backtest.run("
                'basket=[{"symbol":"AAPL","weight":0.5},{"symbol":"MSFT","weight":0.5}],'
                'start="2025-01-01", end="2025-12-31", live=False)',
            ],
        ),
    ],
)
def run(
    basket: list[dict],
    start: date,
    end: date,
    provider: str | None = "fmp_cached",
    live: bool = False,
) -> OBBject[BacktestHandoffResult]:
    """Hand a basket off to ``obb.backtest.portfolio`` when live, else stub.

    Parameters
    ----------
    basket : list[dict]
        Rows of {"symbol": str, "weight": number}; weights sum to ~1.
    start, end : date
        Backtest window.
    provider : str | None
        Passed through to ``obb.backtest.portfolio`` when live.
    live : bool
        If True and openbb-backtest is installed, delegate. If False or
        extension missing, return a deterministic stub payload.

    Notes
    -----
    - Stub payload is stable across calls with the same input — safe
      for hashing / diffing / cache keys.
    - The stub is not a shim that fabricates fake returns; it is a
      structured JSON dump of the request that a follow-up job or a
      later ``live=True`` call can consume.
    """
    positions = _positions_from_basket(basket)
    weights = _weights_dict(positions)
    warnings: list[str] = []

    if live:
        endpoint = _resolve_backtest_endpoint()
        if endpoint is not None:
            try:
                resp = endpoint(
                    weights=weights,
                    start=start,
                    end=end,
                    provider=provider,
                )
                payload_obj = getattr(resp, "results", None)
                if payload_obj is None:
                    payload = {"raw": str(resp)}
                elif hasattr(payload_obj, "model_dump"):
                    payload = payload_obj.model_dump()
                elif isinstance(payload_obj, dict):
                    payload = payload_obj
                else:
                    payload = {"raw": str(payload_obj)}
                return OBBject(
                    results=BacktestHandoffResult(
                        mode="live", payload=payload, warnings=warnings
                    )
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"live handoff failed ({type(exc).__name__}); "
                    "falling back to stub"
                )
        else:
            warnings.append("openbb-backtest not installed — stub payload only")

    stub_payload = {
        "weights": weights,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "provider": provider,
        "note": (
            "Deterministic stub — feed to obb.backtest.portfolio once "
            "the extension is installed. Re-issue this call with live=True."
        ),
    }
    return OBBject(
        results=BacktestHandoffResult(
            mode="stub", payload=stub_payload, warnings=warnings
        )
    )
