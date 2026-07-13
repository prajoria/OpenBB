"""RiskManager — 8-gate trade admission (PRD §8).

Every proposed trade funnels through :meth:`RiskManager.propose_trade`. No
path bypasses it — the chokepoint CI test (§8.6) lands in Phase 2 alongside
IntradaySession. This module ships the gate logic + tests only.

Gate order (PRD §8.2) matters — first REJECT wins, short-circuits the rest:
    G1 flat_by_close           — no new opens after cutoff (default 15:50 ET)
    G2 max_open_positions      — already at max concurrent open positions
    G3 day_dd_pct_breach       — day drawdown exceeds day_dd_pct
    G4 per_symbol_cooldown     — symbol in cooldown after a stopout
    G5 sector_cap              — sector at max_positions_per_sector
    G6 max_position_size       — single position exceeds equity-pct limit
    G7 total_notional_cap      — total notional exceeds equity-pct cap
    G8 duplicate_position      — already long the symbol; block additional

Every REJECTED TradeDecision carries reason_code ∈ {G1..G8} and gate name
so journal filters can attribute exactly which rule fired. Every proposed
plan is echoed back on the TradeDecision.plan field for audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any, Mapping

import exchange_calendars as xcals

from openbb_fmp_trading.models import RiskConfig, RiskState, TickData, TradeDecision

# Phase 2 replaces this alias with openbb_techtrade.models.TradePlan once the
# tick loop wires techtrade signals -> RiskManager. Staying loose here keeps
# P1.3 free of a techtrade dep; propose_trade() only reads plan["symbol"],
# plan["notional"], and plan.get("sector") — a Mapping is enough.
TradePlan = Mapping[str, Any]


@dataclass
class RiskManager:
    """Single source of truth on trade admission. Session-scoped."""

    config: RiskConfig
    starting_equity: Decimal
    exchange: str = "NASDAQ"
    state: RiskState = field(
        default_factory=lambda: RiskState(
            ts=datetime.now(timezone.utc),
            gates_active=["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"],
            gates_tripped_today=[],
            cooldowns={},
            flat_by_close_window_open=False,
            day_dd_pct=0.0,
            open_position_count=0,
            max_open_positions=5,
        )
    )
    # Session-scoped ledgers (mutated by IntradaySession callbacks in P2):
    open_positions_by_symbol: dict[str, Decimal] = field(default_factory=dict)
    open_positions_by_sector: dict[str, int] = field(default_factory=dict)
    total_notional: Decimal = Decimal("0")
    day_pnl: Decimal = Decimal("0")

    def propose_trade(self, plan: TradePlan, tick: TickData) -> TradeDecision:
        """Run gates G1..G8 in order; return first REJECT or an APPROVED decision.

        The gate order matches PRD §8.2 exactly. Do NOT reorder without
        updating the PRD — the order encodes safety priorities (flat-by-close
        beats everything; day-DD before per-symbol; etc.).
        """
        for gate in (
            self._g1, self._g2, self._g3, self._g4,
            self._g5, self._g6, self._g7, self._g8,
        ):
            decision = gate(plan, tick)
            if decision is not None:
                # Deduplicate reason_code additions — a gate can fire many times
                # a day but shows up once in gates_tripped_today.
                self.state.gates_tripped_today = sorted(
                    {*self.state.gates_tripped_today, decision.reason_code}
                )
                return decision
        return TradeDecision(verdict="APPROVED", plan=dict(plan))

    # ------------------------------------------------------------------ G1
    def _g1(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """flat_by_close — no new opens after config.flat_by_close_time_et ET."""
        cutoff_h, cutoff_m = map(int, self.config.flat_by_close_time_et.split(":"))
        cal = xcals.get_calendar(self.exchange)
        now_local = tick.ts.astimezone(cal.tz)
        if now_local.time() >= time(cutoff_h, cutoff_m):
            self.state.flat_by_close_window_open = True
            return TradeDecision(
                verdict="REJECTED",
                reason=(
                    f"in flat-by-close window; no new opens after "
                    f"{self.config.flat_by_close_time_et} ET"
                ),
                reason_code="G1",
                gate="flat_by_close",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G2
    def _g2(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """max_open_positions — hard cap on concurrent open positions."""
        if self.state.open_position_count >= self.config.max_open_positions:
            return TradeDecision(
                verdict="REJECTED",
                reason=(
                    f"already at max_open_positions="
                    f"{self.config.max_open_positions}"
                ),
                reason_code="G2",
                gate="max_open_positions",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G3
    def _g3(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """day_dd_pct_breach — session drawdown exceeds config.day_dd_pct.

        Note: existing positions are NOT force-closed by this gate. G3 only
        prevents deepening the hole — existing stops still work naturally.
        """
        if self.state.day_dd_pct <= self.config.day_dd_pct:
            return TradeDecision(
                verdict="REJECTED",
                reason=(
                    f"day drawdown {self.state.day_dd_pct:.2f}% "
                    f"exceeds day_dd_pct={self.config.day_dd_pct}%"
                ),
                reason_code="G3",
                gate="day_dd_pct_breach",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G4
    def _g4(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """per_symbol_cooldown — symbol in G4 cooldown after a prior stopout."""
        symbol = plan["symbol"]
        until = self.state.cooldowns.get(symbol)
        if until is not None and tick.ts < until:
            # Ceiling-division to minutes so "14min 30s" reports as 15min, not 14.
            mins = int((until - tick.ts).total_seconds() // 60) + 1
            return TradeDecision(
                verdict="REJECTED",
                reason=f"symbol {symbol} in {mins}min cooldown after stopout",
                reason_code="G4",
                gate="per_symbol_cooldown",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G5
    def _g5(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """sector_cap — sector at max_positions_per_sector.

        Skipped when plan carries no sector (e.g. crypto or ETF). Downstream
        IntradaySession populates plan["sector"] via cached equity.profile.
        """
        sector = plan.get("sector")
        if sector is None:
            return None
        current = self.open_positions_by_sector.get(sector, 0)
        cap = self.config.max_positions_per_sector
        if current >= cap:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"sector {sector} at cap {current}/{cap} positions",
                reason_code="G5",
                gate="sector_cap",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G6
    def _g6(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """max_position_size — single-position notional cap as % of equity."""
        notional = Decimal(str(plan["notional"]))
        limit = (
            self.starting_equity
            * Decimal(str(self.config.max_position_size_pct_equity))
            / Decimal("100")
        )
        if notional > limit:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"position size {notional} exceeds max_position_size={limit}",
                reason_code="G6",
                gate="max_position_size",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G7
    def _g7(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """total_notional_cap — sum(open_notional) + this trade <= equity-pct cap."""
        notional = Decimal(str(plan["notional"]))
        cap = (
            self.starting_equity
            * Decimal(str(self.config.max_notional_pct_equity))
            / Decimal("100")
        )
        if (self.total_notional + notional) > cap:
            return TradeDecision(
                verdict="REJECTED",
                reason=(
                    f"total notional {self.total_notional + notional} "
                    f"exceeds max_notional={cap}"
                ),
                reason_code="G7",
                gate="total_notional_cap",
                plan=dict(plan),
            )
        return None

    # ------------------------------------------------------------------ G8
    def _g8(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        """duplicate_position — no additional trades on a symbol already long.

        Hard rule (not configurable) — v1 doesn't support pyramid entries.
        """
        symbol = plan["symbol"]
        if symbol in self.open_positions_by_symbol:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"already long {symbol}; blocking additional long",
                reason_code="G8",
                gate="duplicate_position",
                plan=dict(plan),
            )
        return None
