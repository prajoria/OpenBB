"""Event calendar merge + Smart-Money aggregator (#537, #538).

Two closely-related aggregation utilities that turn per-provider event
streams into unified portfolio-wide timelines:

- **event_calendar** (#537): merge earnings, dividends, splits, IPOs
  from separate provider feeds into one deduplicated, chronologically-
  sorted timeline scoped to a portfolio's symbols.

- **smart_money** (#538): aggregate insider transactions, 13F filings,
  and senate disclosures into per-symbol "smart money" scores for
  overlay display alongside portfolio positions.

Both operate on plain dataclasses (no I/O) so the fmp_cached / SEC
provider work (parked pending API-key session) can wire in independently.
"""

# pylint: disable=too-few-public-methods

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

# ---------------------------------------------------------------------------
# Event Calendar (#537)
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Recognized corporate-action / calendar event types."""

    EARNINGS = "earnings"
    DIVIDEND = "dividend"
    SPLIT = "split"
    IPO = "ipo"


@dataclass(frozen=True)
class CalendarEvent:
    """Single calendar entry — one symbol, one date, one type.

    ``source`` records which provider fed it (e.g. "fmp_cached",
    "sec"). Useful for de-duplication when the same event lands via
    multiple sources.
    """

    symbol: str
    date: date
    event_type: EventType
    source: str
    details: dict = field(default_factory=dict)  # optional per-type payload


def merge_event_calendars(
    portfolio_symbols: set[str],
    *feeds: Iterable[CalendarEvent],
) -> list[CalendarEvent]:
    """Merge multiple event feeds into one chronologically-sorted timeline.

    Deduplication key: ``(symbol, date, event_type)``. When multiple
    sources report the same event, the FIRST one seen wins (feed order
    matters — pass authoritative source first).

    Parameters
    ----------
    portfolio_symbols : set[str]
        Only events for these symbols are kept. Missing => scoped
        specifically to the portfolio being viewed.
    *feeds : Iterable[CalendarEvent]
        One iterable per provider feed. Order matters for dedup:
        earlier feed wins on a collision.

    Returns
    -------
    list[CalendarEvent]
        Chronologically sorted by ``date`` then ``symbol``.
    """
    seen: set[tuple[str, date, EventType]] = set()
    kept: list[CalendarEvent] = []
    for feed in feeds:
        for event in feed:
            if event.symbol not in portfolio_symbols:
                continue
            key = (event.symbol, event.date, event.event_type)
            if key in seen:
                continue
            seen.add(key)
            kept.append(event)
    kept.sort(key=lambda e: (e.date, e.symbol, e.event_type.value))
    return kept


def events_by_symbol(
    events: Iterable[CalendarEvent],
) -> dict[str, list[CalendarEvent]]:
    """Group a merged timeline by symbol for per-holding widgets."""
    grouped: dict[str, list[CalendarEvent]] = defaultdict(list)
    for event in events:
        grouped[event.symbol].append(event)
    return dict(grouped)


# ---------------------------------------------------------------------------
# Smart-Money Aggregator (#538)
# ---------------------------------------------------------------------------


class SmartMoneySource(str, Enum):
    """Recognized smart-money data sources."""

    INSIDER = "insider"  # SEC Form 4 insider transactions
    FORM_13F = "form_13f"  # SEC 13F institutional holdings
    SENATE = "senate"  # US Senate financial disclosures


@dataclass(frozen=True)
class SmartMoneySignal:
    """Single directional signal from a smart-money source.

    ``direction`` is +1 (buy/increase) or -1 (sell/decrease); 0 for
    disclosures that don't imply direction (e.g. a hold).
    ``weight`` is the source-specific magnitude; interpretation is
    source-dependent (dollar value, share count, etc.). Callers
    normalize before aggregation.
    """

    symbol: str
    source: SmartMoneySource
    direction: int  # +1, 0, -1
    weight: Decimal  # source-normalized magnitude


@dataclass
class SmartMoneyScore:
    """Aggregated per-symbol smart-money view.

    ``composite`` is the signed sum of direction * weight across all
    sources. Sign indicates net smart-money sentiment; magnitude
    indicates conviction (sum of contributing weights).
    """

    symbol: str
    composite: Decimal
    by_source: dict[SmartMoneySource, Decimal] = field(default_factory=dict)
    signal_count: int = 0


def aggregate_smart_money(
    signals: Iterable[SmartMoneySignal],
    portfolio_symbols: set[str] | None = None,
) -> dict[str, SmartMoneyScore]:
    """Aggregate signals into per-symbol scores.

    Parameters
    ----------
    signals : Iterable[SmartMoneySignal]
        Signals from any mix of sources.
    portfolio_symbols : set[str] | None
        If provided, only symbols in this set produce output.
        None = return scores for every symbol with at least one signal.

    Returns
    -------
    dict[str, SmartMoneyScore]
        Symbol → aggregated score. Symbols with zero net signal
        (direction * weight sums to 0) still appear if any signal
        contributed.
    """
    by_symbol: dict[str, SmartMoneyScore] = {}
    for sig in signals:
        if portfolio_symbols is not None and sig.symbol not in portfolio_symbols:
            continue
        score = by_symbol.setdefault(
            sig.symbol, SmartMoneyScore(symbol=sig.symbol, composite=Decimal("0"))
        )
        contribution = Decimal(sig.direction) * sig.weight
        score.composite += contribution
        score.by_source[sig.source] = (
            score.by_source.get(sig.source, Decimal("0")) + contribution
        )
        score.signal_count += 1
    return by_symbol


def top_conviction(
    scores: dict[str, SmartMoneyScore],
    n: int = 10,
    absolute: bool = True,
) -> list[SmartMoneyScore]:
    """Return the top-N scores by composite magnitude.

    Parameters
    ----------
    scores : dict[str, SmartMoneyScore]
        Output of aggregate_smart_money().
    n : int
        How many to return.
    absolute : bool
        True (default): rank by |composite| — highest conviction either
        direction. False: rank by signed composite — most-bullish first.
    """
    key = (lambda s: abs(s.composite)) if absolute else (lambda s: s.composite)
    return sorted(scores.values(), key=key, reverse=True)[:n]
