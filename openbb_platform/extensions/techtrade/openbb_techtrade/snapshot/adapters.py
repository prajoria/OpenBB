"""Compute adapters that materialize TechTrade results into EOD snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydantic import BaseModel

from openbb_techtrade.engine.movers import list_movers
from openbb_techtrade.engine.universe import GICS_SECTOR_ETFS
from openbb_techtrade.snapshot.datasets import (
    DEFAULT_EXCHANGE_CALENDAR,
    techtrade_entity_key,
)
from openbb_techtrade.snapshot.refresh import ComputedSnapshot
from openbb_techtrade.snapshot.store import canonical_key

MoverFetcher = Callable[..., object]
EventFetcher = Callable[[date, list[str]], Iterable["MarketEvent"]]


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
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("event symbol must be non-empty")
        object.__setattr__(self, "symbol", symbol)


def _no_events(_session: date, _symbols: list[str]) -> tuple[()]:
    return ()


def _engine_version() -> str:
    try:
        return version("openbb-techtrade")
    except PackageNotFoundError:  # pragma: no cover - editable installs normally exist
        return "source"


def _jsonable(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"snapshot value is not JSON-safe: {type(value).__name__}")


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


class MoversSnapshotAdapter:
    """Compute one `techtrade.movers` payload per configured GICS segment."""

    name = "techtrade.movers"

    def __init__(
        self,
        *,
        segments: Iterable[str] = GICS_SECTOR_ETFS,
        top_n: int = 10,
        calendar: str = DEFAULT_EXCHANGE_CALENDAR,
        mover_fetcher: MoverFetcher = list_movers,
        event_fetcher: EventFetcher = _no_events,
    ) -> None:
        self._segments = tuple(segments)
        self._top_n = top_n
        self._calendar = calendar
        self._mover_fetcher = mover_fetcher
        self._event_fetcher = event_fetcher
        for segment in self._segments:
            techtrade_entity_key(segment)

    def entity_keys(self) -> list[str]:
        return [techtrade_entity_key(segment) for segment in self._segments]

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        segment = _segment_from_key(entity_key)
        result = self._mover_fetcher(
            segment=segment,
            metric="pct_change",
            top_n=self._top_n,
            as_of=as_of_session,
            calendar=self._calendar,
        )
        rows = _mover_rows(result, segment, as_of_session)
        symbols = [
            str(row["symbol"]).strip().upper()
            for row in rows
            if row.get("symbol")
        ]
        events = list(self._event_fetcher(as_of_session, symbols))
        inactive = {
            event.symbol
            for event in events
            if event.kind in (EventKind.DELISTED, EventKind.HALTED)
        }
        earnings = sorted(
            {
                event.symbol
                for event in events
                if event.kind is EventKind.EARNINGS
            }
        )
        rows = [
            row
            for row in rows
            if str(row.get("symbol", "")).strip().upper() not in inactive
        ]
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
            "survivorship": "not-applicable",
        }
        return ComputedSnapshot(
            payload=payload,
            inputs={
                "dataset": self.name,
                "segment": segment,
                "session": as_of_session.isoformat(),
                "top_n": self._top_n,
                "calendar": self._calendar,
                "events": event_inputs,
                "rows": rows,
            },
            engine_version=_engine_version(),
            payload_schema_version="1",
            row_count=len(rows),
        )


def get_snapshot_adapters() -> dict[str, MoversSnapshotAdapter]:
    """Return the installed TechTrade snapshot adapters by dataset name."""
    adapter = MoversSnapshotAdapter()
    return {adapter.name: adapter}
