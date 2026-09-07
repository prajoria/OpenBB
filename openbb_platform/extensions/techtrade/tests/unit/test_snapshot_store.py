"""Tests for the #1963 EOD snapshot store contract (Task 1-2).

Task 1 scope: the shared value types, ``canonical_key`` normalization, and
the baseline ``default_validator`` gate. Task 2 scope: the concrete
``SqliteSnapshotStore`` stage/validate/promote/get_live/get_as_of/
list_history lifecycle, including the keep-last-good rank guard, the
validated-before-promote gate, the DB-level single-LIVE-row unique index,
and read-boundary canonicalization. Task 3 scope: ``should_skip``
(idempotent-rerun detection), ``restamp_live`` (auditable session
re-stamping without recompute, atop the same stage/validate/promote path),
and ``prune`` (the ``RetentionPolicy`` hook — default keep-all, bounded
policy never removes LIVE rows). The MySQL backend is exercised by later
tasks (#1963 Task 4+); see the design spec
(``docs/superpowers/specs/2026-08-09-asof-snapshot-cache-and-alignment-design.md``
§3-4).
"""

# ruff: noqa: D101, D102, D103, D105, SLF001

from __future__ import annotations

import itertools
import logging
import sqlite3
from datetime import date, datetime, timezone

import pytest
from openbb_techtrade.snapshot import store as store_module
from openbb_techtrade.snapshot.store import (
    RetentionPolicy,
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SqliteSnapshotStore,
    ValidationResult,
    canonical_key,
    default_validator,
)


def _row(*, payload: dict, row_count: int | None = 0) -> SnapshotRow:
    """Build a minimal staged ``SnapshotRow`` for validator-only tests."""
    return SnapshotRow(
        dataset="techtrade.movers",
        entity_key="sector=technology",
        as_of_session=date(2026, 9, 4),
        created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        job_run_id="run-1",
        status=SnapshotStatus.OK,
        state=SnapshotState.STAGING,
        payload=payload,
        row_count=row_count,
    )


def test_canonical_key_is_idempotent_and_normalizes_label_pairs() -> None:
    canonical = canonical_key(" sector = Information_Technology ")
    assert canonical == "sector=information technology"
    assert canonical_key(canonical) == canonical


def test_default_validator_rejects_empty_payload_and_negative_rows() -> None:
    assert not default_validator(_row(payload={})).ok
    assert not default_validator(_row(payload={"rows": []}, row_count=-1)).ok
    assert default_validator(
        _row(payload={"rows": [{"symbol": "AAPL"}]}, row_count=1)
    ).ok


# --- Task 2: SQLite lifecycle -------------------------------------------

_job_run_ids = itertools.count(1)


def _stage(
    store: SqliteSnapshotStore,
    *,
    payload: dict,
    dataset: str = "techtrade.movers",
    entity_key: str = "sector=technology",
    as_of_session: date = date(2026, 9, 4),
    job_run_id: str | None = None,
    status: SnapshotStatus = SnapshotStatus.OK,
    input_hash: str | None = None,
) -> tuple[str, str, date, str]:
    """Stage a row; return the ``(dataset, entity_key, as_of_session, job_run_id)``.

    tuple that ``validate()``/``promote()`` expect via ``*staged`` unpacking.
    """
    job_run_id = job_run_id or f"run-{next(_job_run_ids)}"
    store.stage(
        dataset,
        entity_key,
        as_of_session,
        job_run_id,
        payload,
        status=status,
        input_hash=input_hash,
    )
    return (dataset, entity_key, as_of_session, job_run_id)


def test_fresh_store_has_no_live_snapshot(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.close()


def test_clean_stage_validate_promote_is_atomic(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(
        store, status=SnapshotStatus.OK, payload={"rows": [{"symbol": "AAPL"}]}
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.state == SnapshotState.LIVE
    # 12.3 #8: as_of_session is a plain date, created_at a tz-aware datetime;
    # `type(...) is date` (not isinstance) since datetime subclasses date.
    assert (
        type(live.as_of_session) is date
    )  # noqa: E721 pylint: disable=unidiomatic-typecheck
    assert isinstance(live.created_at, datetime)
    assert live.created_at.tzinfo is not None
    store.close()


def test_unvalidated_or_empty_stage_cannot_promote(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(store, payload={})
    assert not store.promote(*staged)
    assert not store.validate(*staged).ok
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.close()


def test_custom_validator_rejection_blocks_promotion(tmp_path) -> None:
    """Invariant: a caller-supplied ``validator=`` can refuse promotion."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason="too few rows for this caller")

    result = store.validate(*staged, validator=_reject)
    assert not result.ok
    assert result.reason == "too few rows for this caller"
    assert not store.promote(*staged)
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.close()


def test_partial_cannot_displace_ok(tmp_path) -> None:
    """Invariant: keep-last-good — PARTIAL never outranks a LIVE OK row."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    ok_staged = _stage(
        store, status=SnapshotStatus.OK, payload={"rows": [{"symbol": "AAPL"}]}
    )
    assert store.validate(*ok_staged).ok
    assert store.promote(*ok_staged)

    partial_staged = _stage(
        store,
        status=SnapshotStatus.PARTIAL,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 5),
    )
    assert store.validate(*partial_staged).ok
    assert not store.promote(*partial_staged)

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.job_run_id == ok_staged[3]
    store.close()


def test_newer_ok_supersedes_prior_ok_and_history_retains_both(tmp_path) -> None:
    """Invariant: a newer OK run displaces the LIVE OK row; history keeps both."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    first = _stage(
        store,
        status=SnapshotStatus.OK,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert store.validate(*first).ok
    assert store.promote(*first)

    second = _stage(
        store,
        status=SnapshotStatus.OK,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
    )
    assert store.validate(*second).ok
    assert store.promote(*second)

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "MSFT"
    assert live.job_run_id == second[3]

    history = store.list_history("techtrade.movers", "sector=technology")
    assert [row.job_run_id for row in history] == [second[3], first[3]]
    assert history[0].state == SnapshotState.LIVE
    assert history[1].state == SnapshotState.SUPERSEDED
    store.close()


def test_direct_second_live_insert_raises_integrity_error(tmp_path) -> None:
    """Invariant: the partial unique index blocks a second LIVE row at the DB layer."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(  # pylint: disable=protected-access
            "INSERT INTO pi_snapshot ("
            "dataset, entity_key, as_of_session, created_at, job_run_id, "
            "status, state, validated, validation_reason, payload_json, "
            "input_hash, row_count, engine_version, payload_schema_version"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', ?, NULL, NULL, NULL, NULL)",
            (
                "techtrade.movers",
                "sector=technology",
                date(2026, 9, 5).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                "run-direct-live",
                SnapshotStatus.OK.value,
                SnapshotState.LIVE.value,
                '{"rows": [{"symbol": "GOOG"}]}',
            ),
        )
    store.close()


def test_differently_formatted_keys_resolve_same_live_row(tmp_path) -> None:
    """Invariant: read-boundary canonicalization — split-brain keys collapse to one row.

    Both write and read keys are deliberately non-canonical and formatted
    *differently* from each other (extra whitespace, underscores, case) so
    this only passes if ``get_live`` canonicalizes its own arguments —
    reading with an already-canonical key would make this assertion
    ceremonial (CLAUDE.md R7: it would pass even with canonicalization
    removed from the read path).
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(
        store,
        entity_key="sector = Information_Technology",
        payload={"rows": [{"symbol": "AAPL"}]},
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    live = store.get_live("techtrade.movers", "sector=INFORMATION_technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    store.close()


def test_promote_refuses_candidate_not_in_staging_state(tmp_path) -> None:
    """Invariant: promote() must refuse a candidate whose row state is not STAGING.

    Prevents resurrecting a SUPERSEDED (or already-LIVE) row back to LIVE by
    calling promote() again with a stale staged-tuple, which would silently
    un-supersede history and displace the true current LIVE row.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    first = _stage(
        store,
        status=SnapshotStatus.OK,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
    )
    assert store.validate(*first).ok
    assert store.promote(*first)

    second = _stage(
        store,
        status=SnapshotStatus.OK,
        payload={"rows": [{"symbol": "MSFT"}]},
        as_of_session=date(2026, 9, 4),
    )
    assert store.validate(*second).ok
    assert store.promote(*second)

    # `first` is now SUPERSEDED. Re-promoting it must be refused, not
    # resurrect it as LIVE and re-supersede `second`.
    assert not store.promote(*first)

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == second[3]
    assert live.payload["rows"][0]["symbol"] == "MSFT"

    history = store.list_history("techtrade.movers", "sector=technology")
    states = {row.job_run_id: row.state for row in history}
    assert states[first[3]] == SnapshotState.SUPERSEDED
    assert states[second[3]] == SnapshotState.LIVE

    # Re-promoting the current LIVE row itself must also be refused.
    assert not store.promote(*second)
    store.close()


def test_validate_refuses_and_does_not_mutate_non_staging_row(tmp_path) -> None:
    """Invariant: validate() must not mutate a row whose state is not STAGING.

    Calling validate() again on an already-promoted (LIVE) row must return a
    failed ``ValidationResult`` and leave the row's persisted
    ``validated``/``validation_reason`` untouched — no silent rewrite of
    LIVE/SUPERSEDED history.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    live_before = store.get_live("techtrade.movers", "sector=technology")
    assert live_before is not None
    assert live_before.validated is True
    assert live_before.validation_reason == ""

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason="should never be persisted")

    result = store.validate(*staged, validator=_reject)
    assert not result.ok

    live_after = store.get_live("techtrade.movers", "sector=technology")
    assert live_after is not None
    assert live_after.validated is True
    assert live_after.validation_reason == ""
    assert live_after.state == SnapshotState.LIVE
    store.close()


def test_get_as_of_returns_promoted_row_for_given_session(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 4)
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    as_of = store.get_as_of("techtrade.movers", "sector=technology", date(2026, 9, 4))
    assert as_of is not None
    assert as_of.payload["rows"][0]["symbol"] == "AAPL"
    assert (
        store.get_as_of("techtrade.movers", "sector=technology", date(2026, 9, 1))
        is None
    )
    store.close()


# --- Task 3: idempotency, auditable restamping, and retention ------------


def _live_store(tmp_path, *, input_hash: str) -> SqliteSnapshotStore:
    """Build a store with one promoted LIVE row carrying ``input_hash``."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    staged = _stage(
        store,
        payload={"rows": [{"symbol": "AAPL"}]},
        as_of_session=date(2026, 9, 3),
        job_run_id="run-1",
        input_hash=input_hash,
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    return store


def _store_with_three_sessions(tmp_path) -> SqliteSnapshotStore:
    """Build a store with three promoted sessions for one key (newest is LIVE)."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    for offset, symbol in enumerate(["AAPL", "MSFT", "GOOG"]):
        staged = _stage(
            store,
            payload={"rows": [{"symbol": symbol}]},
            as_of_session=date(2026, 9, 2 + offset),
        )
        assert store.validate(*staged).ok
        assert store.promote(*staged)
    return store


def test_should_skip_is_false_with_no_live_row_or_mismatched_hash(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    assert not store.should_skip("techtrade.movers", "sector=technology", "any-hash")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]}, input_hash="hash-a")
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    assert not store.should_skip("techtrade.movers", "sector=technology", "hash-b")
    assert store.should_skip("techtrade.movers", "sector=technology", "hash-a")
    store.close()


def test_matching_input_hash_can_be_restamped_without_recompute(tmp_path) -> None:
    store = _live_store(tmp_path, input_hash="same-input")
    assert store.should_skip("techtrade.movers", "sector=technology", "same-input")
    assert store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 4), "run-2"
    )
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.as_of_session == date(2026, 9, 4)
    assert live.job_run_id == "run-2"
    assert live.payload["rows"][0]["symbol"] == "AAPL"
    assert live.input_hash == "same-input"

    history = store.list_history("techtrade.movers", "sector=technology")
    assert len(history) == 2
    # No in-place mutation: the prior row keeps its original session/state.
    superseded = next(row for row in history if row.job_run_id == "run-1")
    assert superseded.as_of_session == date(2026, 9, 3)
    assert superseded.state == SnapshotState.SUPERSEDED
    store.close()


def test_restamp_live_refuses_when_no_live_row_exists(tmp_path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    assert not store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 4), "run-2"
    )
    assert store.get_live("techtrade.movers", "sector=technology") is None
    store.close()


def test_default_prune_keeps_all_and_bounded_policy_preserves_live(tmp_path) -> None:
    store = _store_with_three_sessions(tmp_path)
    assert store.prune() == 0
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 2
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "GOOG"
    history = store.list_history("techtrade.movers", "sector=technology")
    assert len(history) == 1
    store.close()


def _store_with_out_of_order_live_session(tmp_path) -> SqliteSnapshotStore:
    """Build a store where LIVE's session is older than a SUPERSEDED one.

    Promotes three runs *out of session order* — 9/2, then 9/4, then 9/3 —
    so the final LIVE row (run-3, session 9/3) is older than the newest
    distinct session on file (run-2, session 9/4, now SUPERSEDED).
    ``promote()`` has no session-monotonicity requirement (only the
    status-rank keep-last-good guard), so this is a legitimate history a
    real restamp/backfill/replay sequence could produce, not a synthetic
    impossibility.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    for symbol, as_of_session in (
        ("AAPL", date(2026, 9, 2)),
        ("MSFT", date(2026, 9, 4)),
        ("GOOG", date(2026, 9, 3)),
    ):
        staged = _stage(
            store, payload={"rows": [{"symbol": symbol}]}, as_of_session=as_of_session
        )
        assert store.validate(*staged).ok
        assert store.promote(*staged)
    return store


def test_bounded_prune_preserves_live_when_its_session_predates_the_kept_window(
    tmp_path,
) -> None:
    """Discriminating regression test for the `state != LIVE` prune guard.

    LIVE (GOOG, session 9/3) is *not* the newest distinct session on file —
    MSFT's superseded 9/4 row is newer. With ``keep_sessions=1`` the
    newest-session window is ``{9/4}``, which does **not** contain LIVE's
    own session (9/3). A prune implementation that decided "keep" purely by
    session-window membership (ignoring ``state``) would delete the LIVE
    row here; the store's unconditional ``state != 'live'`` filter must
    keep it regardless.
    """
    store = _store_with_out_of_order_live_session(tmp_path)
    live_before = store.get_live("techtrade.movers", "sector=technology")
    assert live_before is not None
    assert live_before.as_of_session == date(2026, 9, 3)
    assert live_before.payload["rows"][0]["symbol"] == "GOOG"

    # Only AAPL (9/2, SUPERSEDED, outside the {9/4} keep window) is removed.
    # MSFT (9/4, SUPERSEDED) survives because its session is in the kept
    # window; GOOG (9/3, LIVE) survives despite its session being outside
    # the kept window, because LIVE rows are never pruned.
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 1

    live_after = store.get_live("techtrade.movers", "sector=technology")
    assert live_after is not None
    assert live_after.as_of_session == date(2026, 9, 3)
    assert live_after.job_run_id == live_before.job_run_id
    assert live_after.payload["rows"][0]["symbol"] == "GOOG"

    history = store.list_history("techtrade.movers", "sector=technology")
    assert {row.payload["rows"][0]["symbol"] for row in history} == {"GOOG", "MSFT"}
    assert len(history) == 2
    store.close()


# ---------------------------------------------------------------------------
# Concurrency: the read -> write window (review findings 1 and 2)
# ---------------------------------------------------------------------------
#
# SQLite has no row locks, so `promote()` opens its transaction with
# `BEGIN IMMEDIATE` (a database-wide write lock taken *before* the reads)
# and re-asserts the state it read in every WHERE clause. The two
# defences are tested separately: a second connection exercises the
# genuinely unlocked `validate()` window, while the `_promotion_refusal`
# seam injects a mutation into the middle of `promote()`'s transaction to
# prove the WHERE-clause predicates are load-bearing rather than
# decorative.

_STORE_LOGGER = "openbb_techtrade.snapshot.store"


def test_validate_refuses_when_the_row_leaves_staging_between_read_and_write(
    tmp_path, caplog
) -> None:
    """Race guard: a concurrent promotion must void an in-flight validate.

    `validate()` reads the row, runs the gate, then writes the verdict.
    A second connection promoting in that window must not end up with a
    rewritten `validated`/`validation_reason` on its LIVE row.
    """
    db_path = tmp_path / "snapshots.db"
    store = SqliteSnapshotStore(db_path)
    other = SqliteSnapshotStore(db_path)
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})

    def _forge(row: SnapshotRow) -> ValidationResult:
        del row
        assert other.validate(*staged).ok
        assert other.promote(*staged)
        return ValidationResult(ok=False, reason="forged-verdict")

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        result = store.validate(*staged, validator=_forge)

    assert result.ok is False
    assert "forged-verdict" not in result.reason
    assert "changed" in result.reason.lower()
    assert [r for r in caplog.records if "validation refused" in r.getMessage()]

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.state == SnapshotState.LIVE
    assert live.validated is True
    assert live.validation_reason == ""


def test_promote_takes_a_write_lock_before_reading_and_pins_what_it_read(
    tmp_path,
) -> None:
    """Invariant: promote serialises itself and re-asserts the rows it read.

    `BEGIN` (deferred) would let another writer commit between the reads
    and the writes; `BEGIN IMMEDIATE` closes that window on SQLite. The
    `state = ?` predicates are the second line of defence.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    seen: list[str] = []
    store._conn.set_trace_callback(seen.append)  # noqa: SLF001
    try:
        assert store.promote(*staged)
    finally:
        store._conn.set_trace_callback(None)  # noqa: SLF001

    # `set_trace_callback` reports *expanded* SQL, so the literals below
    # also prove which values were bound, not merely that a placeholder
    # existed.
    assert seen[0].strip().upper() == "BEGIN IMMEDIATE"
    selects = [sql for sql in seen if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2, "promote must read the candidate and the LIVE row"
    assert seen.index(selects[0]) > 0, "reads must happen inside the locked tx"

    promoting = [
        sql
        for sql in seen
        if sql.lstrip().upper().startswith("UPDATE") and "SET state = 'live'" in sql
    ]
    assert len(promoting) == 1
    assert (
        f"job_run_id = '{staged[3]}'" in promoting[0]
    ), "the promoting UPDATE must target one row by primary key"
    assert (
        "AND state = 'staging'" in promoting[0]
    ), "the promoting UPDATE must re-assert the state it read"


def test_promote_refuses_when_the_incumbent_live_row_moves_mid_transaction(
    tmp_path, caplog, monkeypatch
) -> None:
    """Race guard: never demote a LIVE row other than the one we read.

    Injected at the seam between promote's reads and its writes: the
    incumbent is superseded and a different row becomes LIVE. Demoting
    "whatever is LIVE now" would silently discard that newer snapshot
    and install ours instead.

    The injected swap shares this transaction, so the refusal rolls it
    back too — which is the point: a refused promotion leaves *nothing*
    half-applied. What must never happen is `mine` ending up LIVE.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    incumbent = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 3)
    )
    assert store.validate(*incumbent).ok
    assert store.promote(*incumbent)

    mine = _stage(
        store, payload={"rows": [{"symbol": "MSFT"}]}, as_of_session=date(2026, 9, 4)
    )
    theirs = _stage(
        store, payload={"rows": [{"symbol": "NVDA"}]}, as_of_session=date(2026, 9, 5)
    )
    assert store.validate(*mine).ok
    assert store.validate(*theirs).ok

    real_refusal = store_module._promotion_refusal  # noqa: SLF001
    fired: list[int] = []

    def _swap_live(candidate, live):
        verdict = real_refusal(candidate, live)
        if verdict is None and not fired:
            fired.append(1)
            store._conn.execute(  # noqa: SLF001
                "UPDATE pi_snapshot SET state = ? WHERE job_run_id = ?",
                (SnapshotState.SUPERSEDED.value, incumbent[3]),
            )
            store._conn.execute(  # noqa: SLF001
                "UPDATE pi_snapshot SET state = ? WHERE job_run_id = ?",
                (SnapshotState.LIVE.value, theirs[3]),
            )
        return verdict

    monkeypatch.setattr(store_module, "_promotion_refusal", _swap_live)
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        promoted = store.promote(*mine)

    assert fired, "the interleaving hook never ran - test is inert"
    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id != mine[3], "a refused promotion installed our row anyway"
    assert live.job_run_id == incumbent[3]
    states = {
        row.job_run_id: row.state
        for row in store.list_history("techtrade.movers", "sector=technology")
    }
    assert states[mine[3]] == SnapshotState.STAGING
    assert states[theirs[3]] == SnapshotState.STAGING


def test_promote_refuses_when_the_candidate_leaves_staging_mid_transaction(
    tmp_path, caplog, monkeypatch
) -> None:
    """Race guard: the promoting UPDATE must re-assert STAGING.

    If the candidate is no longer STAGING when the write lands, the
    transition already happened (or was invalidated) elsewhere and this
    caller must report `False` rather than claim it did the work.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    mine = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*mine).ok

    real_refusal = store_module._promotion_refusal  # noqa: SLF001
    fired: list[int] = []

    def _steal(candidate, live):
        verdict = real_refusal(candidate, live)
        if verdict is None and not fired:
            fired.append(1)
            store._conn.execute(  # noqa: SLF001
                "UPDATE pi_snapshot SET state = ? WHERE job_run_id = ?",
                (SnapshotState.SUPERSEDED.value, mine[3]),
            )
        return verdict

    monkeypatch.setattr(store_module, "_promotion_refusal", _steal)
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        promoted = store.promote(*mine)

    assert fired, "the interleaving hook never ran - test is inert"
    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]
    assert store.get_live("techtrade.movers", "sector=technology") is None


def test_promote_converts_a_live_key_collision_into_a_refusal(
    tmp_path, caplog, monkeypatch
) -> None:
    """Race guard: a unique-index collision surfaces as False, not a traceback.

    A writer bypassing `promote()` can install a LIVE row inside the
    window; the partial unique index then rejects ours. A boolean API
    must not make callers catch `sqlite3.IntegrityError`.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    mine = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*mine).ok

    real_refusal = store_module._promotion_refusal  # noqa: SLF001
    fired: list[int] = []

    def _outsider(candidate, live):
        verdict = real_refusal(candidate, live)
        if verdict is None and not fired:
            fired.append(1)
            store._conn.execute(  # noqa: SLF001
                "INSERT INTO pi_snapshot ("
                "dataset, entity_key, as_of_session, created_at, job_run_id, "
                "status, state, validated, validation_reason, payload_json, "
                "input_hash, row_count, engine_version, payload_schema_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', ?, NULL, NULL, NULL, NULL)",
                (
                    "techtrade.movers",
                    "sector=technology",
                    "2026-09-09",
                    "2026-09-09T12:00:00+00:00",
                    "run-outsider",
                    SnapshotStatus.OK.value,
                    SnapshotState.LIVE.value,
                    '{"rows": [{"symbol": "GOOG"}]}',
                ),
            )
        return verdict

    monkeypatch.setattr(store_module, "_promotion_refusal", _outsider)
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        promoted = store.promote(*mine)

    assert fired, "the interleaving hook never ran - test is inert"
    assert promoted is False
    assert [r for r in caplog.records if "promotion refused" in r.getMessage()]

    # The whole transaction, outsider row included, was rolled back.
    assert store.get_live("techtrade.movers", "sector=technology") is None
    remaining = {
        row.job_run_id
        for row in store.list_history("techtrade.movers", "sector=technology")
    }
    assert remaining == {mine[3]}


def test_promote_refuses_when_the_incumbent_live_row_vanishes_mid_transaction(
    tmp_path, caplog, monkeypatch
) -> None:
    """Race guard: "0 rows demoted" must abort, even with nothing in the way.

    No competing row takes over LIVE here, so the partial unique index
    never fires: the demotion's affected-row count is the only evidence
    that the incumbent this promotion was ranked against is gone.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    incumbent = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 3)
    )
    assert store.validate(*incumbent).ok
    assert store.promote(*incumbent)

    mine = _stage(
        store, payload={"rows": [{"symbol": "MSFT"}]}, as_of_session=date(2026, 9, 4)
    )
    assert store.validate(*mine).ok

    real_refusal = store_module._promotion_refusal  # noqa: SLF001
    fired: list[int] = []

    def _vanish(candidate, live):
        verdict = real_refusal(candidate, live)
        if verdict is None and not fired:
            fired.append(1)
            store._conn.execute(  # noqa: SLF001
                "UPDATE pi_snapshot SET state = ? WHERE job_run_id = ?",
                (SnapshotState.SUPERSEDED.value, incumbent[3]),
            )
        return verdict

    monkeypatch.setattr(store_module, "_promotion_refusal", _vanish)
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        promoted = store.promote(*mine)

    assert fired, "the interleaving hook never ran - test is inert"
    assert promoted is False
    assert [
        r
        for r in caplog.records
        if "promotion refused" in r.getMessage()
        and "LIVE row changed" in r.getMessage()
    ]
    states = {
        row.job_run_id: row.state
        for row in store.list_history("techtrade.movers", "sector=technology")
    }
    assert states[mine[3]] == SnapshotState.STAGING
