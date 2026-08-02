"""Basket resolver tests (#1714).

Covers the ``basket_id → list[Position]`` contract:

- ``"demo"`` returns the baked-in 5-symbol basket
- Any other id is treated as user_id, resolved via the PortfolioStore
- Cash equivalents (SPAXX/FCASH) are dropped
- Weights renormalize to sum to 1.0 after cash-drop
- Loud-empty: no snapshot / cash-only snapshot raises BasketNotFoundError
- XSS / malformed id rejected at the regex allowlist

R7.11 twin notes in load-bearing docstrings.
"""

from __future__ import annotations

import pytest
from openbb_portfolio_intel.basket_resolver import (
    BasketNotFoundError,
    Position,
    resolve_basket,
    validate_basket_id,
)


class _FakeStore:
    """Minimal PortfolioStore-Protocol double for resolver tests.

    Populated with ``(user_id, symbol, weight)`` tuples; ``latest_snapshot``
    returns a synthetic row per user; ``positions_for`` returns matching
    rows for the snapshot.
    """

    def __init__(self, holdings: list[tuple[str, str, float]]) -> None:
        self._holdings = holdings
        # snapshot_id per user
        self._snap_id = {u: f"snap-{u}" for u, _, _ in holdings}

    def latest_snapshot(self, user_id: str):
        if user_id not in self._snap_id:
            return None
        return {
            "snapshot_id": self._snap_id[user_id],
            "user_id": user_id,
            "snapshot_date": "2026-08-01",
        }

    def positions_for(self, snapshot_id: str) -> list:
        return [
            {"symbol": sym, "percent_of_account": pct, "user_id": u}
            for u, sym, pct in self._holdings
            if self._snap_id.get(u) == snapshot_id
        ]

    # Unused Protocol methods
    def snapshot_exists(self, *_):
        return None  # noqa: E704

    def insert_snapshot(self, *_):
        return None  # noqa: E704

    def insert_positions(self, *_):
        return 0  # noqa: E704

    def list_snapshots(self, *_):
        return []  # noqa: E704

    def transaction(self):
        return None  # noqa: E704

    def close(self):
        return None  # noqa: E704


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------


def test_demo_returns_5_symbols() -> None:
    positions = resolve_basket("demo")
    assert len(positions) == 5
    assert {p.symbol for p in positions} == {"AAPL", "MSFT", "GOOGL", "NVDA", "META"}


def test_demo_weights_sum_to_one() -> None:
    positions = resolve_basket("demo")
    assert sum(p.weight for p in positions) == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# user_id resolution
# ---------------------------------------------------------------------------


def test_resolves_user_from_store() -> None:
    store = _FakeStore(
        [
            ("alice", "AAPL", 0.5),
            ("alice", "MSFT", 0.3),
            ("alice", "NVDA", 0.2),
        ]
    )
    positions = resolve_basket("alice", store=store)
    assert {p.symbol for p in positions} == {"AAPL", "MSFT", "NVDA"}
    assert sum(p.weight for p in positions) == pytest.approx(1.0)


def test_dropping_cash_still_normalizes_to_one() -> None:
    """R7.11 twin: remove the renormalize step -> weights sum < 1."""
    store = _FakeStore(
        [
            ("alice", "AAPL", 0.4),
            ("alice", "MSFT", 0.4),
            ("alice", "SPAXX", 0.2),  # cash, dropped
        ]
    )
    positions = resolve_basket("alice", store=store)
    assert {p.symbol for p in positions} == {"AAPL", "MSFT"}
    # After renorm each is 0.5, sum = 1.0.
    assert sum(p.weight for p in positions) == pytest.approx(1.0)


def test_all_cash_snapshot_raises_loud_empty() -> None:
    """R7.11 twin: swap raise for return [] -> the loud-empty guard is gone."""
    store = _FakeStore(
        [
            ("alice", "SPAXX", 0.5),
            ("alice", "FCASH", 0.5),
        ]
    )
    with pytest.raises(BasketNotFoundError, match="non-cash"):
        resolve_basket("alice", store=store)


def test_unknown_user_raises_loud_empty() -> None:
    store = _FakeStore([])
    with pytest.raises(BasketNotFoundError, match="no positions snapshot"):
        resolve_basket("nobody", store=store)


def test_cash_symbol_variants_all_dropped() -> None:
    store = _FakeStore(
        [
            ("alice", "SPAXX**", 0.1),
            ("alice", "FCASH", 0.1),
            ("alice", "FDRXX", 0.1),
            ("alice", "AAPL", 0.7),
        ]
    )
    positions = resolve_basket("alice", store=store)
    assert [p.symbol for p in positions] == ["AAPL"]
    assert positions[0].weight == pytest.approx(1.0)


def test_zero_weight_positions_raises() -> None:
    store = _FakeStore([("alice", "AAPL", 0.0), ("alice", "MSFT", 0.0)])
    with pytest.raises(BasketNotFoundError, match="non-positive"):
        resolve_basket("alice", store=store)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_validate_basket_id_accepts_common_forms() -> None:
    for bid in ("demo", "alice", "user_1", "a.b-c_1", "A" * 64):
        assert validate_basket_id(bid) == bid


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "<script>alert(1)</script>",
        "user id",  # space
        "'; DROP TABLE users;--",
        "A" * 65,  # too long
        "user/id",  # slash
    ],
)
def test_validate_basket_id_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError, match="basket_id"):
        validate_basket_id(bad)


def test_resolve_basket_rejects_bad_id() -> None:
    with pytest.raises(ValueError):
        resolve_basket("<script>alert(1)</script>")


# ---------------------------------------------------------------------------
# Position dataclass
# ---------------------------------------------------------------------------


def test_position_is_frozen() -> None:
    p = Position(symbol="AAPL", weight=0.5)
    with pytest.raises((AttributeError, Exception)):
        p.symbol = "MSFT"  # type: ignore[misc]
