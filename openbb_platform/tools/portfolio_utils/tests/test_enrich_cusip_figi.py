"""Regression tests for ``portfolio_utils/enrich_cusip_figi.py`` review-feedback fixes (PR #95).

Covers the four behaviors flagged in code review:
- A: ``--sleep`` is plumbed end-to-end into ``enrich()`` (was silently ignored)
- B: ``--database`` sets ``DB_NAME`` env before the first DB call (was silently ignored)
- C: ``transactional_upsert_cusip_map`` uses BEGIN/COMMIT/ROLLBACK so a failing
     batch leaves zero rows behind (was using autocommit + silently partial-writing)
- E: ``load_dotenv`` is called at module load so ``OPEN_FIGI_API_KEY`` from
     ``.env`` reaches ``os.environ`` (was silently downgrading to keyless)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Make the portfolio_utils inner package + repo-root providers importable.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_PKG_DIR, "portfolio_utils")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# Repo root sits 4 levels above the tests dir:
# openbb_platform/tools/portfolio_utils/tests/  ->  parents[3] is repo root.
_REPO_ROOT = os.path.abspath(os.path.join(_PKG_DIR, "..", "..", ".."))
for _p in (
    os.path.join(_REPO_ROOT, "openbb_platform", "providers", "sec"),
    os.path.join(_REPO_ROOT, "openbb_platform", "providers", "fmp_cached"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import enrich_cusip_figi  # noqa: E402

# ---------------------------------------------------------------------------
# Fix A: --sleep is plumbed into enrich()
# ---------------------------------------------------------------------------


def test_enrich_signature_accepts_extra_sleep():
    """The enrich() function must accept extra_sleep as a kw arg (review fix A)."""
    import inspect

    sig = inspect.signature(enrich_cusip_figi.enrich)
    assert "extra_sleep" in sig.parameters, (
        "enrich() must accept extra_sleep (review fix A — --sleep was silently dropped)"
    )
    # Default should be 0.0 so existing callers don't change behavior
    assert sig.parameters["extra_sleep"].default == 0.0


def test_enrich_extra_sleep_calls_time_sleep_between_batches():
    """extra_sleep > 0 triggers time.sleep between batches (but not after the last)."""
    # Two batches of size 100; extra_sleep=0.7 → expect exactly one sleep(0.7)
    cusips = ["c" * 9] * 150
    sleeps: list[float] = []

    with patch.object(enrich_cusip_figi.time, "sleep", sleeps.append), \
         patch("openbb_sec.utils.openfigi.map_cusips", return_value={}), \
         patch("openbb_sec.utils.openfigi.select_match", return_value=None):
        enrich_cusip_figi.enrich(
            cusips,
            api_key="fake-key",  # keyed → batch_size 100 → 2 batches
            refresh=False,
            dry_run=True,
            audit_disagreements=False,
            max_batches=None,
            extra_sleep=0.7,
        )

    # Exactly one extra_sleep call (after batch 1, NOT after batch 2)
    extra_sleeps = [s for s in sleeps if s == 0.7]
    assert len(extra_sleeps) == 1, (
        f"expected exactly 1 extra_sleep call between 2 batches, got {extra_sleeps}"
    )


def test_enrich_no_extra_sleep_when_zero():
    """extra_sleep=0.0 (the default) means no extra sleep calls."""
    sleeps: list[float] = []

    with patch.object(enrich_cusip_figi.time, "sleep", sleeps.append), \
         patch("openbb_sec.utils.openfigi.map_cusips", return_value={}), \
         patch("openbb_sec.utils.openfigi.select_match", return_value=None):
        enrich_cusip_figi.enrich(
            ["c" * 9] * 150,
            api_key="fake-key",
            refresh=False,
            dry_run=True,
            audit_disagreements=False,
            max_batches=None,
            extra_sleep=0.0,
        )

    assert 0.0 not in sleeps, "extra_sleep=0 should not call time.sleep(0)"


# ---------------------------------------------------------------------------
# Fix B: --database sets DB_NAME env before _db() is touched
# ---------------------------------------------------------------------------


def test_main_sets_db_name_env_when_database_flag_given(monkeypatch):
    """--database X should set os.environ['DB_NAME']=X before the first _db() call (review fix B)."""
    captured_env_at_init: dict = {}

    def fake_init():
        # Snapshot DB_NAME at the moment init_openfigi_cache fires (right after the env should be set)
        captured_env_at_init["DB_NAME"] = os.environ.get("DB_NAME")

    # Stub out everything past env-setting so main() can run end-to-end
    monkeypatch.setattr(sys, "argv", ["enrich_cusip_figi.py", "--database", "fake_db_xyz", "--dry-run"])
    with patch("openbb_sec.utils.openfigi.init_openfigi_cache", side_effect=fake_init), \
         patch("openbb_sec.utils.openfigi.resolve_credentials", return_value=(None, "keyless")), \
         patch.object(enrich_cusip_figi, "select_target_cusips", return_value=[]), \
         patch.object(enrich_cusip_figi, "enrich", return_value={"requested": 0, "mapped_ok": 0,
            "ambiguous": 0, "no_match": 0, "errors": 0, "disagreements": 0, "written": 0}):
        rc = enrich_cusip_figi.main()

    assert rc == 0
    assert captured_env_at_init.get("DB_NAME") == "fake_db_xyz", (
        f"--database fake_db_xyz must set DB_NAME before init_openfigi_cache fires; "
        f"got DB_NAME={captured_env_at_init.get('DB_NAME')!r}"
    )


def test_main_does_not_touch_db_name_env_when_database_flag_omitted(monkeypatch):
    """Without --database, DB_NAME stays whatever it already was (no clobbering)."""
    monkeypatch.setenv("DB_NAME", "preexisting_env_value")
    monkeypatch.setattr(sys, "argv", ["enrich_cusip_figi.py", "--dry-run"])
    with patch("openbb_sec.utils.openfigi.init_openfigi_cache"), \
         patch("openbb_sec.utils.openfigi.resolve_credentials", return_value=(None, "keyless")), \
         patch.object(enrich_cusip_figi, "select_target_cusips", return_value=[]), \
         patch.object(enrich_cusip_figi, "enrich", return_value={"requested": 0, "mapped_ok": 0,
            "ambiguous": 0, "no_match": 0, "errors": 0, "disagreements": 0, "written": 0}):
        enrich_cusip_figi.main()

    assert os.environ.get("DB_NAME") == "preexisting_env_value"


# ---------------------------------------------------------------------------
# Fix C: transactional_upsert_cusip_map rolls back on failure
# ---------------------------------------------------------------------------


def test_transactional_upsert_rolls_back_on_executemany_failure():
    """When executemany raises, the helper rolls back and re-raises (review fix C)."""
    rows = [("c0", "ISSUER", "AAA", "Common Stock", "BBG0", "openfigi", None)]

    fake_cursor = MagicMock()
    fake_cursor.executemany.side_effect = RuntimeError("simulated mid-batch failure")

    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False

    fake_pool_ctx = MagicMock()
    fake_pool_ctx.get_connection.return_value.__enter__.return_value = fake_conn
    fake_pool_ctx.get_connection.return_value.__exit__.return_value = False

    fake_db = MagicMock()
    fake_db.get_connection_pool.return_value = fake_pool_ctx

    with patch.object(enrich_cusip_figi, "_db", return_value=fake_db), \
         pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        enrich_cusip_figi.transactional_upsert_cusip_map(rows)

    # Critical assertions: autocommit was flipped off, then rollback was called,
    # then autocommit was restored.
    autocommit_calls = [call.args[0] for call in fake_conn.autocommit.call_args_list]
    assert autocommit_calls == [False, True], (
        f"expected autocommit(False) then autocommit(True), got {autocommit_calls}"
    )
    fake_conn.rollback.assert_called_once()
    fake_conn.commit.assert_not_called()


def test_transactional_upsert_commits_on_success():
    """Happy path: rows are committed and rowcount is returned."""
    rows = [("c1", "I", "B", None, "BBG", "openfigi", None)] * 3

    fake_cursor = MagicMock()
    fake_cursor.rowcount = 6  # MySQL ON DUPLICATE KEY UPDATE returns 2 per upsert

    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False

    fake_pool_ctx = MagicMock()
    fake_pool_ctx.get_connection.return_value.__enter__.return_value = fake_conn
    fake_pool_ctx.get_connection.return_value.__exit__.return_value = False

    fake_db = MagicMock()
    fake_db.get_connection_pool.return_value = fake_pool_ctx

    with patch.object(enrich_cusip_figi, "_db", return_value=fake_db):
        result = enrich_cusip_figi.transactional_upsert_cusip_map(rows)

    assert result == 6
    fake_conn.commit.assert_called_once()
    fake_conn.rollback.assert_not_called()
    # Autocommit restored even on success
    autocommit_calls = [call.args[0] for call in fake_conn.autocommit.call_args_list]
    assert autocommit_calls == [False, True]


def test_transactional_upsert_empty_rows_is_noop():
    """Empty input returns 0 without touching the connection pool."""
    fake_db = MagicMock()
    with patch.object(enrich_cusip_figi, "_db", return_value=fake_db):
        result = enrich_cusip_figi.transactional_upsert_cusip_map([])
    assert result == 0
    fake_db.get_connection_pool.assert_not_called()


# ---------------------------------------------------------------------------
# Fix E: load_dotenv ran at module import (so .env keys reach os.environ)
# ---------------------------------------------------------------------------


def test_module_loads_dotenv_at_import():
    """The module's top-level should call load_dotenv with the repo-root .env (review fix E)."""
    # We can't easily assert "was called at import" after the fact, but we can
    # assert the module owns a `load_dotenv` symbol (proving the import + soft-guard
    # ran without crashing on systems where python-dotenv is installed) AND that
    # the source file references load_dotenv near the top.
    import pathlib

    src = pathlib.Path(enrich_cusip_figi.__file__).read_text(encoding="utf-8")
    head = src[:3500]  # first ~3.5KB of file (past docstring + imports + load_dotenv block)
    assert "load_dotenv" in head, (
        "enrich_cusip_figi.py must call load_dotenv at module top-of-file (review fix E); "
        "otherwise the OPEN_FIGI_API_KEY tier of R2's credential ladder silently misses."
    )
    assert '_PROJECT_ROOT / ".env"' in head, (
        "load_dotenv must point at PROJECT_ROOT/.env to honor the sibling convention."
    )
