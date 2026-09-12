# MysqlPaperEngine Shared Pool Contract Design

**Issue:** #2059

## Purpose

Make `MysqlPaperEngine` use the shared
`openbb_fmp_cached.utils.database.ConnectionPool` according to its actual
PyMySQL contract. `get_connection()` returns a context manager that owns
connection cleanup, and its yielded connections default to autocommit.

## Constraints and success criteria

- Borrow every connection with `with pool.get_connection() as conn`.
- Never close a pooled connection directly from the engine.
- Start each write transaction explicitly with `conn.begin()` before any SQL.
- Commit successful write scopes and roll back failed write scopes.
- Keep read scopes non-transactional.
- Request bare PyMySQL cursors; do not pass mysql-connector arguments.
- Preserve all paper-engine semantics and leave the SQLite engine unchanged.
- Exercise the real `ConnectionPool` type without making a network connection.

## Considered approaches

### 1. Adapt `MysqlPaperEngine` to the shared pool contract (selected)

Delegate connection lifetime to the pool context manager and add explicit
transaction boundaries in `transaction()`. This is the smallest change, matches
`MysqlSnapshotStore`, and keeps one canonical database abstraction.

### 2. Add compatibility behavior to `ConnectionPool`

Return an object that acts as both a connection and a context manager. This
would preserve the engine's incorrect usage, but it would complicate a shared
provider utility and could conceal the same defect in future consumers.

### 3. Give the engine a private PyMySQL connection factory

This would make lifecycle and transactions explicit but duplicate credential,
connection, and cursor configuration already owned by `fmp_cached`.

## Design

`_acquire()` will enter `self._pool.get_connection()` and yield the connection
without closing it. `transaction()` will borrow through `_acquire()`, call
`conn.begin()` before yielding, commit only after the operation completes, and
roll back before re-raising any exception.

The existing operation boundaries remain unchanged:

- schema creation remains idempotent but is not atomic because MySQL DDL
  implicitly commits; account bootstrap uses a single no-op upsert so
  concurrent constructors preserve the first account seed without a
  check-then-insert race;
- order submission, fill processing, and cancellation each remain one atomic
  transaction;
- fill and cancellation transactions lock the order rows they validate, while
  fill side effects lock account, lot, and position rows before deriving new
  values so concurrent pooled sessions cannot overfill or lose ledger updates;
- account, position, order, and fill reads borrow a connection without opening
  a transaction.

No domain model, factory selection, or SQLite implementation changes are
required.

## Testing

The SQLite-backed double will model PyMySQL instead of mysql-connector:

- `get_connection()` is a context manager;
- the connection exposes `begin()`;
- entry/exit, begin, commit, and rollback are observable;
- cursors remain bare and return mapping-compatible rows.

Tests will first prove the current implementation cannot construct against that
contract. They will then verify successful writes begin and commit, failed
writes roll back, reads do not begin transactions, and the pool—not the
engine—owns connection cleanup. SQL-contract assertions will verify that rows
used to derive fill and cancellation updates are selected `FOR UPDATE`.

A separate contract test will instantiate the real shared `ConnectionPool`
while monkeypatching `pymysql.connect`. Constructing and reading through
`MysqlPaperEngine` will therefore exercise the production context-manager path
without network access or credentials. Existing MySQL-engine tests and focused
SQLite paper-engine regression tests will verify behavioral preservation.

## Error handling and scope

The pool continues to close connections on all exits. Expected
`PaperEngineError` rejections are rolled back inside the borrow and re-raised
unchanged after the pool context exits, preventing the shared pool from
misreporting domain refusals as connection failures. Driver errors still cross
the pool context and retain its connection-error logging.
Changes are limited to issue #2059; unrelated execution and snapshot work,
including #1719, is out of scope.
