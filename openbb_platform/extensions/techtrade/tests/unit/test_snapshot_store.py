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
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from openbb_techtrade.snapshot import store as store_module
from openbb_techtrade.snapshot.store import (
    FIELD_MAX_LENGTHS,
    RetentionPolicy,
    SnapshotFieldTooLong,
    SnapshotRow,
    SnapshotState,
    SnapshotStatus,
    SqliteSnapshotStore,
    ValidationResult,
    canonical_key,
    default_validator,
    get_default_snapshot_store,
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


def _promotion_candidate(
    *,
    validated: bool,
    state: SnapshotState = SnapshotState.STAGING,
    status: SnapshotStatus = SnapshotStatus.OK,
) -> SnapshotRow:
    """Build a candidate row for ``_promotion_refusal`` branch tests."""
    return SnapshotRow(
        dataset="techtrade.movers",
        entity_key="sector=technology",
        as_of_session=date(2026, 9, 4),
        created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        job_run_id="run-1",
        status=status,
        state=state,
        payload={"rows": [{"symbol": "AAPL"}]},
        row_count=1,
        validated=validated,
    )


def test_promotion_refusal_distinguishes_missing_from_unvalidated_candidate() -> None:
    """Each ``_promotion_refusal`` branch reports its own, discriminating reason.

    Regression test for PR #2062 review feedback: a missing candidate
    (``None``, e.g. a stale/wrong ``job_run_id``) used to be reported with
    the same "candidate is not validated" reason as a candidate row that
    genuinely exists but hasn't passed validation, which made the
    promotion-refusal log misleading. The two cases must now be
    distinguishable.
    """
    live_ok = _promotion_candidate(validated=True, state=SnapshotState.LIVE)

    # 1. No candidate row at all: a not-found reason, not "not validated".
    assert (
        store_module._promotion_refusal(None, None) == "candidate snapshot not found"
    )

    # 2. Candidate exists but was never validated: distinct reason from (1).
    unvalidated = _promotion_candidate(validated=False)
    assert (
        store_module._promotion_refusal(unvalidated, None)
        == "candidate is not validated"
    )

    # 3. Validated but no longer STAGING (already promoted/superseded).
    superseded = _promotion_candidate(validated=True, state=SnapshotState.SUPERSEDED)
    assert (
        store_module._promotion_refusal(superseded, None)
        == "candidate is not in STAGING state"
    )

    # 4. Validated, STAGING, but ranked worse than the incumbent LIVE row.
    worse_candidate = _promotion_candidate(validated=True, status=SnapshotStatus.PARTIAL)
    assert (
        store_module._promotion_refusal(worse_candidate, live_ok)
        == "candidate status is worse than LIVE"
    )

    # 5. A fully eligible candidate is allowed through (no refusal).
    good_candidate = _promotion_candidate(validated=True)
    assert store_module._promotion_refusal(good_candidate, None) is None


# --- Task 2: SQLite lifecycle -------------------------------------------

_job_run_ids = itertools.count(1)


def _stage(  # pylint: disable=too-many-arguments
    store: SqliteSnapshotStore,
    *,
    payload: dict,
    dataset: str = "techtrade.movers",
    entity_key: str = "sector=technology",
    as_of_session: date = date(2026, 9, 4),
    job_run_id: str | None = None,
    status: SnapshotStatus = SnapshotStatus.OK,
    input_hash: str | None = None,
    engine_version: str | None = None,
    payload_schema_version: str | None = None,
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
        engine_version=engine_version,
        payload_schema_version=payload_schema_version,
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
            "INSERT INTO pi_eod_snapshot ("
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
    other.close()
    store.close()


def test_revalidating_an_unchanged_verdict_is_not_reported_as_a_race(
    tmp_path, caplog
) -> None:
    """Invariant: an idempotent re-validate succeeds on both backends.

    Re-running the gate over a row that already carries the identical
    verdict rewrites nothing. sqlite3's ``rowcount`` counts rows
    *matched* so it would report 1 here, but the MySQL backend's PyMySQL
    driver counts rows *changed* and reports 0 — so a rowcount-based
    race check answers differently per dialect for the same history.
    Both backends therefore decide the race by re-reading the row inside
    the write transaction, and this test pins the shared answer.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        again = store.validate(*staged)

    assert again.ok is True, again.reason
    assert "changed" not in again.reason.lower()
    assert not [r for r in caplog.records if "refused" in r.getMessage()]

    history = store.list_history("techtrade.movers", "sector=technology")
    assert [(r.state, r.validated) for r in history] == [(SnapshotState.STAGING, True)]
    store.close()


def test_revalidating_a_reversed_verdict_still_persists(tmp_path) -> None:
    """The idempotency fix must not swallow a genuinely changed verdict."""
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok

    def _reject(row: SnapshotRow) -> ValidationResult:
        del row
        return ValidationResult(ok=False, reason="stale-vendor-feed")

    result = store.validate(*staged, validator=_reject)
    assert result.ok is False
    assert result.reason == "stale-vendor-feed"

    history = store.list_history("techtrade.movers", "sector=technology")
    assert history[0].validated is False
    assert history[0].validation_reason == "stale-vendor-feed"
    store.close()


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
    store.close()


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
                "UPDATE pi_eod_snapshot SET state = ? WHERE job_run_id = ?",
                (SnapshotState.SUPERSEDED.value, incumbent[3]),
            )
            store._conn.execute(  # noqa: SLF001
                "UPDATE pi_eod_snapshot SET state = ? WHERE job_run_id = ?",
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
    store.close()


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
                "UPDATE pi_eod_snapshot SET state = ? WHERE job_run_id = ?",
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
    store.close()


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
                "INSERT INTO pi_eod_snapshot ("
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
    store.close()


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
                "UPDATE pi_eod_snapshot SET state = ? WHERE job_run_id = ?",
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
    store.close()


# ---------------------------------------------------------------------------
# Bounded identifier/provenance fields (review finding 2)
# ---------------------------------------------------------------------------
#
# SQLite ignores declared column widths; MySQL does not. The limits are
# therefore enforced in shared Python before either dialect is reached, so
# a call that this backend accepts is a call the MySQL backend accepts too.
# The mirror of these assertions lives in `test_mysql_snapshot_store.py`.


@pytest.mark.parametrize("field", sorted(FIELD_MAX_LENGTHS))
def test_stage_refuses_an_over_long_bounded_field(tmp_path, field: str) -> None:
    """Every bounded field is checked, and nothing is written."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    try:
        limit = FIELD_MAX_LENGTHS[field]
        with pytest.raises(SnapshotFieldTooLong) as excinfo:
            _stage(
                store,
                payload={"rows": [{"symbol": "AAPL"}]},
                **{field: "y" * (limit + 1)},
            )
        message = str(excinfo.value)
        assert field in message
        assert str(limit) in message
        assert str(limit + 1) in message
        assert excinfo.value.field_name == field
        assert excinfo.value.limit == limit
        assert excinfo.value.length == limit + 1
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM pi_eod_snapshot"
        ).fetchone()
        assert rows[0] == 0
    finally:
        store.close()


@pytest.mark.parametrize("field", sorted(FIELD_MAX_LENGTHS))
def test_stage_accepts_a_bounded_field_at_exactly_the_limit(
    tmp_path, field: str
) -> None:
    """The boundary is inclusive, and the full value round-trips."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    try:
        value = "z" * FIELD_MAX_LENGTHS[field]
        dataset, entity_key, _, _ = _stage(
            store, payload={"rows": [{"symbol": "AAPL"}]}, **{field: value}
        )
        history = store.list_history(dataset, entity_key)
        assert len(history) == 1
        assert getattr(history[0], field) == value
    finally:
        store.close()


def test_bounded_lengths_are_measured_after_canonicalization(tmp_path) -> None:
    """The stored value is the canonical one, so that is what is measured."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    try:
        padded = "  " + "k" * FIELD_MAX_LENGTHS["entity_key"] + "  "
        assert len(padded) > FIELD_MAX_LENGTHS["entity_key"]
        dataset, entity_key, _, _ = _stage(
            store, payload={"rows": [{"symbol": "AAPL"}]}, entity_key=padded
        )
        history = store.list_history(dataset, entity_key)
        assert len(history) == 1
        assert history[0].entity_key == canonical_key(padded)
    finally:
        store.close()


def test_restamp_live_inherits_the_length_guard(tmp_path) -> None:
    """`restamp_live` writes a new row, so it is bounded by the same rule.

    It reaches the table through `stage()`, so a guard placed anywhere
    else (in the caller, say) would leave this path unprotected.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    try:
        staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
        assert store.validate(*staged).ok
        assert store.promote(*staged)

        too_long = "r" * (FIELD_MAX_LENGTHS["job_run_id"] + 1)
        with pytest.raises(SnapshotFieldTooLong):
            store.restamp_live(
                "techtrade.movers", "sector=technology", date(2026, 9, 5), too_long
            )
        live = store.get_live("techtrade.movers", "sector=technology")
        assert live is not None
        assert live.as_of_session == date(2026, 9, 4)
    finally:
        store.close()


def test_a_long_validation_reason_is_persisted_whole(tmp_path) -> None:
    """A validator may say as much as it needs to; nothing is cut off."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    try:
        reason = "row-level mismatch: " + ", ".join(f"AAPL{n}" for n in range(300))
        assert len(reason) > 512

        def _reject(row: SnapshotRow) -> ValidationResult:
            del row
            return ValidationResult(ok=False, reason=reason)

        staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
        result = store.validate(*staged, validator=_reject)

        assert result.ok is False
        assert result.reason == reason
        history = store.list_history(staged[0], staged[1])
        assert history[0].validation_reason == reason
    finally:
        store.close()


# ---------------------------------------------------------------------------
# get_default_snapshot_store — env-var driven backend selection (#1963 Task 5)
# ---------------------------------------------------------------------------
#
# Mirrors execution.paper_engine's `TestFactory` suite: an env var picks the
# backend, MySQL is the default, and a MySQL-unreachable server degrades to
# SQLite with a WARNING instead of raising. `_make_mysql_store` is patched
# on `store_module` (never a real connection pool) so these tests need no
# live MySQL server and stay hermetic.


def _raise_connection_error() -> None:
    raise ConnectionError("could not connect to MySQL host")


def test_selector_uses_sqlite_when_requested(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "sqlite")
    store = get_default_snapshot_store(tmp_path / "snapshot.db")
    assert isinstance(store, SqliteSnapshotStore)
    store.close()


def test_mysql_failure_warns_and_falls_back(monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    monkeypatch.setenv("PI_SNAPSHOT_DB", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = get_default_snapshot_store()
    assert isinstance(store, SqliteSnapshotStore)
    assert "falling back to SQLite" in caplog.text
    store.close()


def test_mysql_failure_warning_reports_the_db_path_argument(
    monkeypatch, tmp_path, caplog
) -> None:
    """The WARNING must name the *actual* path opened, not a hardcoded one.

    Regression test for a review finding: the WARNING text used to
    hardcode ``~/.portfolio_intel/snapshot.db`` even when an explicit
    ``db_path`` argument (or ``$PI_SNAPSHOT_DB``) resolved to a
    completely different location — so an operator debugging a MySQL
    outage would be told the wrong file to inspect.
    """
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    # An unrelated env var is set to prove the *argument* wins the
    # precedence race and is the path the WARNING must report.
    monkeypatch.setenv("PI_SNAPSHOT_DB", str(tmp_path / "should-not-be-reported.db"))
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    arg_target = tmp_path / "arg-resolved.db"
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = get_default_snapshot_store(arg_target)
    assert isinstance(store, SqliteSnapshotStore)
    assert "falling back to SQLite" in caplog.text
    assert str(arg_target) in caplog.text
    assert "should-not-be-reported.db" not in caplog.text
    store.close()


def test_mysql_failure_warning_reports_the_env_db_path_when_arg_omitted(
    monkeypatch, tmp_path, caplog
) -> None:
    """Same guarantee as above, but resolved via ``$PI_SNAPSHOT_DB``."""
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    env_target = tmp_path / "env-resolved.db"
    monkeypatch.setenv("PI_SNAPSHOT_DB", str(env_target))
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = get_default_snapshot_store()
    assert isinstance(store, SqliteSnapshotStore)
    assert "falling back to SQLite" in caplog.text
    assert str(env_target) in caplog.text
    store.close()


def test_env_db_path_tilde_expands_to_the_real_home_dir_and_matches_the_warning(
    monkeypatch, tmp_path, caplog
) -> None:
    """Regression: a literal ``~`` in ``$PI_SNAPSHOT_DB`` must expand.

    Before this fix, ``get_default_snapshot_store`` built ``resolved``
    with a bare ``Path(...)`` and never called ``expanduser()``.
    ``Path.resolve()`` does *not* expand ``~`` -- it treats it as an
    ordinary path segment -- so a caller-configured ``~/...`` path would
    have been reported in the WARNING (and eventually opened by
    ``SqliteSnapshotStore``) as a literal ``~`` directory under the
    current working directory rather than the caller's actual home
    directory. Reverse-verified: dropping ``.expanduser()`` from the
    single normalization point in ``get_default_snapshot_store`` makes
    both assertions below fail -- the opened DB lands under a literal
    ``~`` segment instead of ``fake_home``, and the WARNING names that
    same wrong path.

    ``expanduser()`` resolves ``~`` via ``$HOME``/``$USERPROFILE`` (POSIX
    / Windows respectively), not via ``Path.home()``, so both are set.
    """
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    monkeypatch.setenv("PI_SNAPSHOT_DB", "~/.portfolio_intel/snapshot.db")
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    expected = (fake_home / ".portfolio_intel" / "snapshot.db").resolve()

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = get_default_snapshot_store()
    try:
        assert isinstance(store, SqliteSnapshotStore)
        assert store._db_path == expected  # noqa: SLF001
        # The WARNING must name the same expanded path the store opened,
        # never the literal, un-expanded "~/..." argument.
        assert str(expected) in caplog.text
        assert "~" not in caplog.text
    finally:
        store.close()


def test_explicit_tilde_db_path_argument_also_expands(monkeypatch, tmp_path) -> None:
    """The same normalization applies to the ``db_path`` argument, not just the env var."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "sqlite")

    store = get_default_snapshot_store("~/argument-resolved/snapshot.db")
    try:
        expected = (fake_home / "argument-resolved" / "snapshot.db").resolve()
        assert store._db_path == expected  # noqa: SLF001
        assert expected.exists()
        assert not (
            Path.cwd() / "~"
        ).exists(), "a literal '~' directory must never be created under cwd"
    finally:
        store.close()


def test_direct_constructor_tilde_db_path_expands_and_never_creates_literal_tilde_dir(
    monkeypatch, tmp_path
) -> None:
    """``SqliteSnapshotStore(...)`` itself must expand ``~``, not just the factory.

    Regression/discriminator: :func:`get_default_snapshot_store` normalizes
    its ``resolved`` path with ``expanduser().resolve()`` before ever
    constructing a :class:`SqliteSnapshotStore`, but a caller that
    constructs ``SqliteSnapshotStore`` *directly* — skipping the factory
    entirely — used to reach a bare ``Path(db_path).resolve()`` in
    ``__init__``. ``Path.resolve()`` does not expand ``~``; it treats it
    as an ordinary path segment relative to the current working
    directory. So a direct-constructor call with a ``~/...`` path used to
    silently create a literal directory named ``~`` under cwd instead of
    opening the database under the caller's real home directory.

    This test constructs ``SqliteSnapshotStore`` directly (never touching
    ``get_default_snapshot_store``), so it only passes if the
    normalization lives in ``SqliteSnapshotStore.__init__`` itself.
    Reverse-verified: reverting ``__init__`` to ``Path(db_path).resolve()``
    makes both assertions below fail — the store opens under a literal
    ``cwd/~/...`` path instead of ``fake_home``, and a literal ``~``
    directory is left behind under cwd.
    """
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    expected = (fake_home / "direct-ctor" / "snapshot.db").resolve()
    store = SqliteSnapshotStore(Path("~/direct-ctor/snapshot.db"))
    try:
        assert store._db_path == expected  # noqa: SLF001
        assert expected.exists()
        assert not (
            cwd / "~"
        ).exists(), "a literal '~' directory must never be created under cwd"
    finally:
        store.close()


def test_mysql_failure_warning_reports_the_per_user_default_path(
    monkeypatch, caplog
) -> None:
    """With no arg and no env var, the WARNING must name the real default."""
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    monkeypatch.delenv("PI_SNAPSHOT_DB", raising=False)
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    expected_default = (
        (Path.home() / ".portfolio_intel" / "snapshot.db").expanduser().resolve()
    )
    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = get_default_snapshot_store()
    try:
        assert isinstance(store, SqliteSnapshotStore)
        assert "falling back to SQLite" in caplog.text
        assert str(expected_default) in caplog.text
    finally:
        store.close()


def test_selector_rejects_unrecognized_engine_value(monkeypatch) -> None:
    """An unsupported ``PI_SNAPSHOT_ENGINE`` value must fail loudly.

    Regression test for a review finding: the selector used to treat
    anything other than the literal string ``"mysql"`` as an implicit
    request for SQLite, so a typo like ``PI_SNAPSHOT_ENGINE=postgres``
    silently opened the SQLite fallback instead of surfacing the
    misconfiguration.
    """
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "postgres")
    with pytest.raises(ValueError, match="PI_SNAPSHOT_ENGINE"):
        get_default_snapshot_store()


def test_selector_rejects_unrecognized_engine_value_does_not_touch_sqlite(
    monkeypatch, tmp_path
) -> None:
    """The loud rejection must happen before any SQLite file is created."""
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "typo-value")
    never_created = tmp_path / "should-never-exist.db"
    with pytest.raises(ValueError):
        get_default_snapshot_store(never_created)
    assert not never_created.exists()


def test_selector_defaults_to_mysql_and_returns_the_constructed_store(
    monkeypatch,
) -> None:
    """Invariant: with no env var set, the mysql path runs — not sqlite.

    Patches `_make_mysql_store` to hand back a sentinel object (never a
    real pool) and asserts the selector returns it unwrapped, proving both
    that MySQL is the default backend and that a successful construction
    is passed straight through rather than re-derived.
    """
    monkeypatch.delenv("PI_SNAPSHOT_ENGINE", raising=False)
    sentinel = object()
    monkeypatch.setattr(store_module, "_make_mysql_store", lambda: sentinel)
    store = get_default_snapshot_store()
    assert store is sentinel


def test_selector_sqlite_arg_overrides_env_db_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "sqlite")
    monkeypatch.setenv("PI_SNAPSHOT_DB", "/nonexistent/should-not-be-used.db")
    arg_target = tmp_path / "arg.db"
    store = get_default_snapshot_store(arg_target)
    store.close()
    assert arg_target.exists()
    assert not Path("/nonexistent/should-not-be-used.db").exists()


def test_selector_mysql_fallback_uses_env_db_path_when_arg_omitted(
    monkeypatch, tmp_path
) -> None:
    fallback_target = tmp_path / "fallback.db"
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    monkeypatch.setenv("PI_SNAPSHOT_DB", str(fallback_target))
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)
    store = get_default_snapshot_store()
    store.close()
    assert fallback_target.exists()


def test_selector_does_not_swallow_sqlite_construction_errors(
    monkeypatch, tmp_path
) -> None:
    """The MySQL-unreachable guard must not widen to cover SQLite too."""
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "sqlite")

    def _broken_sqlite(db_path):
        del db_path
        raise ValueError("sqlite construction exploded")

    monkeypatch.setattr(store_module, "SqliteSnapshotStore", _broken_sqlite)
    with pytest.raises(ValueError, match="sqlite construction exploded"):
        get_default_snapshot_store(tmp_path / "snapshot.db")


def test_mysql_fallback_does_not_swallow_subsequent_sqlite_construction_errors(
    monkeypatch, tmp_path
) -> None:
    """A broken fallback must still raise, not disappear behind the warning."""
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "mysql")
    monkeypatch.setenv("PI_SNAPSHOT_DB", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(store_module, "_make_mysql_store", _raise_connection_error)

    def _broken_sqlite(db_path):
        del db_path
        raise ValueError("sqlite construction exploded")

    monkeypatch.setattr(store_module, "SqliteSnapshotStore", _broken_sqlite)
    with pytest.raises(ValueError, match="sqlite construction exploded"):
        get_default_snapshot_store()


def test_get_default_snapshot_store_persists_a_promoted_row_across_reopen(
    monkeypatch, tmp_path
) -> None:
    """Acceptance (#1963 Task 5 Step 5): the real SQLite path round-trips.

    Stage/validate/promote one synthetic non-personal row through the
    factory-selected store, close it, reopen via the same factory call,
    and confirm `get_live()` returns the persisted row with the same
    date, UTC timestamp, payload, and provenance.
    """
    db_path = tmp_path / "snapshot.db"
    monkeypatch.setenv("PI_SNAPSHOT_ENGINE", "sqlite")

    store = get_default_snapshot_store(db_path)
    staged = _stage(
        store,
        dataset="techtrade.movers",
        entity_key="sector=technology",
        as_of_session=date(2026, 9, 4),
        job_run_id="run-acceptance-1",
        payload={"rows": [{"symbol": "AAPL", "close": 227.5}]},
    )
    assert store.validate(*staged).ok
    assert store.promote(*staged)
    store.close()

    reopened = get_default_snapshot_store(db_path)
    live = reopened.get_live("techtrade.movers", "sector=technology")
    reopened.close()

    assert live is not None
    assert live.as_of_session == date(2026, 9, 4)
    assert live.created_at.tzinfo is not None
    assert live.created_at.utcoffset().total_seconds() == 0
    assert live.payload == {"rows": [{"symbol": "AAPL", "close": 227.5}]}
    assert live.job_run_id == "run-acceptance-1"
    assert live.dataset == "techtrade.movers"
    assert live.entity_key == "sector=technology"
    assert live.state == SnapshotState.LIVE


# ---------------------------------------------------------------------------
# Schema identity + versioning (#1963 review C1 / I1)
# ---------------------------------------------------------------------------
#
# `CREATE TABLE IF NOT EXISTS` is a *no-op* against a pre-existing table of
# any shape. That is the mechanism that would have let the original
# `pi_snapshot` name silently absorb the account-scoped positions table the
# portfolio importer ships into the same database, leaving a store that
# constructs cleanly and fails every later call. The table is now namespaced,
# and an existing table of the wrong shape (or a table stamped by a different
# schema version) fails loudly at construction instead.

_FOREIGN_TABLE = """
CREATE TABLE pi_eod_snapshot (
    snapshot_id    TEXT PRIMARY KEY,
    snapshot_date  TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    source_sha256  TEXT NOT NULL
)
"""


def test_sqlite_refuses_a_foreign_table_of_the_same_name(tmp_path) -> None:
    """A table of our name that is not our table must fail at construction.

    Without the shape check the store constructs, the selector's MySQL
    fallback never fires, and every `stage`/`get_live` dies deep inside
    the lifecycle with "no such column: dataset".
    """
    db_path = tmp_path / "snapshot.db"
    seeded = sqlite3.connect(str(db_path))
    seeded.executescript(_FOREIGN_TABLE)
    seeded.close()

    with pytest.raises(store_module.SnapshotSchemaMismatch) as excinfo:
        SqliteSnapshotStore(db_path)

    message = str(excinfo.value)
    assert "pi_eod_snapshot" in message
    # The operator is told *which* columns are missing, not just "bad table".
    assert "dataset" in message
    assert "payload_json" in message


def test_sqlite_stamps_and_accepts_its_own_schema_version(tmp_path) -> None:
    db_path = tmp_path / "snapshot.db"
    store = SqliteSnapshotStore(db_path)
    stamped = store._conn.execute("PRAGMA user_version").fetchone()[0]  # noqa: SLF001
    store.close()

    assert stamped == store_module.SNAPSHOT_SCHEMA_VERSION
    # Reopening the file it just stamped must not be read as a mismatch.
    reopened = SqliteSnapshotStore(db_path)
    reopened.close()


def test_sqlite_refuses_a_table_stamped_by_another_schema_version(tmp_path) -> None:
    """A forward-version file is refused rather than silently downgraded.

    The shape check alone cannot catch #1964/#1967 *adding* columns: the
    table would still be a superset of what this build expects. The
    version stamp is what makes that case loud in the other direction.
    """
    db_path = tmp_path / "snapshot.db"
    SqliteSnapshotStore(db_path).close()
    bumped = sqlite3.connect(str(db_path))
    bumped.execute(f"PRAGMA user_version = {store_module.SNAPSHOT_SCHEMA_VERSION + 7}")
    bumped.close()

    with pytest.raises(store_module.SnapshotSchemaMismatch, match="schema"):
        SqliteSnapshotStore(db_path)


# ---------------------------------------------------------------------------
# Thread safety (#1963 review C2 / security Alert 1; design spec 4.6)
# ---------------------------------------------------------------------------
#
# The connection is opened `check_same_thread=False` and sqlite3
# transactions are *connection*-scoped, so two threads inside `_tx()` share
# one transaction: thread B's `BEGIN IMMEDIATE` raises "cannot start a
# transaction within a transaction", and its rollback aborts thread A's
# in-flight transaction — splitting promote()'s demote/promote pair into
# separately committed statements. Spec 4.6 makes the module-level `RLock`
# binding; these tests are what make it load-bearing.


def _promote_in_threads(store, staged, monkeypatch, *, workers: int):
    """Fire `workers` concurrent promotes with a widened read->write window."""
    real_refusal = store_module._promotion_refusal  # noqa: SLF001

    def _slow(candidate, live):
        verdict = real_refusal(candidate, live)
        # Hold the transaction open across a GIL switch so a second
        # thread genuinely arrives *inside* the first one's `_tx()`.
        time.sleep(0.02)
        return verdict

    monkeypatch.setattr(store_module, "_promotion_refusal", _slow)

    barrier = threading.Barrier(workers)
    results: list[bool] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _worker(target) -> None:
        barrier.wait()
        try:
            outcome = store.promote(*target)
        except BaseException as exc:  # noqa: BLE001 - the point of the test
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_worker, args=(one,)) for one in staged]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "a promote deadlocked"
    return results, errors


def test_concurrent_promotes_from_many_threads_keep_exactly_one_live_row(
    tmp_path, monkeypatch
) -> None:
    """Invariant: a shared connection never splits promote()'s two writes.

    Reverse-verified: with `_SQLITE_LOCK` removed from `_tx()`, the
    workers raise `OperationalError: cannot start a transaction within a
    transaction` and the LIVE-row count assertion fails.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    staged = [
        _stage(
            store,
            payload={"rows": [{"symbol": f"SYM{index}"}]},
            as_of_session=date(2026, 9, 2) + timedelta(days=index),
        )
        for index in range(6)
    ]
    for one in staged:
        assert store.validate(*one).ok

    results, errors = _promote_in_threads(store, staged, monkeypatch, workers=6)

    assert not errors, f"a concurrent promote raised: {errors!r}"
    # Serialized promotes all succeed: every candidate is validated, in
    # STAGING, and ranks equal to the incumbent.
    assert results == [True] * len(staged)

    live_rows = store._conn.execute(  # noqa: SLF001
        "SELECT job_run_id FROM pi_eod_snapshot WHERE state = 'live'"
    ).fetchall()
    assert len(live_rows) == 1, "the single-LIVE invariant was broken by threading"
    staging_rows = store._conn.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM pi_eod_snapshot WHERE state = 'staging'"
    ).fetchone()[0]
    assert staging_rows == 0, "a promotion was lost between the two writes"
    store.close()


def test_reads_from_another_thread_are_serialized_against_a_write(
    tmp_path, monkeypatch
) -> None:
    """A reader thread must never observe a half-applied promotion.

    The demote and the promote are two statements on one connection. A
    reader sharing that connection sees its *uncommitted* intermediate
    state unless it is serialized behind the writer, so a naive reader
    would find zero LIVE rows for a key that has one.
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

    observed: list[str | None] = []
    started = threading.Event()
    real_demote = SqliteSnapshotStore._demote  # noqa: SLF001

    def _reader() -> None:
        started.wait(timeout=10)
        live = store.get_live("techtrade.movers", "sector=technology")
        observed.append(None if live is None else live.job_run_id)

    def _demote_then_pause(self, dataset, entity_key, live):
        real_demote(self, dataset, entity_key, live)
        started.set()
        # The window between the demote and the promote: exactly the
        # interval in which the key transiently has no LIVE row.
        time.sleep(0.05)

    monkeypatch.setattr(SqliteSnapshotStore, "_demote", _demote_then_pause)
    reader = threading.Thread(target=_reader)
    reader.start()
    assert store.promote(*mine)
    reader.join(timeout=30)
    assert not reader.is_alive(), "the reader deadlocked against the writer"

    assert observed == [mine[3]], (
        "the reader saw the inside of the promotion transaction "
        f"(observed={observed!r})"
    )
    store.close()


# ---------------------------------------------------------------------------
# WAL + busy timeout (#1963 review I6)
# ---------------------------------------------------------------------------


def test_store_opens_the_file_in_wal_mode_with_a_busy_timeout(tmp_path) -> None:
    """Cross-process reads must not fail while the EOD writer holds a lock.

    In rollback-journal mode a reader arriving during a writer's
    `BEGIN IMMEDIATE` raises `database is locked` — out of the read path
    safeguard #9 promises is always available.

    The timeout is asserted against the module's own constant, not
    against "some positive number": `sqlite3.connect` already defaults
    to 5 s, so a `>= 1000` assertion would pass with the PRAGMA deleted
    (reverse-verified - it did).
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    journal = store._conn.execute("PRAGMA journal_mode").fetchone()[0]  # noqa: SLF001
    timeout = store._conn.execute("PRAGMA busy_timeout").fetchone()[0]  # noqa: SLF001
    store.close()

    assert str(journal).lower() == "wal"
    assert timeout == store_module._SQLITE_BUSY_TIMEOUT_MS  # noqa: SLF001
    assert timeout > 5000, "must exceed sqlite3.connect's own 5 s default"


def test_a_separate_process_style_reader_is_not_locked_out_by_a_writer(
    tmp_path,
) -> None:
    """Discriminating: an *independent* connection reads during a write tx.

    `_SQLITE_LOCK` cannot help here — the reader does not share the
    store's connection, exactly like the Terminal reading the file the
    EOD job is writing. Only WAL keeps it from raising.
    """
    db_path = tmp_path / "snapshots.db"
    store = SqliteSnapshotStore(db_path)
    staged = _stage(store, payload={"rows": [{"symbol": "AAPL"}]})
    assert store.validate(*staged).ok
    assert store.promote(*staged)

    reader = sqlite3.connect(str(db_path), timeout=0.2)
    try:
        store._conn.execute("BEGIN IMMEDIATE")  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "UPDATE pi_eod_snapshot SET validation_reason = 'in-flight' "
            "WHERE job_run_id = ?",
            (staged[3],),
        )
        rows = reader.execute(
            "SELECT state, validation_reason FROM pi_eod_snapshot"
        ).fetchall()
        store._conn.execute("ROLLBACK")  # noqa: SLF001
    finally:
        reader.close()

    assert rows == [("live", "")], "the reader saw uncommitted or no data"
    store.close()


# ---------------------------------------------------------------------------
# Transaction-scope error handling (#1963 review M1)
# ---------------------------------------------------------------------------


def test_a_failing_begin_is_not_masked_by_the_rollback(tmp_path) -> None:
    """The error the caller sees must be the one that actually happened.

    An unconditional `ROLLBACK` in `_tx()`'s handler raises its own
    `OperationalError` when no transaction is open - displacing the
    original. `promote()` *classifies* the exception it catches, so a
    displaced `IntegrityError` turns a documented `False` into a raw
    driver traceback.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")

    class _RefusesBegin:
        """Connection proxy whose ``BEGIN`` fails like a locked database."""

        def __init__(self, conn) -> None:
            self._conn = conn

        def execute(self, sql, *args, **kwargs):
            if sql.upper().startswith("BEGIN"):
                raise sqlite3.OperationalError("database is locked")
            return self._conn.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    store._conn = _RefusesBegin(store._conn)  # noqa: SLF001

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        store.stage(
            "techtrade.movers",
            "sector=technology",
            date(2026, 9, 4),
            "run-masked",
            {"rows": []},
        )
    store.close()


# ---------------------------------------------------------------------------
# Input validation (#1963 review M2 / M3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("keep_sessions", [-1, -50])
def test_a_negative_retention_window_is_refused(keep_sessions: int) -> None:
    """`keep_sessions=-1` is a slice bound, not a smaller window.

    `sessions[:-1]` silently means "delete only the *oldest* session" —
    the near-inverse of the caller's intent.
    """
    with pytest.raises(ValueError, match="keep_sessions"):
        RetentionPolicy(keep_sessions=keep_sessions)


@pytest.mark.parametrize("limit", [0, -1])
def test_a_non_positive_history_limit_is_refused(tmp_path, limit: int) -> None:
    """Parity: SQLite reads `LIMIT -1` as unlimited, MySQL rejects it."""
    store = SqliteSnapshotStore(tmp_path / "snapshots.db")
    with pytest.raises(ValueError, match="limit"):
        store.list_history("techtrade.movers", "sector=technology", limit=limit)
    store.close()


# ---------------------------------------------------------------------------
# restamp_live is pinned to the row it copied (#1963 review I2)
# ---------------------------------------------------------------------------
#
# `restamp_live` reads LIVE, then stages / validates / promotes in separate
# transactions. A genuine recompute promoting inside that window would be
# superseded by the copy of the *older* payload under a *newer* session
# date: LIVE goes backwards in content while going forwards in freshness.
# The rank guard cannot see it - the copy inherits the old row's status.


def _promote_a_real_recompute(db_path, *, symbol: str, as_of_session: date) -> str:
    """Play the competing writer: promote a genuinely new payload."""
    other = SqliteSnapshotStore(db_path)
    staged = _stage(
        other, payload={"rows": [{"symbol": symbol}]}, as_of_session=as_of_session
    )
    assert other.validate(*staged).ok
    assert other.promote(*staged)
    other.close()
    return staged[3]


def test_restamp_refuses_when_a_real_recompute_wins_the_race(tmp_path, caplog) -> None:
    """Invariant: a stale copy never supersedes newer content.

    Reverse-verified: with `_promote_expecting_live` reduced to a plain
    `promote()`, the restamp succeeds and LIVE reverts to the AAPL copy.
    """
    db_path = tmp_path / "snapshots.db"
    store = SqliteSnapshotStore(db_path)
    original = _stage(
        store, payload={"rows": [{"symbol": "AAPL"}]}, as_of_session=date(2026, 9, 3)
    )
    assert store.validate(*original).ok
    assert store.promote(*original)

    fired: list[str] = []
    real_stage = store.stage

    def _stage_then_recompute(*args, **kwargs):
        real_stage(*args, **kwargs)
        if not fired:
            # The window: the copy has been taken and staged, the
            # promote has not run yet.
            fired.append(
                _promote_a_real_recompute(
                    db_path, symbol="NVDA", as_of_session=date(2026, 9, 4)
                )
            )

    store.stage = _stage_then_recompute  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        restamped = store.restamp_live(
            "techtrade.movers", "sector=technology", date(2026, 9, 5), "run-restamp"
        )

    assert fired, "the interleaving hook never ran - test is inert"
    assert restamped is False
    assert [
        record
        for record in caplog.records
        if "promotion refused" in record.getMessage()
        and "real recompute" in record.getMessage()
    ], "the refusal must name the restamp race, not a generic rank refusal"

    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.job_run_id == fired[0]
    assert (
        live.payload["rows"][0]["symbol"] == "NVDA"
    ), "the restamp superseded a newer recompute with an older payload"
    assert live.as_of_session == date(2026, 9, 4)
    store.close()


def test_restamp_still_succeeds_when_live_does_not_move(tmp_path) -> None:
    """Guards the guard: the new gate must not refuse the ordinary path."""
    store = _live_store(tmp_path, input_hash="same-input")
    assert store.restamp_live(
        "techtrade.movers", "sector=technology", date(2026, 9, 6), "run-restamp"
    )
    live = store.get_live("techtrade.movers", "sector=technology")
    assert live is not None
    assert live.as_of_session == date(2026, 9, 6)
    assert live.job_run_id == "run-restamp"
    store.close()


# ---------------------------------------------------------------------------
# prune scoping and statement shape (#1963 review I4)
# ---------------------------------------------------------------------------


def _store_with_two_datasets(tmp_path) -> SqliteSnapshotStore:
    """Three sessions in each of two datasets; the newest is LIVE in both."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    for dataset in ("techtrade.movers", "techtrade.segments"):
        for symbol, as_of_session in (
            ("AAPL", date(2026, 9, 2)),
            ("MSFT", date(2026, 9, 3)),
            ("GOOG", date(2026, 9, 4)),
        ):
            staged = _stage(
                store,
                payload={"rows": [{"symbol": symbol}]},
                dataset=dataset,
                as_of_session=as_of_session,
            )
            assert store.validate(*staged).ok
            assert store.promote(*staged)
    return store


def test_scoped_prune_leaves_a_neighbouring_dataset_untouched(tmp_path) -> None:
    """Invariant: one caller's retention window is not everyone's.

    The store is shared. Without a scope, a `techtrade.movers` job's
    `keep_sessions=1` silently truncates `techtrade.segments` history it
    knows nothing about.
    """
    store = _store_with_two_datasets(tmp_path)

    removed = store.prune(RetentionPolicy(keep_sessions=1), dataset="techtrade.movers")

    assert removed == 2
    assert len(store.list_history("techtrade.movers", "sector=technology")) == 1
    assert len(store.list_history("techtrade.segments", "sector=technology")) == 3
    store.close()


def test_unscoped_prune_still_sweeps_every_dataset(tmp_path) -> None:
    """Guards the guard: the scope is opt-in, the janitor still works."""
    store = _store_with_two_datasets(tmp_path)
    assert store.prune(RetentionPolicy(keep_sessions=1)) == 4
    assert len(store.list_history("techtrade.movers", "sector=technology")) == 1
    assert len(store.list_history("techtrade.segments", "sector=technology")) == 1
    store.close()


def test_entity_scoped_prune_requires_its_dataset(tmp_path) -> None:
    """An `entity_key` is only unique inside a dataset."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    with pytest.raises(ValueError, match="requires dataset"):
        store.prune(RetentionPolicy(keep_sessions=1), entity_key="sector=technology")
    store.close()


def test_prune_scope_is_canonicalized_like_every_other_boundary(tmp_path) -> None:
    """A scope passed in non-canonical form must still match stored rows."""
    store = _store_with_two_datasets(tmp_path)
    assert (
        store.prune(
            RetentionPolicy(keep_sessions=1),
            dataset=" TechTrade.Movers ",
            entity_key="sector = Technology",
        )
        == 2
    )
    assert len(store.list_history("techtrade.movers", "sector=technology")) == 1
    assert len(store.list_history("techtrade.segments", "sector=technology")) == 3
    store.close()


def test_prune_is_set_based_not_a_round_trip_per_key(tmp_path) -> None:
    """Invariant: the write lock is held for a bounded number of statements.

    The shared table lives in the same database as the FMP cache, so a
    SELECT+DELETE pair per `(dataset, entity_key)` held that lock for
    O(#keys) round trips. One ranked SELECT plus batched DELETEs keeps
    it bounded regardless of how many keys are on file.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    for index in range(8):
        for as_of_session in (date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)):
            staged = _stage(
                store,
                payload={"rows": [{"symbol": "AAPL"}]},
                entity_key=f"sector=sector{index}",
                as_of_session=as_of_session,
            )
            assert store.validate(*staged).ok
            assert store.promote(*staged)

    seen: list[str] = []
    store._conn.set_trace_callback(seen.append)  # noqa: SLF001
    try:
        removed = store.prune(RetentionPolicy(keep_sessions=1))
    finally:
        store._conn.set_trace_callback(None)  # noqa: SLF001

    assert removed == 16
    selects = [sql for sql in seen if sql.lstrip().upper().startswith("SELECT")]
    deletes = [sql for sql in seen if sql.lstrip().upper().startswith("DELETE")]
    assert len(selects) == 1, f"one SELECT for the whole sweep, saw {len(selects)}"
    assert len(deletes) == 1, f"one batched DELETE for 8 keys, saw {len(deletes)}"
    store.close()


def test_prune_batches_a_sweep_larger_than_the_batch_size(tmp_path) -> None:
    """Bounded, not unbounded: a huge sweep becomes several DELETEs."""
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    doomed = [
        (f"techtrade.d{index}", "sector=technology", f"2026-09-{index % 28 + 1:02d}")
        for index in range(store_module._PRUNE_BATCH + 5)  # noqa: SLF001
    ]
    batches = list(store_module._batched(doomed))  # noqa: SLF001
    store.close()

    assert len(batches) == 2
    assert len(batches[0]) == store_module._PRUNE_BATCH  # noqa: SLF001
    assert len(batches[1]) == 5


# ---------------------------------------------------------------------------
# prune takes the write lock up front (#1963 whole-branch review)
# ---------------------------------------------------------------------------
#
# `prune()` is a read-decide-write sequence: one ranked `SELECT DISTINCT`
# picks the doomed `(dataset, entity_key, as_of_session)` triples, then the
# `DELETE`s remove them. A *deferred* `BEGIN` takes only a read snapshot at
# the SELECT, and in WAL mode another connection is free to commit inside
# that window — after which the DELETE cannot upgrade to a write lock and
# SQLite returns `SQLITE_BUSY_SNAPSHOT`, which the busy timeout
# deliberately does not retry because retrying it can never succeed. Every
# other read-decide-write scope in this backend already opens
# `BEGIN IMMEDIATE`; prune was the one that did not.


def test_prune_opens_its_transaction_with_begin_immediate(tmp_path) -> None:
    """The lock is taken before the ranking read, not after it."""
    store = _store_with_two_datasets(tmp_path)

    seen: list[str] = []
    store._conn.set_trace_callback(seen.append)  # noqa: SLF001
    try:
        assert store.prune(RetentionPolicy(keep_sessions=1)) == 4
    finally:
        store._conn.set_trace_callback(None)  # noqa: SLF001
    store.close()

    begins = [sql for sql in seen if sql.lstrip().upper().startswith("BEGIN")]
    assert begins == ["BEGIN IMMEDIATE"], (
        "prune opened a deferred transaction; its DELETE can then fail with "
        f"SQLITE_BUSY_SNAPSHOT after a concurrent commit. Saw {begins}"
    )


def test_prune_survives_a_writer_that_commits_between_its_read_and_delete(
    tmp_path,
) -> None:
    """Discriminating: the behavior the `IMMEDIATE` actually buys.

    An independent connection tries to commit in the window between
    prune's ranking `SELECT` and its `DELETE`. With the write lock
    already held, that writer is the one that is refused and prune
    completes. With a deferred `BEGIN`, prune holds only a WAL read
    snapshot, the outsider's commit succeeds, and prune's own DELETE
    then dies with `SQLITE_BUSY_SNAPSHOT` ("database is locked") — which
    the busy timeout never retries. Reverse-verified: with
    `immediate=True` removed, this test fails on that error.
    """
    store = _store_with_two_datasets(tmp_path)
    outsider = sqlite3.connect(str(store._db_path), timeout=0)  # noqa: SLF001
    intruded: list[BaseException | None] = []

    def _intrude(sql: str) -> None:
        # Fired at the start of the DELETE, i.e. after the ranking SELECT
        # has run — the exact window a deferred transaction leaves open.
        if intruded or not sql.lstrip().upper().startswith("DELETE"):
            return
        try:
            outsider.execute(
                "UPDATE pi_eod_snapshot SET validation_reason = 'outsider'"
            )
            outsider.commit()
            intruded.append(None)
        except sqlite3.OperationalError as exc:
            intruded.append(exc)

    store._conn.set_trace_callback(_intrude)  # noqa: SLF001
    try:
        removed = store.prune(RetentionPolicy(keep_sessions=1))
    finally:
        store._conn.set_trace_callback(None)  # noqa: SLF001
        outsider.close()

    assert intruded, "the interleaving hook never ran - the test is inert"
    assert intruded[0] is not None, (
        "the outsider committed inside prune's read -> delete window, which "
        "means prune never held the write lock"
    )
    assert removed == 4
    reasons = {
        row.validation_reason
        for row in store.list_history("techtrade.movers", "sector=technology")
    }
    assert reasons == {""}, "the locked-out writer's update landed anyway"
    store.close()


# ---------------------------------------------------------------------------
# close() is serialized like every other statement (#1963 whole-branch review)
# ---------------------------------------------------------------------------


def test_close_waits_for_an_in_flight_write_on_another_thread(tmp_path) -> None:
    """Closing a shared connection mid-transaction corrupts the writer.

    The connection is opened `check_same_thread=False`, so `close()` from
    a second thread lands in the middle of the first thread's open
    transaction: its next statement raises `sqlite3.ProgrammingError:
    Cannot operate on a closed database` and its half-written promote is
    reported as a programming bug rather than committed or rolled back.
    Holding `_SQLITE_LOCK` makes `close()` queue behind the write, like
    every other statement in this backend.
    """
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    entered = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []

    def _writer() -> None:
        try:
            with store._tx(immediate=True):  # noqa: SLF001
                entered.set()
                release.wait(5)
                store._conn.execute(  # noqa: SLF001
                    "INSERT INTO pi_eod_snapshot ("
                    "dataset, entity_key, as_of_session, created_at, job_run_id, "
                    "status, state, validated, validation_reason, payload_json"
                    ") VALUES ('d', 'e', '2026-09-04', '2026-09-04T00:00:00+00:00', "
                    "'run-x', 'ok', 'staging', 0, '', '{}')"
                )
        except BaseException as exc:  # noqa: BLE001 - the point of the test
            failures.append(exc)

    writer = threading.Thread(target=_writer)
    writer.start()
    assert entered.wait(5), "the writer never entered its transaction"
    closer = threading.Thread(target=store.close)
    closer.start()
    time.sleep(0.1)  # let close() reach the lock (or, unguarded, the close)
    release.set()
    writer.join(5)
    closer.join(5)

    assert failures == [], (
        "close() tore the connection out from under an open transaction on "
        f"another thread: {failures}"
    )


# ---------------------------------------------------------------------------
# `openbb_techtrade.snapshot` lazily imports the MySQL backend (#1963 review)
# ---------------------------------------------------------------------------
#
# `openbb-techtrade`'s pyproject.toml does not declare `openbb-fmp-cached` /
# PyMySQL as a hard dependency, so `snapshot/__init__.py` must not eagerly
# `from .mysql_store import MysqlSnapshotStore` at package-import time: doing
# so would make a SQLite-only install fail to even `import
# openbb_techtrade.snapshot`, before `get_default_snapshot_store()` ever gets
# a chance to fall back to `SqliteSnapshotStore`. `test_mysql_snapshot_store.py`
# imports `mysql_store` at collection time, which poisons `sys.modules` for
# the rest of this pytest session, so the regression is pinned via a fresh
# subprocess interpreter instead of an in-process check.


def test_snapshot_package_lazily_imports_the_mysql_backend() -> None:
    """Regression: importing the package must not import ``mysql_store``.

    Reverse-verified: reverting ``snapshot/__init__.py`` to a module-scope
    ``from .mysql_store import MysqlSnapshotStore`` makes the first
    assertion in the child script fail, because ``mysql_store`` would
    already be in ``sys.modules`` immediately after ``import
    openbb_techtrade.snapshot``.
    """
    script = (
        "import sys\n"
        "import openbb_techtrade.snapshot as snapshot\n"
        "assert 'openbb_techtrade.snapshot.mysql_store' not in sys.modules, (\n"
        "    'mysql_store must stay unimported until MysqlSnapshotStore is '\n"
        "    'actually accessed'\n"
        ")\n"
        "# The rest of the contract surface must be usable with no MySQL\n"
        "# backend loaded at all.\n"
        "assert snapshot.SqliteSnapshotStore is not None\n"
        "assert snapshot.get_default_snapshot_store is not None\n"
        "assert snapshot.canonical_key('sector=Technology') == 'sector=technology'\n"
        "snapshot.MysqlSnapshotStore  # first touch triggers the deferred import\n"
        "assert 'openbb_techtrade.snapshot.mysql_store' in sys.modules, (\n"
        "    'accessing MysqlSnapshotStore must trigger the deferred import'\n"
        ")\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("OK")


def test_snapshot_package_getattr_rejects_unknown_names() -> None:
    """The PEP 562 hook must only special-case ``MysqlSnapshotStore``."""
    from openbb_techtrade import (
        snapshot,
    )  # noqa: PLC0415 pylint: disable=import-outside-toplevel

    with pytest.raises(AttributeError, match="not_a_real_export"):
        snapshot.not_a_real_export  # noqa: B018 pylint: disable=pointless-statement


def test_snapshot_package_mysql_store_attribute_is_a_stable_identity() -> None:
    """Repeated access returns the same class object as a direct import."""
    from openbb_techtrade import (
        snapshot,
    )  # noqa: PLC0415 pylint: disable=import-outside-toplevel
    from openbb_techtrade.snapshot.mysql_store import (  # noqa: PLC0415 pylint: disable=import-outside-toplevel
        MysqlSnapshotStore,
    )

    assert snapshot.MysqlSnapshotStore is MysqlSnapshotStore
    # Second access resolves through the cached module attribute, not a
    # second `__getattr__` round trip -- still the identical class object.
    assert snapshot.MysqlSnapshotStore is MysqlSnapshotStore
