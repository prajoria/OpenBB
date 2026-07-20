"""Per-account single-writer lock manager (#547).

## Problem

Paper fill submission (:mod:`openbb_portfolio_intel.paper.fills`) performs:

    lot = position_store.get(account_id, symbol)     # (1) read
    new_lot = apply_fill(lot, fill_event)            # (2) compute
    position_store.put(account_id, new_lot)          # (3) write
    account_store.apply_cash_delta(account_id, delta) # (4) write

Steps (1)–(3) are not internally atomic — the position store's own
lock covers each of get/put individually, but two concurrent
submit_orders on the same account_id can interleave: T1 gets lot@10,
T2 gets lot@10, both compute their new lots on the STALE 10-share
base, both put — one lot write is silently lost.

Step (4) is atomic (:meth:`AccountStore.apply_cash_delta` runs the
sufficient-cash check + write under its own lock) but that doesn't
save (1)–(3).

## Solution — single-writer-per-account_id

This module ships an :class:`AccountLockManager` that provides one
:class:`threading.Lock` per ``account_id``. The fill engine acquires
the account_id's lock at the top of ``submit_order`` and releases it
after the last store write. Two concurrent submit_orders on the same
account serialize; different accounts run in parallel.

## Lock ordering (deadlock avoidance)

Only ONE lock is held per submit_order — the account_id lock. The
underlying store locks (``PositionStore._lock``, ``AccountStore._lock``)
are always acquired INSIDE the account lock and released before it,
so the total ordering is:

    account_lock(account_id) > store._lock

This is a strict tree (account_lock at the root, per-store leaves) so
no cycle is possible. Documented here + reinforced by
:mod:`test_race_hardening`.

## What this does NOT cover

- **Cross-account atomicity** — e.g. transferring cash between two
  paper accounts requires holding two account locks. This module
  provides ``acquire_both(a, b)`` which sorts the pair to enforce a
  consistent global ordering; callers MUST use that helper for
  multi-account operations to avoid deadlock.
- **Async / event-loop hosting** — the fill engine is synchronous today.
  When it moves to an asyncio host (#544 Fills v1 partials), swap
  :class:`threading.Lock` for :class:`asyncio.Lock` and re-audit.
- **Distributed / multi-process** — this is process-local. Producer
  hosts running many worker processes need a distributed lock
  (Redis, DynamoDB) or the MySQL binding's SELECT ... FOR UPDATE.
  Follow-up scope; the Protocol contract is unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Iterator


@dataclass
class AccountLockManager:
    """Thread-safe map from account_id -> per-account Lock.

    Locks are lazily allocated on first ``lock(account_id)`` call and
    kept alive for the manager's lifetime (accounts long-lived; small
    memory cost).
    """

    _locks: dict[str, Lock] = field(default_factory=dict)
    # Guards the _locks map itself. Held only briefly for lock lookup /
    # allocation; released before the per-account lock is acquired.
    _map_lock: Lock = field(default_factory=Lock)

    def _get_lock(self, account_id: str) -> Lock:
        """Lazily allocate the per-account lock."""
        with self._map_lock:
            lock = self._locks.get(account_id)
            if lock is None:
                lock = Lock()
                self._locks[account_id] = lock
            return lock

    @contextmanager
    def lock(self, account_id: str) -> Iterator[None]:
        """Hold the single-writer lock for ``account_id``.

        Usage::

            with lock_manager.lock(account_id):
                # (load lot, apply fill, write lot, cash delta) sequence
        """
        acquired = self._get_lock(account_id)
        acquired.acquire()
        try:
            yield
        finally:
            acquired.release()

    @contextmanager
    def acquire_both(
        self, account_id_a: str, account_id_b: str
    ) -> Iterator[None]:
        """Hold locks for TWO accounts in a canonical order.

        For multi-account operations (e.g. transferring cash between
        paper accounts). Sorts the pair so the total ordering across
        the whole process is consistent, avoiding deadlock cycles.

        If ``account_id_a == account_id_b`` a single lock is held.
        """
        if account_id_a == account_id_b:
            with self.lock(account_id_a):
                yield
            return
        first, second = sorted((account_id_a, account_id_b))
        with self.lock(first):
            with self.lock(second):
                yield


# Module-level default manager. Callers that want isolated locks
# (e.g. fresh per-test instances) construct their own AccountLockManager.
_DEFAULT_MANAGER: AccountLockManager | None = None


def default_lock_manager() -> AccountLockManager:
    """Return the process-wide default manager (lazily constructed)."""
    global _DEFAULT_MANAGER  # noqa: PLW0603
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = AccountLockManager()
    return _DEFAULT_MANAGER
