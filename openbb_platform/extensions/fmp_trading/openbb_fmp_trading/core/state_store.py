"""MySQL-backed persistent state for fmp_trading (P3.0 / D6).

Consolidated persistence for the two agent turns (P3.1 pre-open, P3.2
post-close) and their deterministic fallbacks. Reuses the ``fmp_cached``
MySQL connection rather than opening a second on-disk surface — one
credentials block, one backup path, one connection pool.

API surface — two layers:

* **Raw:** :func:`load_state` / :func:`save_state`. Payloads are any
  JSON-serializable ``Any``; the caller owns the shape.
* **Typed:** :func:`load_last_watchlist` / :func:`save_last_watchlist`,
  :func:`load_last_plan` / :func:`save_last_plan`. Validate on load per
  design-review A8; corrupt payloads return ``None`` and log ``WARN``
  rather than crashing the caller.

Resilience contract (matches P2.2 ``create_ttl_wrapper_class``):

* DB failure on ``SELECT`` -> return ``None``. Never raise. Marks "DB
  down," not "we have a bug."
* DB failure on ``UPSERT`` -> log at ``WARN``, suppress. Best-effort
  persistence — the caller continues with its in-memory value.
* **A7 (narrow except):** only ``pymysql.MySQLError`` and
  ``ConnectionError`` are caught. ``TypeError`` / ``ValueError`` /
  ``json.JSONDecodeError`` propagate so serialization bugs can't
  masquerade as "DB down."

The underlying MySQL table (``fmp_trading_state``) is defined in
``openbb_fmp_cached.utils.cache_schema.create_fmp_trading_state_table``
and registered in ``FLATTENED_TABLES``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# All DB access goes through the fmp_cached helpers so tests can patch
# them at the openbb_fmp_cached.utils.database module level (same
# pattern the P2.2 ttl-wrapper tests established).


def _db():
    """Return the (execute_query, execute_many) pair, imported lazily.

    Lazy import matters because tests patch these functions at their
    canonical location. If we imported at module load, monkeypatch
    against ``openbb_fmp_cached.utils.database`` wouldn't take effect
    inside ``state_store`` unless the test also patched here — pointless
    duplication.
    """
    from openbb_fmp_cached.utils.database import execute_many, execute_query
    return execute_query, execute_many


def _db_errors() -> tuple:
    """Narrow exception tuple caught by :func:`load_state` / :func:`save_state`.

    Contains only genuine DB / driver failures. Everything else — bad
    JSON, wrong types, programming bugs — propagates (A7).
    """
    import pymysql
    return (pymysql.MySQLError, ConnectionError)


# ---------------------------------------------------------------------------
# Raw layer — untyped Any payloads
# ---------------------------------------------------------------------------


def load_state(key: str, scope: str = "default") -> Any | None:
    """Return the deserialized payload for ``(key, scope)`` or ``None``.

    Returns ``None`` in three cases:
      1. The row is absent (never written).
      2. The DB is unavailable (``pymysql.MySQLError`` / ``ConnectionError``).

    Raises ``json.JSONDecodeError`` if the stored payload is corrupt —
    that's a bug worth surfacing, not silent ``None``.
    """
    execute_query, _ = _db()
    try:
        rows = execute_query(
            "SELECT payload FROM fmp_trading_state "
            "WHERE state_key = %s AND scope = %s",
            (key, scope),
        )
    except _db_errors() as exc:
        logger.warning(
            "state_store.load_state(%s, %s) DB failure: %s", key, scope, exc
        )
        return None
    if not rows:
        return None
    payload = rows[0]["payload"]
    # MySQL JSON columns come back as either str (needs decode) or a
    # native Python object depending on driver flags. Handle both.
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        return json.loads(payload)  # JSONDecodeError propagates — A7
    return payload


def save_state(key: str, payload: Any, scope: str = "default") -> None:
    """UPSERT ``payload`` as JSON. DB failure is logged + suppressed.

    ``TypeError`` from ``json.dumps`` on a non-serializable payload
    propagates — serialization bugs are caller bugs, not "DB down" (A7).
    """
    _, execute_many = _db()
    # json.dumps failures (TypeError on non-serializable) propagate — A7.
    serialized = json.dumps(payload, default=str)
    try:
        execute_many(
            """INSERT INTO fmp_trading_state (state_key, scope, payload)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 payload = VALUES(payload),
                 updated_at = CURRENT_TIMESTAMP""",
            [(key, scope, serialized)],
        )
    except _db_errors() as exc:
        logger.warning(
            "state_store.save_state(%s, %s) DB failure: %s", key, scope, exc
        )


# ---------------------------------------------------------------------------
# Typed convenience wrappers — validate-on-load per A8
# ---------------------------------------------------------------------------


def load_last_watchlist(scope: str = "default") -> list[str] | None:
    """Return the last committed watchlist as ``list[str]``, or ``None``.

    Corrupt payload (not a list, or contains non-strings) is treated as
    absent and logged at ``WARN``. Callers ("yesterday's watchlist"
    fallback in P3.1) can rely on the return being either ``None`` or a
    real, iterable list of strings.
    """
    payload = load_state("last_watchlist", scope)
    if payload is None:
        return None
    if not isinstance(payload, list) or not all(
        isinstance(s, str) for s in payload
    ):
        logger.warning(
            "state_store: last_watchlist corrupt payload shape "
            "(expected list[str]); treating as absent"
        )
        return None
    return payload


def save_last_watchlist(symbols: list[str], scope: str = "default") -> None:
    """Persist the day's watchlist. Called by P3.2 post-close after the
    turn commits, so tomorrow's P3.1 pre-open fallback can read it."""
    save_state("last_watchlist", list(symbols), scope)


def load_last_plan(scope: str = "default"):
    """Return the last committed ``DailyPlan``, or ``None``.

    Corrupt payload (fails ``DailyPlan.model_validate``) is treated as
    absent and logged at ``WARN``. Prevents a legacy or hand-edited row
    from crashing every subsequent pre-open turn.
    """
    from pydantic import ValidationError

    from openbb_fmp_trading.models.plan import DailyPlan

    payload = load_state("last_plan", scope)
    if payload is None:
        return None
    try:
        return DailyPlan.model_validate(payload)
    except ValidationError as exc:
        logger.warning("state_store: last_plan validation failed: %s", exc)
        return None


def save_last_plan(plan, scope: str = "default") -> None:
    """Persist the day's committed plan. Called by P3.2 post-close for
    post-mortem context + P3.1 pre-open prompt context."""
    save_state("last_plan", plan.model_dump(mode="json"), scope)


def load_last_session_summary(scope: str = "default") -> dict | None:
    """Return the last session summary dict (date, realized_pnl,
    veto_counts, ...), or ``None``.

    Kept as an untyped dict here rather than a pydantic model because
    the shape evolves faster than the other state keys — P3.1's prompt
    context builder consumes whatever fields exist.
    """
    payload = load_state("last_session_summary", scope)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "state_store: last_session_summary corrupt payload shape "
            "(expected dict); treating as absent"
        )
        return None
    return payload


def save_last_session_summary(summary: dict, scope: str = "default") -> None:
    """Persist the day's session summary. Called by P3.2 post-close."""
    save_state("last_session_summary", dict(summary), scope)


__all__ = [
    "load_last_plan",
    "load_last_session_summary",
    "load_last_watchlist",
    "load_state",
    "save_last_plan",
    "save_last_session_summary",
    "save_last_watchlist",
    "save_state",
]
