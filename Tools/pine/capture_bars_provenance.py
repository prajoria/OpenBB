"""Capture fmp_cached bars for a fixture and write provenance.json (D2.3).

Spec: docs/superpowers/specs/2026-07-20-pine-hybrid-fixture-suite-design.md
      §5 (canonical serialization), §7.1 (this CLI's contract).

The tool fetches bars for a `(symbol, start, end, adjustment)` window
from `openbb_fmp_cached`, canonicalizes them per the shared
`openbb_pine.testing.canonical_bars` module, computes a SHA-256 digest,
and writes the result into `<fixture_dir>/provenance.json`. Running the
tool twice on the same window produces byte-identical output — that
byte-stability is what makes the hash a meaningful drift detector at
test time.

Usage:
    python capture_bars_provenance.py <fixture_dir>
        --symbol NASDAQ:AAPL
        --start 2025-01-01
        --end 2026-07-20
        --timeframe 1D
        --adjustment splits_only
        --timezone America/New_York
        --session regular
        [--tv-strategy-settings-json path/to/settings.json]
        [--force]

`openbb_fmp_cached` is a **deferred import** — imported only when the
default fetcher is invoked. This keeps the module importable (and
testable via the `fetcher=` seam) even when the provider is broken in
the venv (issue #965).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

# Bumped when the provenance.json schema changes in a way harness
# consumers must key on. Keep in sync with spec §4.1 "$schema_version".
PROVENANCE_SCHEMA_VERSION = 1


def _default_fetcher(
    *,
    symbol: str,
    start_date: str,
    end_date: str,
    adjustment: str,
    **_: Any,
) -> list[dict]:
    """Real fetcher — hits `openbb_fmp_cached` via the OBB facade.

    Deferred import so `import capture_bars_provenance` succeeds even
    when `openbb_fmp_cached` is broken in the venv (issue #965).
    Callers who want to bypass the live provider (tests, offline
    reproductions) pass their own `fetcher=` to :func:`capture`.
    """
    # Deferred; NOT at module-scope by design.
    from openbb import obb  # type: ignore[import-not-found]

    result = obb.equity.price.historical(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        provider="fmp_cached",
        adjustment=adjustment,
    )
    records: Iterable[dict] = result.to_dict(orient="records")  # type: ignore[attr-defined]
    return list(records)


def _now_utc_date() -> str:
    """Return today's date in UTC as ISO string. Broken out for
    monkeypatching in tests; note that pinning to date-only keeps
    same-day re-runs idempotent (spec §7.1).
    """
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _build_provenance(
    *,
    fixture_dir: Path,
    symbol: str,
    start: str,
    end: str,
    timeframe: str,
    adjustment: str,
    timezone: str,
    session: str,
    records: list[dict],
    bars_sha256: str,
    strategy_settings_path: Path | None,
) -> dict:
    """Assemble the provenance.json dict per spec §4.

    Any strategy_settings JSON file is embedded verbatim under the
    top-level ``strategy_settings`` key (spec §4 D1.4). This is the
    same shape the reshape tool emits into `<trades>.meta.json`.
    """
    fixture_name = fixture_dir.name

    prov: dict[str, Any] = {
        "$schema_version": PROVENANCE_SCHEMA_VERSION,
        "fixture_name": fixture_name,
        "canary_mode": False,
        "captured_at": _now_utc_date(),
        "bars_source": {
            "provider": "fmp_cached",
            "symbol": symbol,
            "timeframe": timeframe,
            "start_date": start,
            "end_date": end,
            "adjustment": adjustment,
            "timezone": timezone,
            "session": session,
            "bars_sha256": bars_sha256,
            "bars_row_count": len(records),
        },
        # trades_source is populated by the reshape tool's .meta.json
        # emission, not by this capture step; we leave a placeholder
        # here so downstream validators can distinguish "not yet
        # populated" from "wrong schema". Harness Session 2 (D2.5)
        # will merge the two.
        "trades_source": None,
        "parity_assertions": {
            "structural": {
                "gate": "hard_fail",
                "tolerance": "zero",
                "keys": ["trade_num", "date_entry", "date_exit", "type"],
            },
            "numeric": {
                "gate": "warn_and_fail",
                "tolerance_relative": 1.0e-3,
                "warn_threshold_relative": 5.0e-4,
                "columns": [
                    "price_entry",
                    "price_exit",
                    "profit",
                    "profit_percent",
                    "runup",
                    "drawdown",
                    "commission",
                ],
            },
            "equity": "not compared (Wave 1)",
            "stats": "not compared (Wave 1)",
        },
    }

    if strategy_settings_path is not None:
        if not strategy_settings_path.exists():
            raise FileNotFoundError(
                f"strategy_settings_path does not exist: {strategy_settings_path}"
            )
        prov["strategy_settings"] = json.loads(
            strategy_settings_path.read_text(encoding="utf-8")
        )

    return prov


def capture(
    *,
    fixture_dir: Path,
    symbol: str,
    start: str,
    end: str,
    timeframe: str,
    adjustment: str,
    timezone: str,
    session: str,
    fetcher: Callable[..., list[dict]] | None = None,
    strategy_settings_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Fetch, canonicalize, hash, and write provenance.json.

    Args:
        fixture_dir: directory to write provenance.json into. Must
            already exist.
        symbol, start, end, timeframe, adjustment, timezone, session:
            spec §4 ``bars_source`` fields.
        fetcher: callable that receives the same kwargs above (plus
            ``timeframe`` if it wants) and returns a list of bar
            records — each a dict with keys
            ``{date, open, high, low, close, volume}``. Defaults to
            :func:`_default_fetcher` which uses `openbb_fmp_cached`.
        strategy_settings_path: optional JSON file to embed under
            ``strategy_settings`` in the provenance.
        force: overwrite an existing provenance.json rather than
            refusing.

    Returns:
        The written provenance.json path.

    Raises:
        FileNotFoundError: fixture_dir doesn't exist, or
            strategy_settings_path is set and doesn't exist.
        FileExistsError: provenance.json exists and ``force`` is False.
        ValueError: fetcher returned zero records (R7.3).
    """
    if not fixture_dir.exists():
        raise FileNotFoundError(f"fixture_dir does not exist: {fixture_dir}")
    if not fixture_dir.is_dir():
        raise NotADirectoryError(f"fixture_dir is not a directory: {fixture_dir}")

    prov_path = fixture_dir / "provenance.json"
    if prov_path.exists() and not force:
        raise FileExistsError(
            f"provenance.json already exists at {prov_path}; pass force=True "
            "(or --force on the CLI) to overwrite. Overwriting loses the "
            "prior capture's audit trail, so do this deliberately."
        )

    active_fetcher = fetcher or _default_fetcher
    records = active_fetcher(
        symbol=symbol,
        start_date=start,
        end_date=end,
        adjustment=adjustment,
        timeframe=timeframe,
    )
    if not records:
        raise ValueError(
            f"Fetcher returned zero records for {symbol} {start}..{end} "
            f"(adjustment={adjustment}). This is almost always a real bug "
            "(bad window, API failure, weekend-only range) — refusing to "
            "write a provenance.json for an empty bars set (R7.3 loud empties)."
        )

    # Import here so a broken canonical_bars import surfaces at the
    # first capture rather than at module load.
    from openbb_pine.testing.canonical_bars import sha256_bars

    bars_sha256 = sha256_bars(records)

    prov = _build_provenance(
        fixture_dir=fixture_dir,
        symbol=symbol,
        start=start,
        end=end,
        timeframe=timeframe,
        adjustment=adjustment,
        timezone=timezone,
        session=session,
        records=records,
        bars_sha256=bars_sha256,
        strategy_settings_path=strategy_settings_path,
    )

    # Deterministic JSON output — sort_keys + indent + trailing newline.
    # Matches the reshape tool's meta.json convention.
    prov_path.write_text(
        json.dumps(prov, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return prov_path


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Fetch fmp_cached bars for a fixture window, canonicalize + "
            "hash them, and write provenance.json into the fixture dir. "
            "Implements Session 1 of the hybrid-fixture-suite spec."
        ),
    )
    p.add_argument(
        "fixture_dir",
        type=Path,
        help="Fixture directory to write provenance.json into",
    )
    p.add_argument(
        "--symbol",
        required=True,
        help="Symbol including exchange prefix, e.g. NASDAQ:AAPL",
    )
    p.add_argument(
        "--start",
        required=True,
        help="Window start (ISO date, e.g. 2025-01-01)",
    )
    p.add_argument(
        "--end",
        required=True,
        help="Window end (ISO date, e.g. 2026-07-20)",
    )
    p.add_argument(
        "--timeframe",
        required=True,
        help="Chart timeframe (e.g. 1D)",
    )
    p.add_argument(
        "--adjustment",
        required=True,
        choices=["splits_only", "splits_and_dividends", "unadjusted"],
        help="fmp_cached adjustment mode",
    )
    p.add_argument(
        "--timezone",
        required=True,
        help="Exchange TZ used to align dates (e.g. America/New_York)",
    )
    p.add_argument(
        "--session",
        default="regular",
        choices=["regular", "extended"],
        help="Session type (default: regular)",
    )
    p.add_argument(
        "--tv-strategy-settings-json",
        type=Path,
        default=None,
        help=(
            "Optional path to a JSON file with the TV Strategy Tester "
            "properties used at capture. Embedded verbatim under "
            "'strategy_settings' in provenance.json (spec §4 D1.4)."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an existing provenance.json. Use deliberately: "
            "overwriting loses the prior capture's audit trail."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code.

    T201 (print-found) is suppressed intentionally — this is CLI
    output, not incidental debug logging.
    """
    parser = _build_argparser()
    args = parser.parse_args(argv)

    try:
        prov_path = capture(
            fixture_dir=args.fixture_dir,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            timeframe=args.timeframe,
            adjustment=args.adjustment,
            timezone=args.timezone,
            session=args.session,
            strategy_settings_path=args.tv_strategy_settings_json,
            force=args.force,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)  # noqa: T201
        return 1
    except FileExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)  # noqa: T201
        return 2
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)  # noqa: T201
        return 3

    print(f"Wrote {prov_path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
