"""Per-user tuned-config persistence + mtime cache + contextvar override (#83 L3, L9, Q-E, §5.3 W2).

The hot-path module for the L9 auto-load rule: ``engine/indicators.py`` consults
:func:`lookup_tuned_for_symbol` on every panel build to decide whether the symbol's
GICS sector has a robust tuned :class:`IndicatorConfig` waiting in
``~/.openbb_platform/techtrade_tuned.json``.

This module deliberately does NOT import ``tuneta`` or ``openbb_backtest`` -- it
stays importable on a bare techtrade install, so the L9 hot path keeps working
when neither optional extra is present (the lookup just always returns ``None``
in that case and the panel builder falls back to ``DEFAULT_CONFIG``).

Three mechanisms cooperate:

1. **JSON file** at :data:`TUNED_PATH` is the durable store; written atomically
   via :func:`tempfile.NamedTemporaryFile` + :func:`os.replace`. Schema-versioned
   (:data:`SCHEMA_VERSION`); mismatched versions read as absent.
2. **`lru_cache` keyed on `(path, mtime_ns, st_size)`** keeps the hot path
   microsecond-cheap (Q-E E1) while invalidating exactly when the file changes.
   ``st_size`` is the Q-E guard-2 tiebreaker for coarse-mtime filesystems;
   :func:`write_tuned` ALSO calls :func:`_clear_cache` explicitly as belt-and-braces.
3. **`tune_override` contextvar** lets :mod:`tune_router` make a candidate config
   visible to the validate fold loop WITHOUT writing it to disk first (§5.3 W2).
   Verified safe against #82's sequential single-task fold loop (no
   ThreadPool / ProcessPool / executor offload anywhere in openbb_backtest as of
   2026-06-21). If #82 ever fans folds out via an executor, contributors must
   wrap each fold in :func:`contextvars.copy_context().run` or migrate this
   override path to W1 (write -> validate -> revert in finally).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from openbb_techtrade.engine.indicators import IndicatorConfig

# Best-effort symbol -> segment resolver. The real helper is being added to
# engine/universe.py separately; until it ships, we fall back to a tiny in-file
# dict (top ETF holdings across the 11 GICS sectors) so the hot path and the
# unit tests can run on a bare techtrade install.
#
# TODO(#83): replace with engine.universe.segment_for_symbol when shipped.
try:
    from openbb_techtrade.engine.universe import segment_for_symbol
except ImportError:  # pragma: no cover - exercised when the helper is absent
    _FALLBACK_SEGMENTS = {
        # GICS sector seeds (top ~5 holdings per sector ETF) so unit tests can run
        # without the real helper. The real resolver should land via the bead
        # tracked separately.
        "AAPL": "Information Technology", "MSFT": "Information Technology",
        "NVDA": "Information Technology", "GOOG": "Communication Services",
        "META": "Communication Services", "AMZN": "Consumer Discretionary",
        "TSLA": "Consumer Discretionary", "JNJ": "Health Care",
        "UNH": "Health Care", "JPM": "Financials", "BAC": "Financials",
        "XOM": "Energy", "CVX": "Energy", "PG": "Consumer Staples",
        "KO": "Consumer Staples",
    }

    def segment_for_symbol(symbol: str) -> str | None:
        return _FALLBACK_SEGMENTS.get(symbol)


logger = logging.getLogger(__name__)

#: Schema version for the tuned-defaults JSON file. Bumped on incompatible changes.
SCHEMA_VERSION: str = "1.0"

#: Per-user path. Lives alongside user_settings.json. Never committed.
TUNED_PATH: Path = Path.home() / ".openbb_platform" / "techtrade_tuned.json"

#: LRU cache bound (Q-E guard 1). A long interactive session that re-tunes many
#: times will not accumulate more than this many parsed-dict entries.
CACHE_MAXSIZE: int = 8

#: §5.3 W2: per-task candidate-config override active during the validate call.
#: Maps segment name -> candidate IndicatorConfig. ``None`` (default) means "no
#: override, consult the file".
_TUNE_OVERRIDE: ContextVar[dict[str, IndicatorConfig] | None] = ContextVar(
    "_tune_override", default=None
)


# --- public API -------------------------------------------------------------------------------


def read_tuned() -> dict | None:
    """Read and parse the tuned-defaults JSON, or return ``None`` if absent / unparseable.

    Returns the raw parsed dict (with the top-level ``schema_version`` and
    ``segments`` keys). Returns ``None`` when the file does not exist OR when
    its ``schema_version`` does not match :data:`SCHEMA_VERSION` (logged at
    WARNING). Used internally by :func:`lookup_tuned_for_symbol`; tests can
    call it directly for shape assertions.
    """
    try:
        stat = TUNED_PATH.stat()
    except FileNotFoundError:
        return None
    return _read_tuned_cached(str(TUNED_PATH), stat.st_mtime_ns, stat.st_size)


def lookup_tuned_for_symbol(symbol: str) -> IndicatorConfig | None:
    """Hot-path: return the tuned :class:`IndicatorConfig` for ``symbol``'s segment, or ``None``.

    1. Resolve ``symbol`` -> its segment (via :func:`segment_for_symbol`).
    2. If the segment is in the current :data:`_TUNE_OVERRIDE` contextvar, return
       that candidate (§5.3 W2 -- the tune router's mid-validate override).
    3. Else read the on-disk tuned-defaults file; return its entry for the
       segment if present and ``meta.verdict == "robust"`` (defensive: the gate
       in :func:`write_tuned` already enforces this, but the read-side check
       protects against a hand-edited file).
    4. Else return ``None``.
    """
    segment = segment_for_symbol(symbol)
    if segment is None:
        return None
    override = _TUNE_OVERRIDE.get()
    if override is not None and segment in override:
        return override[segment]
    parsed = read_tuned()
    if parsed is None:
        return None
    entry = parsed.get("segments", {}).get(segment)
    if entry is None:
        return None
    if entry.get("meta", {}).get("verdict") != "robust":
        return None
    try:
        return IndicatorConfig(**entry["config"])
    except (TypeError, KeyError) as exc:
        logger.warning("tuned_defaults: bad entry for %s: %s", segment, exc)
        return None


def write_tuned(segment: str, config: IndicatorConfig, meta: dict) -> None:
    """Atomically write ``segment -> {config, meta}`` into the tuned-defaults JSON.

    Reads the current file (if any), merges in the new segment entry, and writes
    via :func:`tempfile.NamedTemporaryFile` + :func:`os.replace` so a concurrent
    reader either sees the old complete file or the new complete file (never a
    half-written one). Explicitly clears the LRU cache (Q-E guard 2) so a
    coarse-mtime filesystem does not serve stale data on the next lookup.

    Caller is responsible for the L2 verdict gate: ``write_tuned`` does not check
    ``meta["verdict"]``, but :func:`lookup_tuned_for_symbol` filters on it on
    read, so a future bug that called ``write_tuned`` with a non-robust meta
    would still be filtered out at the consumer.
    """
    TUNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = read_tuned() or {"schema_version": SCHEMA_VERSION, "segments": {}}
    current.setdefault("segments", {})[segment] = {
        "config": asdict(config),
        "meta": meta,
    }
    # Sort keys + indent=2 for byte-stability across runs (global determinism rule).
    payload = json.dumps(current, sort_keys=True, indent=2)
    # Atomic write: NamedTemporaryFile in the same directory, then os.replace.
    # On Windows, os.replace can fail when the destination is held by a concurrent
    # reader; the try/except guarantees the temp file is cleaned up so we never
    # accumulate `.techtrade_tuned.*.tmp` orphans in ~/.openbb_platform/.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(TUNED_PATH.parent),
        prefix=".techtrade_tuned.", suffix=".tmp", delete=False,
    ) as fh:
        fh.write(payload)
        tmp_name = fh.name
    try:
        os.replace(tmp_name, TUNED_PATH)
    except OSError:
        # Best-effort cleanup; suppress secondary failures so the original raises.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _clear_cache()


@contextmanager
def tune_override(overrides: dict[str, IndicatorConfig]):
    """§5.3 W2: make ``overrides`` visible to :func:`lookup_tuned_for_symbol` for the block.

    Used by :func:`openbb_techtrade.tuning.tune_router.tune` around the
    ``validate_plan`` call so the candidate :class:`IndicatorConfig` is the
    *active* config when the techtrade_confluence strategy re-runs over the WFO
    folds -- without writing anything to disk until the verdict comes back robust.

    The contextvar mechanism is safe because #82's :func:`validate_plan` runs the
    fold loop sequentially in the caller's asyncio task (verified 2026-06-21);
    asyncio context-copy propagates the override into every coroutine the task
    creates. If #82 ever moves folds into a ThreadPool / ProcessPool /
    ``run_in_executor`` worker, the override will NOT cross that boundary and
    this mechanism must be re-evaluated (W1 disk-write-and-revert is the
    documented fallback in design §5.3).
    """
    token = _TUNE_OVERRIDE.set(dict(overrides))
    try:
        yield
    finally:
        _TUNE_OVERRIDE.reset(token)


def _clear_cache() -> None:
    """Drop the cached parsed JSON (Q-E guard 2 belt-and-braces; tests call this too)."""
    _read_tuned_cached.cache_clear()


# --- internal: the cached read ----------------------------------------------------------------


@lru_cache(maxsize=CACHE_MAXSIZE)
def _read_tuned_cached(path: str, mtime_ns: int, size: int) -> dict | None:
    """Cached JSON read keyed on ``(path, mtime_ns, st_size)`` (Q-E E1 + guard 2).

    ``mtime_ns`` is the primary invalidation key; ``size`` is the coarse-mtime
    tiebreaker (two writes inside one mtime tick on a low-resolution filesystem
    will still differ in file size for any non-empty content change). The cache
    is bounded by :data:`CACHE_MAXSIZE` (Q-E guard 1).
    """
    # The mtime_ns/size args are unused inside the body -- their job is to make
    # the cache key correct. Body just reads + validates the schema version.
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("tuned_defaults: read failed for %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("tuned_defaults: top-level JSON in %s is not an object", path)
        return None
    found_version = data.get("schema_version")
    if found_version != SCHEMA_VERSION:
        logger.warning(
            "tuned_defaults: schema_version %r in %s does not match %r; ignoring",
            found_version, path, SCHEMA_VERSION,
        )
        return None
    return data
