"""Basket-id → holdings resolver (#1714).

The widget backend has 16 endpoints that take ``basket_id`` or
``account_id`` and want to know "what's in that basket". Today
everything but ``basket_id="demo"`` is a 422 gate. This module lifts
the gate by resolving basket_id against the canonical MySQL positions
store (#1744).

Design:

- ``"demo"`` — hardcoded 5-symbol basket, kept for backward-compat with
  every existing demo fixture and E2E test.
- Anything else — treated as ``user_id``. We pull the latest snapshot
  for that user from :class:`MySqlPortfolioStore`, drop cash equivalents
  (SPAXX/FCASH), and return ``(symbol, weight)`` pairs where weight is
  normalized to sum to 1.
- Unknown basket_id (no snapshots for that user) — raises
  :class:`BasketNotFoundError`. Never returns silent ``[]``.

Zero widget-backend consumers today call this directly — the retrofit
wrapper in ``widgets_endpoints.py`` invokes it inside
``@with_chain`` seams so a tier failure falls back to the demo stub.

Security posture: same last-4-mask on ``account_number`` as the
importer. This module reads from the store; it never persists new PII.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Same allowlist regex the widget backend uses for basket_id.
_BASKET_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# Cash-equivalent symbols we drop from the effective basket.
_CASH_SYMBOLS: frozenset[str] = frozenset(
    {"SPAXX", "SPAXX**", "FCASH", "FDRXX", "FZFXX", "SPRXX"}
)


# Baked-in demo basket (5 mega-caps). Kept in sync with
# widget_backend/widgets_endpoints.py:_DEMO_BASKET_CONSENSUS.
_DEMO_BASKET: tuple[tuple[str, float], ...] = (
    ("AAPL", 0.28),
    ("MSFT", 0.24),
    ("GOOGL", 0.19),
    ("NVDA", 0.16),
    ("META", 0.13),
)


class BasketNotFoundError(RuntimeError):
    """No snapshot exists for the requested basket_id / user_id.

    Raised (never silently returned as []) so the ChainedFetcher wrapper
    treats it as a tier failure and falls to the demo stub.
    """


@dataclass(frozen=True)
class Position:
    """One row in a resolved basket.

    ``symbol`` is normalized upper-case; ``weight`` is fraction-of-1.
    """

    symbol: str
    weight: float


def validate_basket_id(basket_id: str) -> str:
    """Reject XSS / malformed basket_id strings. Returns the normalized id."""
    if not _BASKET_ID_RE.match(basket_id):
        raise ValueError(
            f"basket_id must match [A-Za-z0-9_.-]{{1,64}}; got {basket_id!r}"
        )
    return basket_id


def resolve_basket(
    basket_id: str,
    store: Any | None = None,
) -> list[Position]:
    """Return the effective basket for ``basket_id``.

    Args:
        basket_id: ``"demo"`` or a user_id (regex-validated).
        store: Optional injected PortfolioStore (for tests). Defaults to
            the canonical MySQL store via ``get_default_store()``.

    Returns:
        List of :class:`Position` with weights summing to ~1.0.

    Raises:
        ValueError: basket_id fails the regex allowlist.
        BasketNotFoundError: no snapshot exists for the user, or the
            snapshot has no non-cash symbols.
    """
    validate_basket_id(basket_id)

    if basket_id == "demo":
        return [Position(symbol=s, weight=w) for s, w in _DEMO_BASKET]

    # basket_id ≡ user_id (for now — richer schemes tracked in follow-ups).
    if store is None:
        # Deferred import: portfolio_snapshot_importer is optional at
        # widget-backend install time (browser harness CI doesn't install
        # it). Callers can always inject ``store=`` for tests.
        try:
            from portfolio_snapshot_importer import (  # noqa: PLC0415
                get_default_store,
            )
        except ImportError as exc:
            raise BasketNotFoundError(
                f"portfolio_snapshot_importer is not installed; cannot "
                f"resolve basket_id={basket_id!r} without an injected store"
            ) from exc
        store = get_default_store()

    snap = store.latest_snapshot(basket_id)
    if snap is None:
        raise BasketNotFoundError(
            f"no positions snapshot found for user_id={basket_id!r}"
        )

    snapshot_id = _row_field(snap, "snapshot_id")
    if not snapshot_id:
        raise BasketNotFoundError(
            f"latest snapshot for {basket_id!r} has no snapshot_id"
        )

    rows = store.positions_for(snapshot_id)
    positions: list[tuple[str, float]] = []
    for r in rows:
        symbol = (_row_field(r, "symbol") or "").upper()
        if not symbol or symbol in _CASH_SYMBOLS:
            continue
        pct = _row_field(r, "percent_of_account")
        if pct is None:
            continue
        try:
            weight = float(pct)
        except (TypeError, ValueError):
            continue
        positions.append((symbol, weight))

    if not positions:
        raise BasketNotFoundError(
            f"snapshot {snapshot_id!r} for {basket_id!r} has no non-cash "
            "positions (only cash equivalents?)"
        )

    # Renormalize so weights sum to 1.0 (cash rows removed above).
    total = sum(w for _, w in positions)
    if total <= 0:
        raise BasketNotFoundError(
            f"snapshot {snapshot_id!r} has non-positive weight sum ({total})"
        )
    return [Position(symbol=s, weight=w / total) for s, w in positions]


def _row_field(row: Any, key: str) -> Any:
    """Fetch a field from a sqlite3.Row / dict / tuple-cursor row."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None
