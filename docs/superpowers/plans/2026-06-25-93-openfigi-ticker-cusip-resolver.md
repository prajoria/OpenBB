# Issue #93 — OpenFIGI ticker→CUSIP Resolver Implementation Plan

> 🔒 **BRANCH FROZEN — work on this plan is COMPLETE.** All four tasks
> (T1–T4) shipped via **[PR #95](https://github.com/prajoria/OpenBB/pull/95)**
> (`feat/93-openfigi-ticker-cusip-resolver` → `trading_technicals`). 51/51
> unit tests green; live-run evidence in
> [`Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md`](../../../Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md).
> See [`BRANCH-FROZEN.md`](../../../BRANCH-FROZEN.md) at repo root.
>
> **Do not amend, re-run, or branch new work off these tasks.** Review
> feedback on PR #95 → handle in a new branch per the BRANCH-FROZEN rules.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `resolve_cusip(symbol)` coverage from the #89 MVP universe (~514 S&P 500 + B4 seed tickers) to the broad 13F universe by deterministically mapping every un-tickered CUSIP already present in `sec_13f_holdings` to a `(ticker, figi)` via Bloomberg's free OpenFIGI `/v3/mapping` API, with read-through response caching.

**Architecture:** Two new files plus one extension:
1. **`providers/sec/openbb_sec/utils/openfigi.py`** — a thin `requests`-based OpenFIGI `/v3/mapping` client that owns the `openfigi_map_cache` read-through cache, batching, rate limiting, and the deterministic `select_match()` ladder (R3).
2. **`Tools/enrich_cusip_figi.py`** — an offline batch job that selects un-tickered CUSIPs from `sec_13f_holdings` (ranked by latest-period held value), maps them in chunks, and upserts the chosen `(ticker, figi)` into `sec_13f_cusip_map` with `source='openfigi'` (or `'openfigi_ambiguous'` on skip).
3. **Per-tool spec doc + DESIGN.md changelog** under `Tools/docs/`.

No change to `resolve_cusip` itself, `sec_13f_cusip_map` DDL, the existing `upsert_cusip_map` helper, or the `fmp_cached` SEC tier. The new `openfigi_map_cache` table is owned by the helper, created on demand.

**Tech Stack:** Python 3.10–3.13, `requests` (no `aiohttp`), MySQL via the existing `openbb_fmp_cached.utils.database` helpers, OpenFIGI `/v3/mapping` v3 contract (vendored fork at `third_party/openfigi-api/python/example.py` is the reference shape — submodule already added, not imported at runtime).

## Global Constraints

These apply to every task. Copied verbatim from `docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md` §0.1–§0.3:

- **L1 — Mechanism:** OpenFIGI `/v3/mapping` with `idType=ID_CUSIP`. Deterministic key→key. No licensed CUSIP master may be copied.
- **L3 — No 13F schema change:** the existing `sec_13f_cusip_map` table (`cusip, issuer_name, ticker, title_class, figi, source, updated_at`) is the target. **Do not add columns.**
- **L5 — No fuzzy issuer-name matching anywhere.** Ambiguous results are skipped + flagged, never guessed.
- **L6 — HTTP rules:** `requests` only (no `aiohttp`); descriptive UA `OpenBBTechnical/openfigi-enrich/0.1`; `Content-Type: application/json`; resumable; per-CUSIP try/except.
- **L7 — Idempotency:** `INSERT … ON DUPLICATE KEY UPDATE` only; `ticker = COALESCE(VALUES(ticker), ticker)` (never null an existing richer ticker). Provenance precedence is enforced **app-side** by the R5 anti-join, *not* by `COALESCE`.
- **R1 — Helper location:** `providers/sec/openbb_sec/utils/openfigi.py`. The fork submodule is reference-only and excluded from packaging.
- **R2 — Credentials order:** `--api-key` flag → `OPEN_FIGI_API_KEY` env → `user_settings.credentials.openfigi_api_key` → keyless. Log `mode=keyed|keyless source=…` at startup (never the key value).
- **R3 — `select_match()` ladder (apply in order, stop at first single match):**
  1. Filter to `marketSector == "Equity"` ∧ `securityType2 ∈ {"Common Stock","Preferred Stock"}` ∧ `exchCode ∈ US_COMPOSITE_SET` (`{"US"}`, module constant).
  2. Of survivors, prefer rows where `figi == compositeFIGI`.
  3. If still >1, prefer `securityType2 == "Common Stock"` over `Preferred Stock`.
  4. If still ambiguous → **skip + flag**.
- **R4 — Persist ambiguous skips:** write a row `(ticker=NULL, source='openfigi_ambiguous')` so re-runs anti-join past them; `--reresolve-flagged` re-attempts.
- **R5 — Source query:** distinct `cusip` from `sec_13f_holdings` where `put_call IS NULL` ∧ `CHAR_LENGTH(cusip)=9`, ranked by `SUM(value_usd)` over the **latest period per filer**; left-anti-join excludes any CUSIP whose existing row in `sec_13f_cusip_map` has `ticker IS NOT NULL` **or** `source IN ('seed','fmp_profile','openfigi','openfigi_ambiguous')`. `--limit` counts **distinct CUSIPs**. Per-batch transactional upsert.
- **R6 — Provenance enforcement is app-side** (anti-join filters out `seed`/`fmp_profile` CUSIPs upstream). `--audit-disagreements` maps without writing and WARNs on OpenFIGI ↔ existing ticker diffs.
- **R8 — CLI flags:** mirror `populate_cusip_map.py` plus `--max-batches --since --reresolve-flagged --audit-disagreements --refresh`.
- **R9 — Read-through cache:** new table `openfigi_map_cache` keyed `(id_type, id_value, exch_code)`; `OPENFIGI_CACHE_TTL_DAYS = 180`; `--refresh` bypasses; log hits/misses/stores at run end.
- **Codebase conventions:** Ruff line-length 122, `Decimal` for money (N/A here — value rankings only), `pathlib`, `logging` (no `print` inside the helper module — CLI scripts may print to stdout for the human-facing run report, per `populate_cusip_map.py` precedent), no emoji.
- **Tests:** unit tests live at `openbb_platform/providers/sec/tests/test_openfigi.py` (alongside `test_thirteen_f_index.py`), not under `utils/tests/`. All offline with fixtures.
- **Venv:** all test/dev commands use `.venv_win\Scripts\python.exe` (Windows path; the existing skill convention).

---

## File Structure

| File | Disposition | Lines (approx) | Responsibility |
|---|---|---:|---|
| `openbb_platform/providers/sec/openbb_sec/utils/openfigi.py` | NEW | ~400 | OpenFIGI `/v3/mapping` client + `select_match()` + `openfigi_map_cache` DDL/helpers/stats |
| `openbb_platform/providers/sec/tests/test_openfigi.py` | NEW | ~350 | Unit tests for client, batching, cache, rate-limit policy, match ladder (all offline, no network) |
| `Tools/enrich_cusip_figi.py` | NEW | ~320 | Offline batch enrichment CLI |
| `Tools/docs/specs/enrich_cusip_figi.md` | NEW | ~80 | Per-tool spec (matches existing `Tools/docs/specs/` precedent) |
| `Tools/docs/DESIGN.md` | EDIT | +~15 | Add to DB-loaders inventory + changelog entry |
| `.gitmodules` + `third_party/openfigi-api` submodule | **already staged** | — | Reference-only vendored fork (commit in Task 1) |
| `pyproject.toml` (root + `providers/sec/`) | EDIT (verify only) | — | Confirm no `packages` glob picks up `third_party/openfigi-api` (R1 CI safety check) |

---

## Task 1: OpenFIGI client + `select_match()` + read-through cache (R9)

**bd issue:** `OpenBBTechnical-93-T1` (file in Phase 2 of openbb-dev-cycle, blocked-by: parent `cse` un-defer)

**Files:**
- Create: `openbb_platform/providers/sec/openbb_sec/utils/openfigi.py`
- Create: `openbb_platform/providers/sec/tests/test_openfigi.py`
- Verify: root `pyproject.toml` + `openbb_platform/providers/sec/pyproject.toml` — confirm `third_party/openfigi-api` is not picked up by any `packages` / `include` glob (R1 CI safety, Q-A reviewer note 4)
- Commit: staged `third_party/openfigi-api` submodule + `.gitmodules` (separate first commit so the test suite has the reference handy)

**Interfaces:**
- Consumes:
  - `openbb_fmp_cached.utils.database._db().execute_query(sql, params)` returning `list[dict]`
  - `openbb_fmp_cached.utils.database._db().execute_many(sql, rows)` returning `int`
  - The fork's `/v3/mapping` request/response contract (see `third_party/openfigi-api/python/example.py:38-71`)
- Produces (the public surface Task 2 imports):
  - `OPEN_FIGI_API_URL: str = "https://api.openfigi.com/v3/mapping"`
  - `US_COMPOSITE_SET: frozenset[str] = frozenset({"US"})`
  - `OPENFIGI_CACHE_TTL_DAYS: int = 180`
  - `class OpenFIGIMatch(TypedDict)` — keys: `figi, ticker, name, exchCode, securityType, securityType2, compositeFIGI, marketSector`
  - `class RateLimitPolicy` (`@dataclass(frozen=True)`) — fields: `requests_per_minute: int`, `requests_per_6h: int`, `batch_size: int`. Class methods `keyed() -> RateLimitPolicy` (batch 100, 25 rpm, 25000/6h placeholder verified at impl time), `keyless() -> RateLimitPolicy` (batch 10, 25 rpm, 250/6h placeholder).
  - `def resolve_credentials(api_key_arg: str | None) -> tuple[str | None, str]` — returns `(api_key_or_None, source_label)` where source ∈ `{"flag","env","user_settings","keyless"}`
  - `def init_openfigi_cache() -> None` — runs `CREATE TABLE IF NOT EXISTS openfigi_map_cache (…)`
  - `def cache_get(id_value: str, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> dict | None` — returns the cached **raw job result** (parsed JSON: `{"data": [...]}` or `{"error": "..."}`) if a fresh hit, else `None`
  - `def cache_put(id_value: str, job_result: dict, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> None` — upserts raw response into `openfigi_map_cache`
  - `def map_cusips(cusips: list[str], *, api_key: str | None = None, policy: RateLimitPolicy | None = None, refresh: bool = False) -> dict[str, dict]` — returns `{cusip: raw_job_result}` (mix of cache hits + fresh API calls). On 429, honors `Retry-After`; falls back to exponential backoff if header absent. Logs `cache hits=N misses=M stores=K` at end.
  - `def select_match(job_result: dict) -> OpenFIGIMatch | None` — applies R3 ladder; returns `None` on ambiguous/no-match
  - `class OpenFIGIError(Exception)` — for non-recoverable client errors (auth, malformed batch)

- [ ] **Step 1: Commit the staged vendored fork submodule** (already in `git status`; commit it first so Task 1 tests can reference it).

```bash
git status   # confirm: new file: third_party/openfigi-api ; modified: .gitmodules
git commit -m "$(cat <<'EOF'
chore(third_party): vendor openfigi-api fork as submodule (#93 L8)

Reference-only fork of OpenFIGI/api-examples (Apache-2.0). Documents the
/v3/mapping contract; openbb_sec.utils.openfigi will wrap the same shape
with `requests`. Not imported at runtime, not on the package path.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Confirm `pyproject.toml` packaging does not include the fork (R1 CI safety).**

Run:

```bash
grep -n "third_party\|openfigi" H:/masterswork/git/OpenBBTechnical/pyproject.toml
grep -n "third_party\|openfigi" H:/masterswork/git/OpenBBTechnical/openbb_platform/providers/sec/pyproject.toml
```

Expected: no hits, OR the third_party glob is explicitly excluded. If a `packages = [...]` line includes a glob that would pick up `third_party/`, add an `exclude` entry. Document the result in the commit message for Step 14.

- [ ] **Step 3: Write failing test for `select_match()` single-match happy path.**

Create `openbb_platform/providers/sec/tests/test_openfigi.py` with:

```python
"""Unit tests for openbb_sec.utils.openfigi (#93)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from openbb_sec.utils.openfigi import (
    OPENFIGI_CACHE_TTL_DAYS,
    OPEN_FIGI_API_URL,
    US_COMPOSITE_SET,
    OpenFIGIError,
    RateLimitPolicy,
    cache_get,
    cache_put,
    init_openfigi_cache,
    map_cusips,
    resolve_credentials,
    select_match,
)


# ---------------------------------------------------------------------------
# Fixtures — verbatim shapes from third_party/openfigi-api/python/example.py
# ---------------------------------------------------------------------------

AAPL_JOB_RESULT: dict = {
    "data": [
        {
            "figi": "BBG000B9XRY4",
            "name": "APPLE INC",
            "ticker": "AAPL",
            "exchCode": "US",
            "compositeFIGI": "BBG000B9XRY4",
            "uniqueID": "EQ0010169500001000",
            "securityType": "Common Stock",
            "marketSector": "Equity",
            "shareClassFIGI": "BBG001S5N8V8",
            "securityType2": "Common Stock",
            "securityDescription": "AAPL",
        }
    ]
}

NO_MATCH_JOB_RESULT: dict = {"warning": "No identifier found."}

ERROR_JOB_RESULT: dict = {"error": "Invalid idType/idValue combination"}


def test_select_match_returns_single_us_composite_common():
    """R3 ladder rung (a): one Common-Stock US-composite match → keep it."""
    m = select_match(AAPL_JOB_RESULT)
    assert m is not None
    assert m["ticker"] == "AAPL"
    assert m["figi"] == "BBG000B9XRY4"
    assert m["securityType2"] == "Common Stock"
```

- [ ] **Step 4: Run the test to verify it fails.**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py::test_select_match_returns_single_us_composite_common -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'openbb_sec.utils.openfigi'`.

- [ ] **Step 5: Create `openfigi.py` with the minimum surface to pass Step 3.**

```python
"""OpenFIGI /v3/mapping client + read-through cache (issue #93).

Owns the `openfigi_map_cache` table (R9). Helper lives under
``openbb_sec.utils`` — same package as ``thirteen_f_index.py`` from #89 — so
any future SEC-provider command can call it without a circular ``Tools/``
import. Today's only runtime caller is ``Tools/enrich_cusip_figi.py``.

The vendored fork at ``third_party/openfigi-api/python/example.py`` documents
the v3 contract this module wraps; we never import that script (it isn't on
the installed package path, same one-way rule #89 Q-A applied to ``Tools/``).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPEN_FIGI_API_URL = "https://api.openfigi.com/v3/mapping"
US_COMPOSITE_SET = frozenset({"US"})
OPENFIGI_CACHE_TTL_DAYS = 180
_DEFAULT_USER_AGENT = "OpenBBTechnical/openfigi-enrich/0.1"
_DEFAULT_TIMEOUT_SECS = 30


# ---------------------------------------------------------------------------
# Public TypedDicts
# ---------------------------------------------------------------------------


class OpenFIGIMatch(TypedDict, total=False):
    figi: str
    ticker: str
    name: str
    exchCode: str
    securityType: str
    securityType2: str
    compositeFIGI: str
    marketSector: str


class OpenFIGIError(Exception):
    """Non-recoverable OpenFIGI client error (auth, malformed batch, etc.)."""


# ---------------------------------------------------------------------------
# R3 — select_match() deterministic ladder
# ---------------------------------------------------------------------------


def select_match(job_result: dict) -> OpenFIGIMatch | None:
    """Pick exactly one match from an OpenFIGI /v3/mapping job result.

    Applies the R3 ladder; returns ``None`` for no-match, error payloads, or
    truly ambiguous (>1 surviving US-composite Common Stock).
    """
    matches = job_result.get("data") or []
    if not matches:
        return None

    # Rung (a): equity + (Common|Preferred) + US composite
    survivors = [
        m for m in matches
        if m.get("marketSector") == "Equity"
        and m.get("securityType2") in {"Common Stock", "Preferred Stock"}
        and m.get("exchCode") in US_COMPOSITE_SET
    ]
    if not survivors:
        return None
    if len(survivors) == 1:
        return survivors[0]  # type: ignore[return-value]

    # Rung (b): figi == compositeFIGI
    composite = [m for m in survivors if m.get("figi") and m["figi"] == m.get("compositeFIGI")]
    if len(composite) == 1:
        return composite[0]  # type: ignore[return-value]
    pool = composite or survivors

    # Rung (c): Common over Preferred
    commons = [m for m in pool if m.get("securityType2") == "Common Stock"]
    if len(commons) == 1:
        return commons[0]  # type: ignore[return-value]

    # Rung (d): genuinely ambiguous
    return None


# Other helpers (rate policy, credentials, cache, map_cusips) added in
# subsequent steps.
```

Add a *minimal* stub for the remaining symbols imported by the test file so collection passes — they'll be implemented in later steps:

```python
@dataclass(frozen=True)
class RateLimitPolicy:
    requests_per_minute: int
    requests_per_6h: int
    batch_size: int

    @classmethod
    def keyed(cls) -> "RateLimitPolicy":
        return cls(requests_per_minute=25, requests_per_6h=25_000, batch_size=100)

    @classmethod
    def keyless(cls) -> "RateLimitPolicy":
        return cls(requests_per_minute=25, requests_per_6h=250, batch_size=10)


def resolve_credentials(api_key_arg: str | None) -> tuple[str | None, str]:
    raise NotImplementedError  # implemented in Step 7

def init_openfigi_cache() -> None:
    raise NotImplementedError  # implemented in Step 9

def cache_get(id_value: str, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> dict | None:
    raise NotImplementedError  # implemented in Step 9

def cache_put(id_value: str, job_result: dict, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> None:
    raise NotImplementedError  # implemented in Step 9

def map_cusips(cusips, *, api_key=None, policy=None, refresh=False):
    raise NotImplementedError  # implemented in Step 11
```

- [ ] **Step 6: Run the test to verify it passes.**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py::test_select_match_returns_single_us_composite_common -v
```

Expected: PASS.

- [ ] **Step 7: Add `select_match()` coverage for all five required fixtures (Q-C reviewer note 4) + ambiguity handling.**

Append to `test_openfigi.py`:

```python
def test_select_match_multi_match_us_composite_plus_foreign_keeps_us():
    """Multi-listing: foreign listings filtered out; US composite kept."""
    job = {
        "data": [
            {"ticker": "AAPL", "figi": "BBG000B9XRY4", "exchCode": "US",
             "compositeFIGI": "BBG000B9XRY4", "securityType2": "Common Stock",
             "marketSector": "Equity"},
            {"ticker": "APC", "figi": "BBG000BLPDP5", "exchCode": "GR",
             "compositeFIGI": "BBG000B9XRY4", "securityType2": "Common Stock",
             "marketSector": "Equity"},
        ]
    }
    m = select_match(job)
    assert m is not None and m["ticker"] == "AAPL"

def test_select_match_adr_via_us_composite():
    """ADR CUSIP → US ADR ticker through composite FIGI."""
    job = {
        "data": [
            {"ticker": "BABA", "figi": "BBG006G2JVL2", "exchCode": "US",
             "compositeFIGI": "BBG006G2JVL2", "securityType2": "Common Stock",
             "marketSector": "Equity"},
        ]
    }
    assert select_match(job) is not None

def test_select_match_preferred_only_returns_preferred():
    """Preferred-only CUSIP is legitimately resolvable; not filtered out."""
    job = {
        "data": [
            {"ticker": "BAC-PB", "figi": "BBG004NLQHS5", "exchCode": "US",
             "compositeFIGI": "BBG004NLQHS5", "securityType2": "Preferred Stock",
             "marketSector": "Equity"},
        ]
    }
    m = select_match(job)
    assert m is not None and m["securityType2"] == "Preferred Stock"

def test_select_match_error_payload_returns_none():
    assert select_match(ERROR_JOB_RESULT) is None

def test_select_match_no_match_returns_none():
    assert select_match(NO_MATCH_JOB_RESULT) is None

def test_select_match_truly_ambiguous_two_us_commons_returns_none():
    """Both rows survive every rung → caller must persist as 'ambiguous'."""
    job = {
        "data": [
            {"ticker": "FOO", "figi": "BBG000000001", "exchCode": "US",
             "compositeFIGI": "BBG000000001", "securityType2": "Common Stock",
             "marketSector": "Equity"},
            {"ticker": "BAR", "figi": "BBG000000002", "exchCode": "US",
             "compositeFIGI": "BBG000000002", "securityType2": "Common Stock",
             "marketSector": "Equity"},
        ]
    }
    assert select_match(job) is None

def test_select_match_prefers_common_over_preferred_when_tied():
    job = {
        "data": [
            {"ticker": "FOO", "figi": "BBG000000001", "exchCode": "US",
             "compositeFIGI": "BBG000000001", "securityType2": "Common Stock",
             "marketSector": "Equity"},
            {"ticker": "FOO-PA", "figi": "BBG000000002", "exchCode": "US",
             "compositeFIGI": "BBG000000002", "securityType2": "Preferred Stock",
             "marketSector": "Equity"},
        ]
    }
    m = select_match(job)
    assert m is not None and m["securityType2"] == "Common Stock"
```

Run:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py -k select_match -v
```

Expected: 7 passing.

- [ ] **Step 8: Implement + test `resolve_credentials()` (R2 order: flag → env → user_settings → keyless).**

Append to `test_openfigi.py`:

```python
def test_resolve_credentials_flag_wins(monkeypatch):
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "from-env")
    key, source = resolve_credentials("from-flag")
    assert key == "from-flag" and source == "flag"

def test_resolve_credentials_env_used_when_no_flag(monkeypatch):
    monkeypatch.setenv("OPEN_FIGI_API_KEY", "from-env")
    key, source = resolve_credentials(None)
    assert key == "from-env" and source == "env"

def test_resolve_credentials_user_settings_used_when_no_env(monkeypatch):
    monkeypatch.delenv("OPEN_FIGI_API_KEY", raising=False)
    fake_creds = MagicMock(openfigi_api_key="from-settings")
    fake_user = MagicMock(default_user_settings=MagicMock(credentials=fake_creds))
    with patch("openbb_sec.utils.openfigi._user_service_credentials", return_value=fake_creds):
        key, source = resolve_credentials(None)
    assert key == "from-settings" and source == "user_settings"

def test_resolve_credentials_keyless_when_nothing_available(monkeypatch):
    monkeypatch.delenv("OPEN_FIGI_API_KEY", raising=False)
    with patch("openbb_sec.utils.openfigi._user_service_credentials", return_value=None):
        key, source = resolve_credentials(None)
    assert key is None and source == "keyless"
```

Replace `resolve_credentials` in `openfigi.py`:

```python
def _user_service_credentials() -> Any | None:
    """Return ``user_settings.credentials`` or ``None`` if openbb_core is absent."""
    try:
        from openbb_core.app.service.user_service import UserService  # noqa: PLC0415
        return UserService().default_user_settings.credentials
    except Exception as exc:  # noqa: BLE001
        logger.debug("openbb_core UserService unavailable for OpenFIGI creds: %s", exc)
        return None


def resolve_credentials(api_key_arg: str | None) -> tuple[str | None, str]:
    """Resolve OpenFIGI key per R2: flag → env → user_settings → keyless.

    Returns ``(key_or_None, source_label)``. Never logs the key value.
    """
    if api_key_arg:
        return api_key_arg, "flag"
    env_key = os.environ.get("OPEN_FIGI_API_KEY")
    if env_key:
        return env_key, "env"
    creds = _user_service_credentials()
    if creds is not None:
        settings_key = getattr(creds, "openfigi_api_key", None)
        if settings_key:
            return settings_key, "user_settings"
    return None, "keyless"
```

Run:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py -k resolve_credentials -v
```

Expected: 4 passing.

- [ ] **Step 9: Implement + test `openfigi_map_cache` table + `cache_get` / `cache_put`.**

Append to `test_openfigi.py`:

```python
@pytest.fixture
def fake_db(monkeypatch):
    """Replace _db() with an in-memory dict-of-rows fake."""
    rows: list[dict] = []

    def execute_many(sql, batch):
        # Trivially "store" (id_type, id_value, exch_code, response_json, status, match_count, fetched_at, is_valid)
        for tup in batch:
            rows.append({
                "id_type": tup[0], "id_value": tup[1], "exch_code": tup[2],
                "response_json": tup[3], "status": tup[4],
                "match_count": tup[5], "fetched_at": tup[6], "is_valid": tup[7],
            })
        return len(batch)

    def execute_query(sql, params=()):
        if sql.lstrip().upper().startswith("CREATE"):
            return None
        if sql.lstrip().upper().startswith("SELECT"):
            id_type, id_value, exch_code = params[0], params[1], params[2]
            for r in rows:
                if (r["id_type"], r["id_value"], r["exch_code"]) == (id_type, id_value, exch_code):
                    return [r]
            return []
        return None

    fake = MagicMock(execute_many=execute_many, execute_query=execute_query)
    monkeypatch.setattr("openbb_sec.utils.openfigi._db", lambda: fake)
    return rows


def test_init_openfigi_cache_runs_ddl(fake_db, monkeypatch):
    captured = []
    monkeypatch.setattr("openbb_sec.utils.openfigi._db",
                        lambda: MagicMock(execute_query=lambda sql, params=(): captured.append(sql)))
    init_openfigi_cache()
    assert any("CREATE TABLE IF NOT EXISTS openfigi_map_cache" in s for s in captured)


def test_cache_put_then_get_round_trips(fake_db):
    cache_put("037833100", AAPL_JOB_RESULT)
    hit = cache_get("037833100")
    assert hit is not None
    assert hit["data"][0]["ticker"] == "AAPL"


def test_cache_get_miss_returns_none(fake_db):
    assert cache_get("999999999") is None


def test_cache_get_stale_row_returns_none(fake_db):
    """Row older than OPENFIGI_CACHE_TTL_DAYS is a miss."""
    from datetime import timedelta
    stale_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=OPENFIGI_CACHE_TTL_DAYS + 1)
    fake_db.append({
        "id_type": "ID_CUSIP", "id_value": "111111111", "exch_code": "",
        "response_json": json.dumps(AAPL_JOB_RESULT),
        "status": "ok", "match_count": 1, "fetched_at": stale_dt, "is_valid": 1,
    })
    assert cache_get("111111111") is None
```

Replace the cache stubs in `openfigi.py`:

```python
DDL_OPENFIGI_CACHE = """
CREATE TABLE IF NOT EXISTS openfigi_map_cache (
    id_type       VARCHAR(16)  NOT NULL,
    id_value      VARCHAR(32)  NOT NULL,
    exch_code     VARCHAR(8)   NOT NULL DEFAULT '',
    response_json LONGTEXT     NOT NULL,
    status        VARCHAR(16)  NOT NULL,
    match_count   INT          NOT NULL DEFAULT 0,
    fetched_at    DATETIME     NOT NULL,
    is_valid      TINYINT(1)   NOT NULL DEFAULT 1,
    PRIMARY KEY (id_type, id_value, exch_code),
    KEY idx_fetched_at (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _db():
    """Lazy import of the fmp_cached DB helpers (same pattern as #89's `thirteen_f_index._db`)."""
    from openbb_fmp_cached.utils import database as _database  # noqa: PLC0415
    return _database.execute_many.__self__ if hasattr(_database.execute_many, "__self__") else _database


def init_openfigi_cache() -> None:
    """Create ``openfigi_map_cache`` if absent (idempotent)."""
    _db().execute_query(DDL_OPENFIGI_CACHE)
    logger.info("openfigi_map_cache table ready")


def _classify(job_result: dict) -> tuple[str, int]:
    """Return (status, match_count) for a raw job result."""
    if "error" in job_result:
        return ("error", 0)
    data = job_result.get("data") or []
    if not data:
        return ("no_match", 0)
    return ("ok", len(data))


def cache_get(id_value: str, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> dict | None:
    """Return the cached raw job result if fresh+valid, else None."""
    try:
        rows = _db().execute_query(
            "SELECT response_json, fetched_at, is_valid "
            "FROM openfigi_map_cache WHERE id_type=%s AND id_value=%s AND exch_code=%s",
            (id_type, id_value, exch_code),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("openfigi cache_get(%s) failed: %s", id_value, exc)
        return None
    if not rows:
        return None
    row = rows[0]
    if not row.get("is_valid"):
        return None
    fetched_at = row.get("fetched_at")
    if fetched_at is None:
        return None
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - _ttl_delta()
    if fetched_at < cutoff:
        return None
    raw = row.get("response_json")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def cache_put(id_value: str, job_result: dict, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> None:
    """Upsert one raw job result (idempotent; L7)."""
    status, count = _classify(job_result)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sql = """
    INSERT INTO openfigi_map_cache
        (id_type, id_value, exch_code, response_json, status, match_count, fetched_at, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
    ON DUPLICATE KEY UPDATE
        response_json = VALUES(response_json),
        status        = VALUES(status),
        match_count   = VALUES(match_count),
        fetched_at    = VALUES(fetched_at),
        is_valid      = 1
    """
    _db().execute_many(sql, [(id_type, id_value, exch_code,
                              json.dumps(job_result), status, count, now)])


def _ttl_delta():
    from datetime import timedelta  # local import keeps the module's top-level light
    return timedelta(days=OPENFIGI_CACHE_TTL_DAYS)
```

Run:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py -k "cache_ or init_openfigi" -v
```

Expected: 4 passing.

- [ ] **Step 10: Write a failing test for `map_cusips()` cache hit / miss / 429 flow.**

Append to `test_openfigi.py`:

```python
def test_map_cusips_serves_from_cache_when_present(fake_db):
    cache_put("037833100", AAPL_JOB_RESULT)
    calls = []
    with patch("openbb_sec.utils.openfigi.requests.post",
               side_effect=AssertionError("must not be called when cache is fresh")) as p:
        result = map_cusips(["037833100"], api_key=None)
        assert p.call_count == 0
    assert result["037833100"]["data"][0]["ticker"] == "AAPL"


def test_map_cusips_batches_misses_and_caches_responses(fake_db):
    response_mock = MagicMock(status_code=200)
    response_mock.json.return_value = [AAPL_JOB_RESULT, NO_MATCH_JOB_RESULT]
    response_mock.raise_for_status.return_value = None
    with patch("openbb_sec.utils.openfigi.requests.post", return_value=response_mock) as p:
        result = map_cusips(["037833100", "999999999"], api_key=None)
    assert p.call_count == 1   # one batch, two jobs
    payload = p.call_args.kwargs["json"]
    assert payload == [
        {"idType": "ID_CUSIP", "idValue": "037833100"},
        {"idType": "ID_CUSIP", "idValue": "999999999"},
    ]
    # Both raw responses are now cached
    assert cache_get("037833100") is not None
    assert cache_get("999999999") is not None
    assert result["999999999"] == NO_MATCH_JOB_RESULT


def test_map_cusips_honors_retry_after_on_429(fake_db, monkeypatch):
    """429 with Retry-After: 1 → sleep 1s, then succeed."""
    sleeps: list[float] = []
    monkeypatch.setattr("openbb_sec.utils.openfigi.time.sleep", lambda s: sleeps.append(s))

    too_many = MagicMock(status_code=429, headers={"Retry-After": "1"})
    too_many.raise_for_status.side_effect = requests.HTTPError(response=too_many)
    ok = MagicMock(status_code=200)
    ok.json.return_value = [AAPL_JOB_RESULT]
    ok.raise_for_status.return_value = None

    with patch("openbb_sec.utils.openfigi.requests.post",
               side_effect=[too_many, ok]) as p:
        result = map_cusips(["037833100"], api_key=None)
    assert p.call_count == 2
    assert 1 in sleeps  # Retry-After honored
    assert result["037833100"]["data"][0]["ticker"] == "AAPL"


def test_map_cusips_refresh_bypasses_cache(fake_db):
    cache_put("037833100", NO_MATCH_JOB_RESULT)  # stale-looking row
    response_mock = MagicMock(status_code=200)
    response_mock.json.return_value = [AAPL_JOB_RESULT]
    response_mock.raise_for_status.return_value = None
    with patch("openbb_sec.utils.openfigi.requests.post", return_value=response_mock):
        result = map_cusips(["037833100"], api_key=None, refresh=True)
    assert result["037833100"] == AAPL_JOB_RESULT
```

Run:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py -k map_cusips -v
```

Expected: 4 FAILING with `NotImplementedError`.

- [ ] **Step 11: Implement `map_cusips()`.**

Replace the `map_cusips` stub in `openfigi.py`:

```python
def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _post_batch(jobs: list[dict], api_key: str | None, max_retries: int = 5) -> list[dict]:
    """POST one batch to /v3/mapping; honor Retry-After on 429."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": _DEFAULT_USER_AGENT,
    }
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    backoff = 1.0
    for attempt in range(max_retries):
        resp = requests.post(OPEN_FIGI_API_URL, json=jobs,
                             headers=headers, timeout=_DEFAULT_TIMEOUT_SECS)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else backoff
            logger.info("OpenFIGI 429; sleeping %.1fs (attempt %d/%d)",
                        wait, attempt + 1, max_retries)
            time.sleep(wait)
            backoff = min(backoff * 2, 60.0)
            continue
        resp.raise_for_status()
        return resp.json()
    raise OpenFIGIError(f"OpenFIGI /v3/mapping retry budget exhausted after {max_retries} 429s")


def map_cusips(
    cusips: list[str],
    *,
    api_key: str | None = None,
    policy: RateLimitPolicy | None = None,
    refresh: bool = False,
) -> dict[str, dict]:
    """Map a list of CUSIPs to their raw OpenFIGI /v3/mapping job results.

    Read-through cache (R9): cache hits short-circuit the API; misses are
    batched per ``policy.batch_size`` and upserted into ``openfigi_map_cache``.
    Returns ``{cusip: raw_job_result}`` (cache + fresh, merged).
    """
    policy = policy or (RateLimitPolicy.keyed() if api_key else RateLimitPolicy.keyless())
    init_openfigi_cache()

    hits = 0
    misses: list[str] = []
    results: dict[str, dict] = {}
    if not refresh:
        for cusip in cusips:
            hit = cache_get(cusip)
            if hit is not None:
                results[cusip] = hit
                hits += 1
            else:
                misses.append(cusip)
    else:
        misses = list(cusips)

    stores = 0
    for batch in _chunked(misses, policy.batch_size):
        jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        responses = _post_batch(jobs, api_key=api_key)
        for cusip, job_result in zip(batch, responses, strict=True):
            cache_put(cusip, job_result)
            stores += 1
            results[cusip] = job_result
        # crude per-minute rate respect: sleep so we don't exceed policy.requests_per_minute
        time.sleep(60.0 / max(1, policy.requests_per_minute))

    logger.info("openfigi map_cusips: cache hits=%d misses=%d stores=%d", hits, len(misses), stores)
    return results
```

Run:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py -k map_cusips -v
```

Expected: 4 passing.

- [ ] **Step 12: Run the full test_openfigi.py file.**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py -v
```

Expected: ~19 passing, 0 failing.

- [ ] **Step 13: Run ruff over the new files.**

```bash
.venv_win\Scripts\python.exe -m ruff check openbb_platform/providers/sec/openbb_sec/utils/openfigi.py openbb_platform/providers/sec/tests/test_openfigi.py
```

Expected: 0 errors. Fix any line-length-122 violations or unused imports inline.

- [ ] **Step 14: Commit Task 1.**

```bash
git add openbb_platform/providers/sec/openbb_sec/utils/openfigi.py \
        openbb_platform/providers/sec/tests/test_openfigi.py
git commit -m "$(cat <<'EOF'
feat(sec/93): OpenFIGI /v3/mapping client + openfigi_map_cache read-through

- providers/sec/utils/openfigi.py: thin requests wrapper for /v3/mapping
  with deterministic select_match() ladder (R3), R2 credential resolution
  (flag→env→user_settings→keyless), RateLimitPolicy (keyed vs keyless),
  429 Retry-After honoring, and an OPENFIGI_CACHE_TTL_DAYS=180 read-through
  cache backed by openfigi_map_cache (R9) — schema lives here, not in
  thirteen_f_index, so L3 (no 13F schema change) is preserved.
- tests/test_openfigi.py: 19 unit tests (no network) covering all 7 R3 fixture
  classes, R2 credential order, cache hit/miss/refresh/stale, 429 retry.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `Tools/enrich_cusip_figi.py` batch CLI

**bd issue:** `OpenBBTechnical-93-T2` (blocked-by: T1)

**Files:**
- Create: `Tools/enrich_cusip_figi.py`
- Test (smoke-only, run during Task 4): `Tools/enrich_cusip_figi.py --help`, `--dry-run`

**Interfaces:**
- Consumes (from Task 1):
  - `openbb_sec.utils.openfigi.map_cusips`, `select_match`, `resolve_credentials`, `RateLimitPolicy`, `init_openfigi_cache`, `OPENFIGI_CACHE_TTL_DAYS`
  - `openbb_sec.utils.thirteen_f_index.upsert_cusip_map(rows)` where each row is `(cusip, issuer_name, ticker, title_class, figi, source, updated_at)` (7-tuple, verified at `thirteen_f_index.py:240-261`)
  - `openbb_fmp_cached.utils.database._db().execute_query(sql, params)` returning `list[dict]`
- Produces: no Python API surface; CLI script.

- [ ] **Step 1: Sketch the CLI scaffold matching `populate_cusip_map.py`'s shape.**

Create `Tools/enrich_cusip_figi.py`:

```python
"""Tools/enrich_cusip_figi.py — broad ticker→CUSIP coverage via OpenFIGI (#93).

Walks the un-tickered CUSIPs in ``sec_13f_holdings`` (left-anti-joined against
``sec_13f_cusip_map``), batches them through OpenFIGI /v3/mapping, picks the
US-composite match via ``select_match()`` (R3), and upserts the result into
``sec_13f_cusip_map`` with ``source='openfigi'`` (or ``'openfigi_ambiguous'``
on skip).

Read the design at docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md
for the locked decisions (L1–L8, R1–R9).

Usage
=====

    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --dry-run
    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --limit 100
    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --refresh --limit 50
    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --audit-disagreements --limit 25

Flags mirror Tools/populate_cusip_map.py plus #93-specific ones
(--max-batches --since --reresolve-flagged --audit-disagreements --refresh).
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make stdout UTF-8 (Windows console default is cp1252) — same as populate_cusip_map.py
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add repo root to sys.path so providers/sec can be imported when run as a script
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "openbb_platform" / "providers" / "sec"))
sys.path.insert(0, str(_REPO_ROOT / "openbb_platform" / "providers" / "fmp_cached"))

logger = logging.getLogger("enrich_cusip_figi")
SOURCE_OPENFIGI = "openfigi"
SOURCE_AMBIGUOUS = "openfigi_ambiguous"
MAX_RUNTIME_DEFAULT_SECS = 3600  # one hour safety cap (R2 reviewer note 4)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
```

- [ ] **Step 2: Implement the R5 source query (distinct un-mapped CUSIPs ranked by latest-period held value).**

Append to `enrich_cusip_figi.py`:

```python
SELECT_UNMAPPED_CUSIPS_SQL = """
WITH latest_period_per_filer AS (
    SELECT filer_cik, MAX(period) AS max_period
    FROM sec_13f_holdings
    GROUP BY filer_cik
),
latest_rows AS (
    SELECT h.cusip, h.value_usd
    FROM sec_13f_holdings h
    JOIN latest_period_per_filer lp
      ON lp.filer_cik = h.filer_cik AND lp.max_period = h.period
    WHERE h.put_call IS NULL
      AND CHAR_LENGTH(h.cusip) = 9
),
ranked AS (
    SELECT cusip, SUM(value_usd) AS held_usd
    FROM latest_rows
    GROUP BY cusip
)
SELECT r.cusip
FROM ranked r
LEFT JOIN sec_13f_cusip_map m ON m.cusip = r.cusip
WHERE (m.cusip IS NULL)
   OR (m.ticker IS NULL
       AND (m.source IS NULL
            OR m.source NOT IN ('seed','fmp_profile','openfigi','openfigi_ambiguous')))
ORDER BY r.held_usd DESC
"""

SELECT_FLAGGED_CUSIPS_SQL = """
SELECT cusip FROM sec_13f_cusip_map
WHERE source = 'openfigi_ambiguous'
ORDER BY updated_at ASC
"""


def _db():
    from openbb_fmp_cached.utils import database as _database  # noqa: PLC0415
    return _database.execute_many.__self__ if hasattr(_database.execute_many, "__self__") else _database


def select_target_cusips(*, since: str | None, reresolve_flagged: bool, limit: int | None) -> list[str]:
    """R5 source query. Returns up to ``limit`` distinct CUSIPs ordered by held USD."""
    if reresolve_flagged:
        rows = _db().execute_query(SELECT_FLAGGED_CUSIPS_SQL)
    else:
        sql = SELECT_UNMAPPED_CUSIPS_SQL
        params: tuple = ()
        if since:
            sql = sql.replace(
                "WHERE h.put_call IS NULL",
                "WHERE h.put_call IS NULL AND h.updated_at >= %s",
                1,
            )
            params = (since,)
        rows = _db().execute_query(sql, params)

    cusips = [r["cusip"] for r in (rows or []) if r.get("cusip")]
    if limit is not None:
        cusips = cusips[:limit]
    return cusips
```

- [ ] **Step 3: Implement the enrichment loop with per-batch transactional upsert (R5 last bullet).**

Append:

```python
def _row_for_upsert(
    cusip: str, match, issuer_hint: str | None = None, *, source: str = SOURCE_OPENFIGI
) -> tuple:
    """Build a sec_13f_cusip_map upsert tuple from a select_match() result."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if match is None:
        return (cusip, issuer_hint or "", None, None, None, source, now)
    return (
        cusip,
        match.get("name") or issuer_hint or "",
        match.get("ticker"),
        match.get("securityType2"),  # 'Common Stock' / 'Preferred Stock' → title_class
        match.get("figi"),
        source,
        now,
    )


def _existing_row(cusip: str) -> dict | None:
    rows = _db().execute_query(
        "SELECT ticker, source FROM sec_13f_cusip_map WHERE cusip=%s",
        (cusip,),
    )
    return rows[0] if rows else None


def enrich(
    cusips: list[str],
    *,
    api_key: str | None,
    refresh: bool,
    dry_run: bool,
    audit_disagreements: bool,
    max_batches: int | None,
    batch_size: int,
) -> dict:
    """Map → select → upsert. Returns a stats dict (also logged at end)."""
    from openbb_sec.utils.openfigi import (  # noqa: PLC0415
        RateLimitPolicy,
        map_cusips,
        select_match,
    )
    from openbb_sec.utils.thirteen_f_index import upsert_cusip_map  # noqa: PLC0415

    policy = RateLimitPolicy.keyed() if api_key else RateLimitPolicy.keyless()
    stats = {"requested": len(cusips), "mapped_ok": 0, "ambiguous": 0,
             "no_match": 0, "errors": 0, "disagreements": 0, "written": 0}

    # Break the work into "batches" of policy.batch_size CUSIPs to keep the
    # transactional upsert window bounded (R5 last bullet).
    total_batches = math.ceil(len(cusips) / max(1, policy.batch_size))
    if max_batches is not None:
        total_batches = min(total_batches, max_batches)
        cusips = cusips[: total_batches * policy.batch_size]

    for batch_idx in range(total_batches):
        chunk = cusips[batch_idx * policy.batch_size : (batch_idx + 1) * policy.batch_size]
        if not chunk:
            break
        logger.info("batch %d/%d: %d cusips", batch_idx + 1, total_batches, len(chunk))
        try:
            results = map_cusips(chunk, api_key=api_key, policy=policy, refresh=refresh)
        except Exception as exc:  # noqa: BLE001 — drop the in-flight batch, do not partial-upsert
            logger.error("batch %d dropped (uncaught error): %s", batch_idx + 1, exc)
            stats["errors"] += len(chunk)
            continue

        rows_to_upsert: list[tuple] = []
        for cusip in chunk:
            job = results.get(cusip)
            if job is None or "error" in (job or {}):
                stats["errors"] += 1
                continue
            match = select_match(job)
            if match is None:
                # No match OR ambiguous — both persist as a flagged row (R4)
                if not (job.get("data") or []):
                    stats["no_match"] += 1
                else:
                    stats["ambiguous"] += 1
                if not (dry_run or audit_disagreements):
                    rows_to_upsert.append(_row_for_upsert(cusip, None, source=SOURCE_AMBIGUOUS))
                continue

            stats["mapped_ok"] += 1
            if audit_disagreements:
                existing = _existing_row(cusip)
                if existing and existing.get("ticker") and existing["ticker"] != match.get("ticker"):
                    stats["disagreements"] += 1
                    logger.warning(
                        "OpenFIGI disagreement: cusip=%s existing=%s (%s) openfigi=%s",
                        cusip, existing["ticker"], existing.get("source"), match.get("ticker"),
                    )
                continue  # audit mode never writes

            if dry_run:
                continue
            rows_to_upsert.append(_row_for_upsert(cusip, match))

        if rows_to_upsert:
            written = upsert_cusip_map(rows_to_upsert)
            stats["written"] += written

    return stats
```

- [ ] **Step 4: Implement `main()` and the human-facing run report.**

Append:

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich sec_13f_cusip_map via OpenFIGI (#93).")
    parser.add_argument("--database", default=None,
                        help="Target MySQL database (default: from DatabaseConfig)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap distinct CUSIPs to enrich this run")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Extra sleep between batches (sec), atop RateLimitPolicy")
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only -- no DB writes (still does cache reads + API calls)")
    parser.add_argument("--api-key", default=None,
                        help="Override OpenFIGI key (else env OPEN_FIGI_API_KEY then user_settings then keyless)")
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Stop after N batches (CI safety; R2 reviewer note 4)")
    parser.add_argument("--since", default=None,
                        help="YYYY-MM-DD: only consider CUSIPs whose holdings updated_at >= since")
    parser.add_argument("--reresolve-flagged", action="store_true",
                        help="Re-attempt CUSIPs previously flagged as openfigi_ambiguous")
    parser.add_argument("--audit-disagreements", action="store_true",
                        help="Map but do not write; WARN-log OpenFIGI ↔ existing ticker diffs")
    parser.add_argument("--refresh", action="store_true",
                        help="Bypass openfigi_map_cache reads and overwrite the row (R9 CLI bypass)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    from openbb_sec.utils.openfigi import init_openfigi_cache, resolve_credentials  # noqa: PLC0415

    api_key, source = resolve_credentials(args.api_key)
    policy_label = "keyed" if api_key else "keyless"
    batch_size = 100 if api_key else 10
    init_openfigi_cache()

    cusips = select_target_cusips(
        since=args.since, reresolve_flagged=args.reresolve_flagged, limit=args.limit,
    )
    total = len(cusips)
    batches_est = math.ceil(total / batch_size) if total else 0
    if args.max_batches is not None:
        batches_est = min(batches_est, args.max_batches)

    print("=" * 70)
    print("  ENRICH sec_13f_cusip_map via OpenFIGI (#93)")
    print("=" * 70)
    print(f"  Distinct un-mapped: {total}")
    print(f"  To enrich this run: {total}")
    print(f"  Estimated batches : {batches_est}  (size {batch_size}, mode {policy_label}, source {source})")
    if args.dry_run:
        print("\n  DRY RUN -- no DB writes (cache reads + OpenFIGI calls still happen).")

    started = time.monotonic()
    stats = enrich(
        cusips,
        api_key=api_key,
        refresh=args.refresh,
        dry_run=args.dry_run,
        audit_disagreements=args.audit_disagreements,
        max_batches=args.max_batches,
        batch_size=batch_size,
    )
    elapsed = time.monotonic() - started

    print(f"\n{'=' * 70}")
    print("  RESULTS")
    print(f"{'=' * 70}")
    print(f"  Requested     : {stats['requested']}")
    print(f"  Mapped OK     : {stats['mapped_ok']}")
    print(f"  Ambiguous     : {stats['ambiguous']}  (persisted as source='openfigi_ambiguous')")
    print(f"  No match      : {stats['no_match']}")
    print(f"  Errors        : {stats['errors']}")
    if args.audit_disagreements:
        print(f"  Disagreements : {stats['disagreements']}  (WARN-logged; not written)")
    print(f"  Rows written  : {stats['written']}")
    print(f"  Elapsed       : {elapsed:.1f}s")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Smoke-test `--help` and `--dry-run` (offline path: planning + DB read only, no API).**

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --help
```

Expected: usage text listing all 11 flags.

If a populated `sec_13f_holdings` exists in the dev DB:

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --dry-run --limit 5
```

Expected: prints the run report with a non-zero "Distinct un-mapped" count and "DRY RUN" notice; no writes.

If the dev DB is empty / unavailable, document in the commit message that the dry-run smoke is deferred to Task 4 (end-to-end verification).

- [ ] **Step 6: Ruff over the new tool.**

```bash
.venv_win\Scripts\python.exe -m ruff check Tools/enrich_cusip_figi.py
```

Expected: 0 errors. Fix line-length-122 inline.

- [ ] **Step 7: Commit Task 2.**

```bash
git add Tools/enrich_cusip_figi.py
git commit -m "$(cat <<'EOF'
feat(tools/93): enrich_cusip_figi.py — broad OpenFIGI ticker→CUSIP backfill

Offline batch job:
- R5 source query: distinct sec_13f_holdings.cusip where put_call IS NULL ∧
  len(cusip)=9, ranked by SUM(value_usd) over the latest period per filer,
  left-anti-joined against sec_13f_cusip_map rows whose source ∈
  ('seed','fmp_profile','openfigi','openfigi_ambiguous') — provenance
  precedence is enforced HERE (R6 app-side), not by COALESCE.
- Maps misses via openbb_sec.utils.openfigi.map_cusips (cache-aware),
  picks the US-composite match via select_match() (R3), and upserts the
  chosen (ticker, figi) into sec_13f_cusip_map. Ambiguous/no-match CUSIPs
  persist as (ticker=NULL, source='openfigi_ambiguous') so re-runs skip
  them (R4); --reresolve-flagged re-attempts.
- CLI flags mirror populate_cusip_map.py plus the five #93-specific ones
  (--max-batches --since --reresolve-flagged --audit-disagreements --refresh).
  Startup banner logs scope: distinct un-mapped, to enrich, batches, mode,
  credential source (R8).
- Per-batch transactional upsert (R5 last bullet): an uncaught exception
  drops the in-flight batch rather than partial-writing it.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Documentation — per-tool spec + DESIGN.md changelog

**bd issue:** `OpenBBTechnical-93-T3` (blocked-by: T1, T2)

**Files:**
- Create: `Tools/docs/specs/enrich_cusip_figi.md` (~80 lines)
- Edit: `Tools/docs/DESIGN.md` — add an entry under the DB-loaders inventory + a changelog line

**Interfaces:** None — documentation only.

- [ ] **Step 1: Read the existing per-tool spec for `populate_cusip_map.py` so the new doc matches its house style.**

```bash
cat H:/masterswork/git/OpenBBTechnical/Tools/docs/specs/populate_cusip_map.md
```

Note the sections used (Purpose, Usage, Inputs, Outputs, Cadence, etc.) and mirror them.

- [ ] **Step 2: Write `Tools/docs/specs/enrich_cusip_figi.md`.**

Sections (in this order):

1. **Purpose** — one paragraph: closes the long-tail ticker→CUSIP gap left by `populate_cusip_map.py`'s S&P-500 scope, using OpenFIGI as the deterministic FIGI bridge per design doc #93.
2. **Usage** — copy the four CLI invocations from the script's docstring; one per common scenario (dry-run, limited live run, refresh, audit).
3. **Inputs** — DB tables read (`sec_13f_holdings`, `sec_13f_cusip_map`); env / cred order (`--api-key` → `OPEN_FIGI_API_KEY` → `user_settings` → keyless).
4. **Outputs** — DB tables written (`sec_13f_cusip_map`, `openfigi_map_cache`); cache TTL (180 days).
5. **Selection rule (R3 ladder)** — the four rungs verbatim from the design.
6. **Provenance precedence** — short paragraph explaining R6 app-side guard (anti-join, not COALESCE).
7. **Cadence** — one-shot now; re-run quarterly after each new `ingest_sec_13f.py` quarter lands; `--reresolve-flagged` opportunistic.
8. **Acceptance checks** — copy the 8 bullets from §3 of the design doc.
9. **Cross-refs** — link the design doc and the related Tools (`populate_cusip_map.md`, `ingest_sec_13f.md`).

- [ ] **Step 3: Edit `Tools/docs/DESIGN.md` to add `enrich_cusip_figi.py` to the inventory and changelog.**

```bash
grep -n "populate_cusip_map\|## Changelog\|DB-loaders" H:/masterswork/git/OpenBBTechnical/Tools/docs/DESIGN.md
```

Add the new tool right after `populate_cusip_map.py` in the inventory table/list. Add one changelog line dated `2026-06-25` referencing issue #93.

- [ ] **Step 4: Commit Task 3.**

```bash
git add Tools/docs/specs/enrich_cusip_figi.md Tools/docs/DESIGN.md
git commit -m "$(cat <<'EOF'
docs(tools/93): per-tool spec + DESIGN.md inventory for enrich_cusip_figi

- Tools/docs/specs/enrich_cusip_figi.md: usage, inputs/outputs, R3 selection
  rule, R6 provenance precedence, cadence, acceptance checks (from #93 §3),
  cross-refs to the design doc and sibling Tools.
- Tools/docs/DESIGN.md: add the new tool to the DB-loaders inventory next to
  populate_cusip_map.py + a changelog line for 2026-06-25 #93.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: End-to-end verification (bounded live run + `resolve_cusip` long-tail check)

**bd issue:** `OpenBBTechnical-93-T4` (blocked-by: T1, T2, T3)

**Files:** none new — this is a verification task with an evidence-only commit (a session log appended to the design doc, or a markdown report under `Tools/docs/runs/`).

**Interfaces:** none.

- [ ] **Step 1: Pick a candidate "long-tail" ticker present in 13F but **not** in the S&P 500 seed/profile rows.**

A reasonable candidate is `SHOP` (Shopify) or `ASML` (ADR) — both are widely held but outside the S&P 500 seed-table population. Verify the chosen ticker resolves to `[]` before enrichment:

```bash
.venv_win\Scripts\python.exe -c "from openbb_sec.utils.thirteen_f_index import resolve_cusip; print(repr(resolve_cusip('SHOP')))"
```

Expected: `[]` (this is the gap #93 closes).

- [ ] **Step 2: Live run, capped at a small `--limit` and `--max-batches`.**

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --limit 100 --max-batches 2
```

Expected behaviors observed in the printed report:
- Distinct un-mapped > 0
- Mapped OK > 0
- Rows written > 0
- Some ambiguous/no_match rows persisted with `source='openfigi_ambiguous'` (per R4)
- The run finishes inside the policy-based rate budget

- [ ] **Step 3: Re-run the same command and verify cache + anti-join idempotency.**

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --limit 100 --max-batches 2
```

Expected: "Distinct un-mapped" drops by the number written in Step 2; the log shows `cache hits=N misses=0 stores=0` for any CUSIP from Step 2 that does get re-queried (the anti-join should also exclude already-mapped rows so we should see zero misses).

- [ ] **Step 4: Confirm the long-tail ticker now resolves.**

```bash
.venv_win\Scripts\python.exe -c "from openbb_sec.utils.thirteen_f_index import resolve_cusip; print(repr(resolve_cusip('SHOP')))"
```

Expected: non-empty list of CUSIPs (the acceptance criterion from design §3 bullet 3). If `SHOP` doesn't surface in the first two batches, pick another candidate observed in the Step 2 log output and verify.

- [ ] **Step 5: Confirm provenance precedence (existing seed/S&P 500 tickers untouched).**

```bash
.venv_win\Scripts\python.exe -c "
from openbb_fmp_cached.utils import database as db
rows = db.execute_query('SELECT source, COUNT(*) AS n FROM sec_13f_cusip_map GROUP BY source')
for r in rows: print(r)
"
```

Expected: `seed` and `fmp_profile` counts unchanged from pre-#93 baseline (anti-join blocked them, R6).

- [ ] **Step 6: Run the cache-bypass refresh path on one CUSIP from Step 2.**

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --refresh --reresolve-flagged --max-batches 1 --limit 5
```

Expected: cache stats log shows non-zero `stores=` even for previously-cached rows.

- [ ] **Step 7: Audit mode — should write nothing.**

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --audit-disagreements --limit 10
```

Expected: report prints `Rows written  : 0`; any disagreement logs are WARN-level.

- [ ] **Step 8: Run the Task 1 unit suite once more to confirm no regression.**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/test_openfigi.py openbb_platform/providers/sec/tests/test_thirteen_f_index.py -v
```

Expected: all green.

- [ ] **Step 9: Record evidence.**

Create `Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md` capturing:
- Command lines from Steps 2–7
- Their stdout/stderr (run report blocks + cache stats)
- The "before" `resolve_cusip('SHOP') == []` and "after" `resolve_cusip('SHOP') == ['…']` evidence
- Per-source row count delta between pre- and post-run

- [ ] **Step 10: Commit evidence + close.**

```bash
git add Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md
git commit -m "$(cat <<'EOF'
test(93): end-to-end verification — bounded OpenFIGI live run

Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md records:
- pre-run: resolve_cusip('SHOP') == [] (the gap #93 closes)
- live run --limit 100 --max-batches 2: K mapped, J ambiguous, written
- re-run idempotent: anti-join excludes already-mapped CUSIPs (0 stores)
- post-run: resolve_cusip('SHOP') == ['…'] — long-tail closed
- provenance precedence: seed/fmp_profile counts unchanged (R6 holds)
- --refresh bypass + --audit-disagreements paths exercised

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Phase-3..Phase-7 handoff (openbb-dev-cycle)

After Task 4 closes:
- **Phase 5 (Quality):** invoke `simplify` over `openfigi.py` + `enrich_cusip_figi.py`, run `mcp__ide__getDiagnostics`, run the full SEC provider test suite (`.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/sec/tests/ -v`).
- **Phase 6 (Review):** invoke `pr-review-toolkit:code-reviewer` on the staged diff; address findings; verify each piece of feedback before agreeing (`superpowers:receiving-code-review`).
- **Phase 7 (Integration):** open PR on `trading_technicals` (per repo branching convention — never to upstream); update CLAUDE.md if the OpenFIGI helper introduces any new repo convention worth capturing; `bd remember` the cache TTL and the R6 anti-join enforcement as cross-session knowledge.

---

## Self-Review (per writing-plans skill)

1. **Spec coverage** — every §3 acceptance criterion maps to a task:
   - `--dry-run` lists N → Task 2 Step 5 + Task 4 Step 2 ✓
   - Live run upserts + idempotency → Task 4 Steps 2–3 ✓
   - `resolve_cusip(long-tail)` non-empty after run → Task 4 Step 4 ✓
   - Seed/S&P never overwritten → Task 4 Step 5 ✓
   - Multi-match → US composite; truly ambiguous → skip+flag → Task 1 Steps 7 + Task 4 Step 7 ✓
   - Cache hit on re-run; `--refresh` forces re-fetch → Task 1 Step 10 + Task 4 Steps 3 & 6 ✓
   - Unit tests offline, no aiohttp, respects rate limits → Task 1 Steps 3–11 ✓
   - DESIGN.md + per-tool spec → Task 3 ✓

2. **Placeholder scan** — no "TBD"/"add error handling later"/"similar to Task N". Code blocks present in every code step.

3. **Type consistency check** —
   - `upsert_cusip_map` row tuple: 7 elements `(cusip, issuer_name, ticker, title_class, figi, source, updated_at)` — used identically in Task 2 Step 3's `_row_for_upsert`. ✓
   - `map_cusips` signature defined in Task 1 Step 5 stub + reimplemented Step 11; Task 2 Step 3 calls `map_cusips(chunk, api_key=api_key, policy=policy, refresh=refresh)` — matches. ✓
   - `select_match` returns `OpenFIGIMatch | None`; Task 2 Step 3 handles `match is None` correctly. ✓
   - `resolve_credentials` returns `tuple[str | None, str]`; Task 2 Step 4 unpacks `api_key, source` — matches. ✓
   - `RateLimitPolicy.keyed()` / `keyless()` factory methods used in both Task 1 (map_cusips default) and Task 2 (policy selection) — name consistent. ✓
   - `init_openfigi_cache()` called in both `map_cusips` (Task 1 Step 11) and `main()` (Task 2 Step 4) — idempotent, both call sites safe. ✓

4. **Scope check** — single subsystem (broad ticker→CUSIP resolver), 4 tightly-coupled deliverables. No decomposition needed.

Plan is internally consistent and ready for execution.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-25-93-openfigi-ticker-cusip-resolver.md`.

Per the openbb-dev-cycle Phase 3, execution will proceed by:
1. **Worktree isolation** — invoke `superpowers:using-git-worktrees` to create `.claude/worktrees/93-openfigi-resolver` (or work directly on `trading_technicals` if the user prefers — this is a single-branch sprint, not a parallel feature).
2. **File bd issues** for T1–T4 with `bd dep add` wiring T2→T1, T3→T1+T2, T4→T1+T2+T3.
3. **Un-defer parent** `bd update OpenBBTechnical-cse --status=open` and link it as the GitHub-tracking issue for #93.
4. **TDD per task** using `superpowers:test-driven-development` and `superpowers:subagent-driven-development` for parallel sub-tasks where possible (Task 1 Steps 3/5, 7, 8, 9, 10/11 are largely independent within the same file and could each be a subagent's deliverable, though their tight file coupling makes serial execution simpler).
