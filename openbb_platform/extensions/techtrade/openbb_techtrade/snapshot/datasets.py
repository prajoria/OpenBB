"""Dataset names, entity keys, and validation for TechTrade EOD snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date

from openbb_techtrade.engine.universe import GICS_SECTOR_ETFS
from openbb_techtrade.snapshot.semantics import (
    validate_calendar_name,
    validate_exchange_session,
)
from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    ValidationResult,
    canonical_key,
    default_validator,
)

TECHTRADE_DATASETS = (
    "techtrade.movers",
    "techtrade.scan",
    "techtrade.signals",
    "techtrade.plan",
    "techtrade.orders",
    "techtrade.simulate",
    "techtrade.validate",
    "techtrade.tune",
    "techtrade.audit",
)

SURVIVORSHIP_SENSITIVE_DATASETS = frozenset(
    {"techtrade.validate", "techtrade.tune", "techtrade.audit"}
)
SURVIVORSHIP_UNCORRECTED = "in-sample · survivorship-uncorrected"
DEFAULT_EXCHANGE_CALENDAR = "XNYS"
MIN_PREVIOUS_ROWS_FOR_RATIO = 5
MIN_PREVIOUS_ROW_RATIO = 0.70
_ROW_RATIO_DATASETS = frozenset({"techtrade.movers"})
_DATE_FIELDS = ("date", "bar_date", "as_of")
_EXACT_PRICE_FIELDS = frozenset({"price", "open", "high", "low", "close"})
_REQUIRED_PAYLOAD_FIELDS = frozenset(
    {"rows", "segment", "as_of_session", "exchange_calendar"}
)


def techtrade_entity_key(segment: str) -> str:
    """Return the canonical snapshot key for one supported GICS segment."""
    normalized = " ".join(segment.split())
    if normalized not in GICS_SECTOR_ETFS:
        raise ValueError("unknown TechTrade segment")
    return canonical_key(f"segment={normalized}")


def _price_field(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _EXACT_PRICE_FIELDS or lowered.endswith("_price")


def _validate_rows(rows: list[object]) -> ValidationResult:
    mappings: list[Mapping[str, object]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            return ValidationResult(False, "rows must contain JSON objects")
        mappings.append(item)

    if not mappings:
        return ValidationResult(True)

    columns = set().union(*(row.keys() for row in mappings))
    for column in sorted(columns):
        values = [row.get(column) for row in mappings]
        if all(value is None for value in values):
            return ValidationResult(False, f"all-null column: {column}")
        if _price_field(str(column)):
            for value in values:
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return ValidationResult(False, f"{column} must be numeric")
                if not math.isfinite(float(value)) or float(value) <= 0:
                    return ValidationResult(False, f"{column} must be positive")

    for field in _DATE_FIELDS:
        values = [row.get(field) for row in mappings if row.get(field) is not None]
        if not values:
            continue
        try:
            parsed = [date.fromisoformat(str(value)) for value in values]
        except ValueError:
            return ValidationResult(False, f"{field} must contain ISO dates")
        if parsed != sorted(parsed):
            return ValidationResult(False, f"{field} must be monotonic")

    return ValidationResult(True)


# pylint: disable=too-many-return-statements
def validate_techtrade_snapshot(  # noqa: PLR0911 - stable refusal reasons
    row: SnapshotRow, previous: SnapshotRow | None = None
) -> ValidationResult:
    """Apply the common TechTrade envelope and row sanity policy."""
    baseline = default_validator(row)
    if not baseline.ok:
        return baseline
    missing = sorted(_REQUIRED_PAYLOAD_FIELDS - row.payload.keys())
    if missing:
        return ValidationResult(False, f"missing metadata: {', '.join(missing)}")
    rows = row.payload["rows"]
    if not isinstance(rows, list):
        return ValidationResult(False, "rows must be a list")
    if row.row_count is not None and row.row_count != len(rows):
        return ValidationResult(False, "row_count does not match payload rows")
    try:
        payload_session = date.fromisoformat(str(row.payload["as_of_session"]))
    except ValueError:
        return ValidationResult(False, "as_of_session must be an ISO date")
    if payload_session != row.as_of_session:
        return ValidationResult(
            False, "payload session does not match snapshot session"
        )
    try:
        calendar_name = validate_calendar_name(str(row.payload["exchange_calendar"]))
        validate_exchange_session(payload_session, calendar_name)
    except ValueError as exc:
        return ValidationResult(False, str(exc))

    row_verdict = _validate_rows(rows)
    if not row_verdict.ok:
        return row_verdict

    previous_count = previous.row_count if previous is not None else None
    excluded_count = len(
        {
            str(symbol).strip().upper()
            for symbol in row.payload.get("excluded_symbols", [])
            if str(symbol).strip()
        }
    )
    if (
        row.dataset in _ROW_RATIO_DATASETS
        and previous_count is not None
        and previous_count >= MIN_PREVIOUS_ROWS_FOR_RATIO
        and len(rows) + excluded_count
        < math.ceil(previous_count * MIN_PREVIOUS_ROW_RATIO)
    ):
        return ValidationResult(False, "row_count is below 70% of previous LIVE")
    return ValidationResult(True)


# pylint: enable=too-many-return-statements
