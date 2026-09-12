"""Compute adapters that materialize TechTrade results into EOD snapshots."""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydantic import BaseModel

from openbb_techtrade.engine.movers import list_movers
from openbb_techtrade.engine.universe import GICS_SECTOR_ETFS
from openbb_techtrade.models import TradePlan
from openbb_techtrade.snapshot.datasets import (
    DEFAULT_EXCHANGE_CALENDAR,
    SURVIVORSHIP_SENSITIVE_DATASETS,
    SURVIVORSHIP_UNCORRECTED,
    TECHTRADE_DATASETS,
    techtrade_entity_key,
)
from openbb_techtrade.snapshot.refresh import ComputedSnapshot
from openbb_techtrade.snapshot.store import canonical_key

MoverFetcher = Callable[..., object]
EventFetcher = Callable[[date, list[str]], Iterable["MarketEvent"]]
ComputeFunction = Callable[[str, date], object]
MembershipFetcher = Callable[[str, date], "MembershipSnapshot | None"]
EventSource = Callable[[date], Iterable[object]]


class EventKind(str, Enum):
    """Between-session market events that affect EOD snapshot validity."""

    EARNINGS = "earnings"
    DELISTED = "delisted"
    HALTED = "halted"


@dataclass(frozen=True)
class MarketEvent:
    """A public market event associated with one symbol."""

    symbol: str
    kind: EventKind

    def __post_init__(self) -> None:
        """Normalize the public symbol identifier."""
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("event symbol must be non-empty")
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True)
class MembershipSnapshot:
    """Universe membership captured for an exact exchange session."""

    as_of_session: date
    exchange_calendar: str
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        """Normalize and de-duplicate membership symbols."""
        if not self.exchange_calendar.strip():
            raise ValueError("membership exchange_calendar must be non-empty")
        symbols = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in self.symbols if symbol.strip()
            )
        )
        object.__setattr__(self, "symbols", symbols)


def _event_row(value: object) -> dict[str, Any]:
    row = _jsonable(value)
    if not isinstance(row, dict):
        raise TypeError("event source rows must be JSON objects")
    return row


def _event_symbol(row: Mapping[str, object]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


class PublicEventRiskProvider:
    """Combine public earnings, delisting, and halt sources for target symbols."""

    def __init__(
        self,
        *,
        earnings_fetcher: EventSource,
        delisted_fetcher: EventSource,
        halted_fetcher: EventSource,
    ) -> None:
        self._earnings_fetcher = earnings_fetcher
        self._delisted_fetcher = delisted_fetcher
        self._halted_fetcher = halted_fetcher

    def __call__(self, session: date, symbols: list[str]) -> list[MarketEvent]:
        """Return freshly fetched public events for the requested symbols."""
        events: list[MarketEvent] = []
        for value in self._earnings_fetcher(session):
            row = _event_row(value)
            symbol = _event_symbol(row)
            event_date = row.get("date") or row.get("report_date")
            if symbol and (
                event_date is None or date.fromisoformat(str(event_date)) == session
            ):
                events.append(MarketEvent(symbol, EventKind.EARNINGS))
        for value in self._delisted_fetcher(session):
            row = _event_row(value)
            symbol = _event_symbol(row)
            event_date = (
                row.get("delisted_date") or row.get("delistedDate") or row.get("date")
            )
            if symbol and (
                event_date is None or date.fromisoformat(str(event_date)) <= session
            ):
                events.append(MarketEvent(symbol, EventKind.DELISTED))
        for value in self._halted_fetcher(session):
            symbol = _event_symbol(_event_row(value))
            if symbol:
                events.append(MarketEvent(symbol, EventKind.HALTED))
        target = {symbol.strip().upper() for symbol in symbols}
        return [event for event in dict.fromkeys(events) if event.symbol in target]


def _no_events(_session: date, _symbols: list[str]) -> tuple[()]:
    return ()


def _no_membership(_segment: str, _session: date) -> None:
    return None


def _engine_version() -> str:
    try:
        return version("openbb-techtrade")
    except PackageNotFoundError:  # pragma: no cover - editable installs normally exist
        return "source"


def _jsonable(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"snapshot value is not JSON-safe: {type(value).__name__}")


def _fetch_earnings(session: date) -> Iterable[object]:
    from openbb import obb

    equity = getattr(obb, "equity")
    result = equity.calendar.earnings(
        start_date=session.isoformat(),
        end_date=session.isoformat(),
        provider="fmp_cached",
    )
    return result.results or ()


def _fetch_delisted(_session: date) -> Iterable[object]:
    from openbb_core.app.service.user_service import UserService
    from openbb_fmp_cached.models.w5_w6_w8_extras import (
        FMPCachedDelistedCompaniesFetcher,
    )

    credentials = UserService().default_user_settings.credentials.model_dump(
        mode="json"
    )
    return asyncio.run(FMPCachedDelistedCompaniesFetcher.fetch_data({}, credentials))


def _configured_halts(_session: date) -> Iterable[object]:
    return [
        {"symbol": symbol}
        for symbol in os.environ.get("PI_TECHTRADE_HALTED_SYMBOLS", "").split(",")
        if symbol.strip()
    ]


_PUBLIC_EVENT_RISK = PublicEventRiskProvider(
    earnings_fetcher=_fetch_earnings,
    delisted_fetcher=_fetch_delisted,
    halted_fetcher=_configured_halts,
)


def _segment_from_key(entity_key: str) -> str:
    key = canonical_key(entity_key)
    if not key.startswith("segment="):
        raise ValueError("TechTrade entity key must start with segment=")
    wanted = key.split("=", 1)[1]
    for segment in GICS_SECTOR_ETFS:
        if segment.casefold() == wanted:
            return segment
    raise ValueError("unknown TechTrade segment")


def _mover_rows(result: object, segment: str, session: date) -> list[dict[str, Any]]:
    materialized = _jsonable(result)
    groups = materialized if isinstance(materialized, list) else [materialized]
    rows: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise TypeError("mover result must contain JSON objects")
        group_segment = str(group.get("segment") or segment)
        group_session = str(group.get("as_of") or session.isoformat())
        movers = group.get("movers", [])
        if not isinstance(movers, list):
            raise TypeError("movers must be a list")
        for raw in movers:
            if not isinstance(raw, dict):
                raise TypeError("movers must contain JSON objects")
            row = dict(raw)
            row.setdefault("segment", group_segment)
            row.setdefault("as_of", group_session)
            rows.append(row)
    return rows


def _result_rows(result: object) -> list[dict[str, Any]]:
    materialized = _jsonable(result)
    if isinstance(materialized, dict) and "results" in materialized:
        materialized = materialized["results"]
    values = materialized if isinstance(materialized, list) else [materialized]
    if not all(isinstance(value, dict) for value in values):
        raise TypeError("snapshot result must contain JSON objects")
    return [dict(value) for value in values]


class TechTradeSnapshotAdapter:
    """Materialize one public TechTrade dataset for every configured segment."""

    def __init__(
        self,
        name: str,
        *,
        compute_fn: ComputeFunction,
        segments: Iterable[str] | None = None,
        calendar: str = DEFAULT_EXCHANGE_CALENDAR,
        event_fetcher: EventFetcher = _no_events,
        membership_fetcher: MembershipFetcher = _no_membership,
    ) -> None:
        if name not in TECHTRADE_DATASETS:
            raise ValueError("unknown TechTrade snapshot dataset")
        self.name = name
        self._compute_fn = compute_fn
        self._segments = tuple(GICS_SECTOR_ETFS if segments is None else segments)
        self._calendar = calendar
        self._event_fetcher = event_fetcher
        self._membership_fetcher = membership_fetcher
        for segment in self._segments:
            techtrade_entity_key(segment)

    def entity_keys(self) -> list[str]:
        """Return one canonical key per configured GICS segment."""
        return [techtrade_entity_key(segment) for segment in self._segments]

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        """Compute and envelope one segment without persistence side effects."""
        segment = _segment_from_key(entity_key)
        rows = _result_rows(self._compute_fn(segment, as_of_session))
        symbols = [
            str(row["symbol"]).strip().upper() for row in rows if row.get("symbol")
        ]
        events = list(self._event_fetcher(as_of_session, symbols))
        inactive = {
            event.symbol
            for event in events
            if event.kind in (EventKind.DELISTED, EventKind.HALTED)
        }
        earnings = sorted(
            {event.symbol for event in events if event.kind is EventKind.EARNINGS}
        )
        rows = [
            row
            for row in rows
            if str(row.get("symbol", "")).strip().upper() not in inactive
        ]
        membership = self._membership_fetcher(segment, as_of_session)
        membership_symbols: list[str] = []
        survivorship = "not-applicable"
        if self.name in SURVIVORSHIP_SENSITIVE_DATASETS:
            survivorship = SURVIVORSHIP_UNCORRECTED
            if (
                membership is not None
                and membership.as_of_session == as_of_session
                and membership.exchange_calendar == self._calendar
            ):
                membership_symbols = sorted(membership.symbols)
                member_set = set(membership_symbols)
                rows = [
                    row
                    for row in rows
                    if not row.get("symbol")
                    or str(row["symbol"]).strip().upper() in member_set
                ]
                survivorship = "corrected"
        event_inputs = [
            {"kind": event.kind.value, "symbol": event.symbol} for event in events
        ]
        payload = {
            "rows": rows,
            "segment": segment,
            "as_of_session": as_of_session.isoformat(),
            "exchange_calendar": self._calendar,
            "earnings_symbols": earnings,
            "excluded_symbols": sorted(inactive),
            "survivorship": survivorship,
            "universe_membership": membership_symbols,
        }
        return ComputedSnapshot(
            payload=payload,
            inputs={
                "dataset": self.name,
                "segment": segment,
                "session": as_of_session.isoformat(),
                "calendar": self._calendar,
                "events": event_inputs,
                "membership": membership_symbols,
                "rows": rows,
            },
            engine_version=_engine_version(),
            payload_schema_version="1",
            row_count=len(rows),
        )


class MoversSnapshotAdapter(TechTradeSnapshotAdapter):
    """Compute one `techtrade.movers` payload per configured GICS segment."""

    def __init__(
        self,
        *,
        segments: Iterable[str] | None = None,
        top_n: int = 10,
        calendar: str = DEFAULT_EXCHANGE_CALENDAR,
        mover_fetcher: MoverFetcher = list_movers,
        event_fetcher: EventFetcher = _PUBLIC_EVENT_RISK,
    ) -> None:
        def compute_movers(segment: str, session: date) -> list[dict[str, Any]]:
            result = mover_fetcher(
                segment=segment,
                metric="pct_change",
                top_n=top_n,
                as_of=session,
                calendar=calendar,
            )
            return _mover_rows(result, segment, session)

        super().__init__(
            "techtrade.movers",
            compute_fn=compute_movers,
            segments=segments,
            calendar=calendar,
            event_fetcher=event_fetcher,
        )
        self._top_n = top_n

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        """Compute movers and add the configured ranking limit to provenance."""
        computed = super().compute(entity_key, as_of_session)
        inputs_value = _jsonable(computed.inputs)
        if not isinstance(inputs_value, dict):
            raise TypeError("movers inputs must be a JSON object")
        inputs = dict(inputs_value)
        inputs["top_n"] = self._top_n
        return ComputedSnapshot(
            payload=computed.payload,
            inputs=inputs,
            engine_version=computed.engine_version,
            payload_schema_version=computed.payload_schema_version,
            row_count=computed.row_count,
        )


def _signals(segment: str, session: date) -> object:
    from openbb_techtrade.engine.signals import build_signals

    return build_signals(segment=segment, as_of=session)


def _plans(segment: str, session: date) -> list[TradePlan]:
    from openbb_techtrade.engine.plan import build_plans

    return build_plans(segment=segment, as_of=session)


def _orders(segment: str, session: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for plan in _result_rows(_plans(segment, session)):
        for order in plan.get("orders", []):
            row = dict(order)
            row.setdefault("symbol", plan.get("symbol"))
            row.setdefault("segment", segment)
            row.setdefault("as_of", session.isoformat())
            rows.append(row)
    return rows


def _simulations(segment: str, session: date) -> list[dict[str, Any]]:
    return _planned_trajectories(_plans(segment, session))


def _planned_trajectories(plans: Iterable[TradePlan]) -> list[dict[str, Any]]:
    """Build an explicit stop/entry/target P&L scenario for each plan."""
    rows: list[dict[str, Any]] = []
    for plan in plans:
        recommendation = plan.recommendation
        entry = float(recommendation.entry_price)
        quantity = float(plan.position_size)
        direction = -1.0 if recommendation.action == "SELL_SHORT" else 1.0
        for day, (scenario, price) in enumerate(
            (
                ("stop", float(recommendation.stop_price)),
                ("entry", entry),
                ("target", float(recommendation.target_price)),
            )
        ):
            rows.append(
                {
                    "symbol": plan.symbol,
                    "segment": plan.segment,
                    "day": day,
                    "scenario": scenario,
                    "price": price,
                    "pnl": round((price - entry) * quantity * direction, 8),
                }
            )
    return rows


def _validations(segment: str, session: date) -> list[dict[str, Any]]:
    from openbb_techtrade.validation.backtest_bridge import validate_plan

    rows: list[dict[str, Any]] = []
    for plan in _plans(segment, session):
        _updated, report = asyncio.run(validate_plan(plan))
        row = _jsonable(report)
        if not isinstance(row, dict):
            raise TypeError("validation result must be a JSON object")
        row.setdefault("symbol", plan.symbol)
        row.setdefault("segment", segment)
        rows.append(row)
    return rows


def _tuning(segment: str, session: date) -> object:
    from openbb_techtrade.tuning.tune_router import tune

    return asyncio.run(tune(segment=segment, as_of=session, persist=False)).results


def _audit(segment: str, session: date) -> list[dict[str, Any]]:
    return _audit_rows(_plans(segment, session), session)


def _audit_rows(plans: Iterable[TradePlan], session: date) -> list[dict[str, Any]]:
    """Compare planned target P&L with persisted forward simulation fills."""
    rows: list[dict[str, Any]] = []
    for plan in plans:
        recommendation = plan.recommendation
        quantity = float(plan.position_size)
        entry = float(recommendation.entry_price)
        direction = -1.0 if recommendation.action == "SELL_SHORT" else 1.0
        replay_pnl = (float(recommendation.target_price) - entry) * quantity * direction
        forward_pnl = 0.0
        for fill in plan.simulated_fills:
            cash_sign = 1.0 if fill.side in ("sell", "sell_short") else -1.0
            forward_pnl += cash_sign * float(fill.quantity) * float(fill.price) - float(
                fill.commission
            )
        notional = abs(entry * quantity)
        deviation_bps = (
            (forward_pnl - replay_pnl) / notional * 10_000 if notional else 0.0
        )
        rows.append(
            {
                "symbol": plan.symbol,
                "segment": plan.segment,
                "bar_date": session.isoformat(),
                "replay_pnl": round(replay_pnl, 8),
                "forward_pnl": round(forward_pnl, 8),
                "deviation_bps": round(deviation_bps, 8),
                "fill_count": len(plan.simulated_fills),
            }
        )
    return rows


class ScanSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize the cross-segment scan rows."""

    def __init__(
        self,
        *,
        segments: Iterable[str] | None = None,
        scan_fetcher: Callable[..., list[TradePlan]] | None = None,
        event_fetcher: EventFetcher = _PUBLIC_EVENT_RISK,
    ) -> None:
        from openbb_techtrade.engine.scan import scan_segments
        from openbb_techtrade.snapshots.models import plan_to_row

        fetcher = scan_fetcher or scan_segments
        cached_session: date | None = None
        cached_rows: dict[str, list[dict[str, Any]]] = {}

        def compute_scan(segment: str, session: date) -> list[dict[str, Any]]:
            nonlocal cached_session, cached_rows
            if cached_session != session:
                cached_rows = {}
                for plan in fetcher(as_of=session):
                    cached_rows.setdefault(plan.segment, []).append(plan_to_row(plan))
                cached_session = session
            return list(cached_rows.get(segment, ()))

        super().__init__(
            "techtrade.scan",
            compute_fn=compute_scan,
            segments=segments,
            event_fetcher=event_fetcher,
        )


class SignalsSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize ranked confluence signals."""

    def __init__(self) -> None:
        super().__init__(
            "techtrade.signals",
            compute_fn=_signals,
            event_fetcher=_PUBLIC_EVENT_RISK,
        )


class PlanSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize full trading plans."""

    def __init__(self) -> None:
        super().__init__(
            "techtrade.plan", compute_fn=_plans, event_fetcher=_PUBLIC_EVENT_RISK
        )


class OrdersSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize broker-ready order legs."""

    def __init__(self) -> None:
        super().__init__(
            "techtrade.orders", compute_fn=_orders, event_fetcher=_PUBLIC_EVENT_RISK
        )


class SimulateSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize available simulation fills."""

    def __init__(
        self,
        *,
        segments: Iterable[str] | None = None,
        plans_fetcher: Callable[[str, date], list[TradePlan]] = _plans,
        event_fetcher: EventFetcher = _PUBLIC_EVENT_RISK,
    ) -> None:
        super().__init__(
            "techtrade.simulate",
            compute_fn=lambda segment, session: _planned_trajectories(
                plans_fetcher(segment, session)
            ),
            segments=segments,
            event_fetcher=event_fetcher,
        )


class ValidateSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize validation reports with survivorship labeling."""

    def __init__(self) -> None:
        super().__init__(
            "techtrade.validate",
            compute_fn=_validations,
            event_fetcher=_PUBLIC_EVENT_RISK,
        )


class TuneSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize tuning reports with survivorship labeling."""

    def __init__(self) -> None:
        super().__init__(
            "techtrade.tune", compute_fn=_tuning, event_fetcher=_PUBLIC_EVENT_RISK
        )


class AuditSnapshotAdapter(TechTradeSnapshotAdapter):
    """Materialize auditable plan-state rows."""

    def __init__(
        self,
        *,
        segments: Iterable[str] | None = None,
        plans_fetcher: Callable[[str, date], list[TradePlan]] = _plans,
        event_fetcher: EventFetcher = _PUBLIC_EVENT_RISK,
    ) -> None:
        super().__init__(
            "techtrade.audit",
            compute_fn=lambda segment, session: _audit_rows(
                plans_fetcher(segment, session), session
            ),
            segments=segments,
            event_fetcher=event_fetcher,
        )


def get_snapshot_adapters(
    *,
    segments: Iterable[str] | None = None,
    movers_top_n: int = 10,
) -> dict[str, TechTradeSnapshotAdapter]:
    """Return the installed TechTrade snapshot adapters by dataset name."""
    adapters: tuple[TechTradeSnapshotAdapter, ...] = (
        MoversSnapshotAdapter(segments=segments, top_n=movers_top_n),
        ScanSnapshotAdapter(segments=segments),
        SignalsSnapshotAdapter(),
        PlanSnapshotAdapter(),
        OrdersSnapshotAdapter(),
        SimulateSnapshotAdapter(),
        ValidateSnapshotAdapter(),
        TuneSnapshotAdapter(),
        AuditSnapshotAdapter(),
    )
    return {adapter.name: adapter for adapter in adapters}
