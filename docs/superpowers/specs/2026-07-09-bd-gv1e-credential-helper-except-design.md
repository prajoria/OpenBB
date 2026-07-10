# bd-gv1e — Narrow credential-helper except clauses

**Bead:** OpenBBTechnical-gv1e (P0 security)
**Base:** origin/develop
**Depends on:** none
**Scope:** single file, ~15 semantic LoC

## Goal

`_get_db_config` (L342-343) and `_get_api_key` (L372-373) in
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/index_constituents.py`
wrap the `user_settings.json` read in `except Exception: pass`. This silently
swallows:

1. **`json.JSONDecodeError`** — corrupted / tampered settings file
2. **`PermissionError`** — file exists but not readable (e.g. `chmod 000`)
3. **`UnicodeDecodeError`** — file corrupted with non-UTF-8 bytes
4. **`OSError`** subclasses in general — disk full, disk read error, symlink loop

...and then the user sees a downstream `"Missing MySQL credential(s)"` or
`"No FMP API key"` error with **no hint** that their settings file is broken.

Security concern (per bd-gv1e): silently ignoring a permission-denied read
on a credentials file is exactly what an attacker replacing the file with a
symlink-to-unreadable-file wants.

## Design decisions

### D1 — Narrow to `(json.JSONDecodeError, OSError)` + `log.warning`

**Before:**
```python
try:
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
            ...
except Exception:
    pass
```

**After:**
```python
try:
    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)
            ...
except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
    logger.warning(
        "Failed to read %s: %s. Falling back to env vars.",
        settings_path, exc,
    )
```

**Rationale:**
- `OSError` covers `PermissionError`, `FileNotFoundError` (redundant with `os.path.exists` check but safe against TOCTOU), `IsADirectoryError`, disk read errors, symlink loops
- `json.JSONDecodeError` catches corrupted-JSON specifically
- `UnicodeDecodeError` catches non-UTF-8 bytes when explicit `encoding="utf-8"` is used
- Any OTHER exception (e.g. `KeyError` from a bug in `settings.get`, `AttributeError` from a shape drift) is NOT swallowed — it propagates and gets a real stack trace
- `logger.warning` provides operator visibility without breaking the fallback

### D2 — Explicit `encoding="utf-8"`

Pre-fix `open(settings_path)` uses platform default encoding (varies by
OS/locale). Adding explicit `utf-8` makes `UnicodeDecodeError` deterministic
and testable, and matches how the file is written by the platform.

### D3 — Do NOT add logger import if already present; add if not

Verify `logger = logging.getLogger(__name__)` exists at module top. If yes,
reuse. If no, add + import `logging`.

### D4 — Fix in place, do NOT extract a helper

Two call sites (`_get_db_config`, `_get_api_key`) with slightly different
downstream logic (config vs API key). A shared "safe_read_settings_json"
helper would be nice but adds indirection for ~5 LoC saved. Do the local
narrowing — matches PR #414 P2 fix pattern (didn't factor helpers when
the callsites diverge).

### D5 — Preserve fallback shape (env var takes precedence in _get_api_key)

`_get_api_key` checks env vars FIRST, only falls to settings file if env is
empty. Preserve that ordering — bd-gv1e is about failure surface not
fallback ordering.

## Test plan

`test_credential_helper_narrows_exceptions.py` — new, ~6 tests:

1. **`test_get_db_config_reads_valid_settings_file`** — happy path regression lock
2. **`test_get_db_config_narrows_json_decode_error_with_warning`** — corrupted JSON logs warning, falls back to env
3. **`test_get_db_config_narrows_permission_error_with_warning`** — permission-denied logs warning, falls back
4. **`test_get_db_config_unexpected_exception_propagates`** — a bug that raises `TypeError` MUST propagate (proves the narrow-except catches only the intended set)
5. **`test_get_api_key_env_var_takes_precedence`** — env-first ordering preserved
6. **`test_get_api_key_narrows_json_decode_error_with_warning`** — same narrowing on the API-key path

**Empirical RED-then-GREEN:** revert the narrow-except → tests fail
(specifically the "unexpected exception propagates" test would fail because
bare `except:` swallows the TypeError).

## Beads closed

- **OpenBBTechnical-gv1e** (P0 security)

## Follow-ups (out of scope)

- bd-porh (index_constituents PIT refactor) will subsume this file into a
  larger architectural change. Fixing gv1e standalone now de-risks that
  future refactor by removing the security-critical error-hiding behavior
  from the pre-refactor codebase.
