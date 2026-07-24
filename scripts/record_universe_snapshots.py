#!/usr/bin/env python
"""Sweep-record all snapshots for the notebook-series universe.

Part of sub-epic #1374 / PR-3 (#1377). This is the ONE hands-on step
Daisy runs on her machine to produce the ~120 snapshots that unblock
Phase B notebook code fulfillment (blocker #1373).

Usage::

    .\\.venv_portfolio\\Scripts\\Activate.ps1
    python scripts/record_universe_snapshots.py

Optional flags::

    --force                 re-record even fresh snapshots (>7d default)
    --stale-days N          override the freshness threshold (default 7)
    --only TICKER1,TICKER2  restrict the sweep to these tickers
    --skip-endpoints A,B    skip named endpoints (yahoo_equity_quote, ...)
    --dry-run               print the (endpoint, ticker) plan and exit

Design notes:

- Reads ``notebooks/portfolio/UNIVERSE.md``. Only lines inside the
  ``universe`` fenced code block, ignoring blank + comment lines.
- Routes each ticker to endpoints per the classification in
  ``TICKER_ENDPOINTS`` (equities → quote+info; equity ETFs → quote+
  info+etf-holdings; bond ETFs → quote+info+bond-etf-holdings;
  physical commodities → quote+info only). Bond-ETF routing to the
  DOM-scrape recording (``yahoo_bond_etf_holdings``) fixes the
  routing bug from PR #1382 review issue #2.
- Skip-if-fresh: compares the snapshot's persisted ``captured_at``
  (not the file mtime, which is reset by git clone/copy) against
  ``--stale-days``. Matches the documented behavior; fixes issue #3.
- Progress log written to ``.scrape_record_sweep.log`` under the repo
  root; ``.gitignore`` excludes it.
- On per-capture failure (Playwright timeout, XHR miss, hollow
  response, etc.), log and continue — don't abort the whole sweep.
  Coverage report at end makes gaps visible. **The recording scripts
  raise RecordingCaptureError on missed XHRs so hollow snapshots
  never land in the OK bucket** — fixes issue #1 from the sweep side
  (recording-side fix in PR #1381).
- Explicit ``n/a`` rows are emitted for (endpoint, ticker) pairs the
  routing skips, so the coverage matrix cell renders ``--`` instead
  of blank — fixes issue #6.
- Exit code is 0 only if every planned capture ended in ``recorded``,
  ``fresh_skip``, or ``n/a``. Any ``failed`` row exits non-zero for
  CI / wrapper detection — fixes issue #5.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_MD = REPO_ROOT / "notebooks" / "portfolio" / "UNIVERSE.md"
LOG_FILE = REPO_ROOT / ".scrape_record_sweep.log"

ALL_ENDPOINTS = (
    "yahoo_equity_quote",
    "yahoo_equity_info",
    "yahoo_etf_holdings",
    "yahoo_bond_etf_holdings",
)

# Ticker → endpoints classification (fixes review issue #2).
# Rules:
#   - every ticker gets quote + info
#   - equity ETFs additionally get yahoo_etf_holdings
#   - bond ETFs additionally get yahoo_bond_etf_holdings (DOM-scrape)
#   - physical commodity trusts (GLD) get quote+info only — no equity holdings
EQUITY_ETFS = frozenset({"QQQ", "VTI", "VNQ", "SPY", "DIA", "IWM", "VOO", "VEA"})
BOND_ETFS = frozenset({"BND"})  # add AGG, BSV, VCLT, LQD, HYG as universe grows
COMMODITY_TRUSTS = frozenset({"GLD"})  # no holdings-list endpoint on Yahoo


def endpoints_for(ticker: str) -> list[str]:
    base = ["yahoo_equity_quote", "yahoo_equity_info"]
    if ticker in EQUITY_ETFS:
        return base + ["yahoo_etf_holdings"]
    if ticker in BOND_ETFS:
        return base + ["yahoo_bond_etf_holdings"]
    # equities + commodity trusts get base only
    return base


@dataclass
class Result:
    endpoint: str
    ticker: str
    status: str  # "recorded" | "fresh_skip" | "failed" | "n/a"
    path: str = ""
    error: str = ""
    elapsed_s: float = 0.0


@dataclass
class Report:
    plan_size: int = 0
    recorded: list[Result] = field(default_factory=list)
    fresh_skips: list[Result] = field(default_factory=list)
    failed: list[Result] = field(default_factory=list)
    na: list[Result] = field(default_factory=list)

    def add(self, r: Result) -> None:
        {
            "recorded": self.recorded,
            "fresh_skip": self.fresh_skips,
            "failed": self.failed,
            "n/a": self.na,
        }[r.status].append(r)

    def matrix(self, endpoints: tuple[str, ...]) -> str:
        """Compact endpoint × ticker table for the closing summary."""
        by_ticker: dict[str, dict[str, str]] = {}
        for r in self.recorded + self.fresh_skips + self.failed + self.na:
            by_ticker.setdefault(r.ticker, {})[r.endpoint] = {
                "recorded": "OK",
                "fresh_skip": "FR",
                "failed": "!!",
                "n/a": "--",
            }[r.status]
        # Short endpoint labels for compact width
        labels = {
            "yahoo_equity_quote": "quote",
            "yahoo_equity_info": "info",
            "yahoo_etf_holdings": "etf-hold",
            "yahoo_bond_etf_holdings": "bond-hold",
        }
        header = f"{'ticker':<8}" + "".join(
            f"{labels.get(e, e):>12}" for e in endpoints
        )
        lines = [header, "-" * len(header)]
        for t in sorted(by_ticker):
            row = f"{t:<8}"
            for e in endpoints:
                row += f"{by_ticker[t].get(e, ''):>12}"
            lines.append(row)
        return "\n".join(lines)


def parse_universe() -> list[str]:
    if not UNIVERSE_MD.exists():
        sys.exit(f"UNIVERSE.md not found at {UNIVERSE_MD}")
    text = UNIVERSE_MD.read_text(encoding="utf-8")
    match = re.search(r"```universe\n(.*?)```", text, re.DOTALL)
    if not match:
        sys.exit("UNIVERSE.md: no ```universe fenced block found")
    tickers: list[str] = []
    for line in match.group(1).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        tickers.append(s)
    if not tickers:
        sys.exit("UNIVERSE.md: universe block is empty")
    return tickers


def build_plan(
    tickers: list[str],
    only: set[str] | None,
    skip_endpoints: set[str],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (plan, skipped) — the runnable plan + explicit n/a rows.

    n/a rows are (endpoint, ticker) pairs where the ticker's classification
    doesn't include that endpoint (e.g. AAPL has no yahoo_etf_holdings).
    They surface as ``--`` in the coverage matrix rather than blank cells
    (fixes review issue #6).
    """
    plan: list[tuple[str, str]] = []
    na: list[tuple[str, str]] = []
    for ticker in tickers:
        if only and ticker not in only:
            continue
        applicable = set(endpoints_for(ticker))
        for endpoint in ALL_ENDPOINTS:
            if endpoint in skip_endpoints:
                continue
            if endpoint in applicable:
                plan.append((endpoint, ticker))
            else:
                na.append((endpoint, ticker))
    return plan, na


def read_snapshot_captured_at(path: Path) -> datetime | None:
    """Read ``captured_at`` from the on-disk envelope (not file mtime).

    Fixes review issue #3 — file mtime is reset by git clone / copy, so a
    genuinely-stale snapshot could look fresh. The envelope's
    ``captured_at`` is the truth.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_captured = data.get("captured_at")
    if not raw_captured:
        return None
    try:
        # Envelope timestamps are ISO-8601 with tz (UTC)
        return datetime.fromisoformat(raw_captured)
    except (TypeError, ValueError):
        return None


def is_fresh(cfg, endpoint: str, ticker: str, stale_days: int) -> tuple[bool, Path]:
    from scrape_record.config import snapshot_path

    path = snapshot_path(cfg, endpoint, ticker)
    if not path.exists():
        return False, path
    captured_at = read_snapshot_captured_at(path)
    if captured_at is None:
        return False, path  # snapshot with no captured_at → treat as stale
    return (datetime.now(timezone.utc) - captured_at) < timedelta(days=stale_days), path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-record even snapshots newer than --stale-days.",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=7,
        help="Snapshots older than N days re-record (default 7).",
    )
    parser.add_argument(
        "--only", type=str, default="", help="Comma-separated ticker subset to record."
    )
    parser.add_argument(
        "--skip-endpoints",
        type=str,
        default="",
        help="Comma-separated endpoints to skip.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan and exit; do not record."
    )
    args = parser.parse_args()

    tickers = parse_universe()
    only = set(t.strip().upper() for t in args.only.split(",") if t.strip()) or None
    skip_endpoints = set(s.strip() for s in args.skip_endpoints.split(",") if s.strip())

    plan, na_pairs = build_plan(tickers, only, skip_endpoints)
    report = Report(plan_size=len(plan))
    # Emit explicit n/a rows (fixes issue #6)
    for endpoint, ticker in na_pairs:
        report.add(Result(endpoint=endpoint, ticker=ticker, status="n/a"))

    print(f"Universe:  {len(tickers)} tickers ({UNIVERSE_MD})")
    print(f"Plan:      {len(plan)} (endpoint, ticker) pairs to record")
    print(f"           {len(na_pairs)} n/a pairs (endpoint not applicable)")
    print(f"Force:     {args.force}")
    print(f"Stale:     >{args.stale_days} days (by envelope captured_at, not mtime)")
    if only:
        print(f"Only:      {sorted(only)}")
    if skip_endpoints:
        print(f"Skip:      {sorted(skip_endpoints)}")
    print()

    if args.dry_run:
        for endpoint, ticker in plan:
            print(f"  RECORD    {endpoint:<28} {ticker}")
        for endpoint, ticker in na_pairs:
            print(f"  n/a       {endpoint:<28} {ticker}")
        print()
        print(f"Total: {len(plan)} captures planned; {len(na_pairs)} n/a.")
        return

    # Import here so --help / --dry-run don't need Playwright
    from scrape_record.config import load_config
    from scrape_record.record import run_recording

    cfg = load_config()
    print(f"Config:\n{cfg.summary()}\n")
    print("Starting sweep. Headed Chromium will open — accept the Yahoo cookie")
    print("banner once (if present); the persistent profile remembers it after.\n")

    log_fh = LOG_FILE.open("a", encoding="utf-8")
    log_fh.write(f"\n=== sweep started {datetime.now(timezone.utc).isoformat()} ===\n")

    for i, (endpoint, ticker) in enumerate(plan, start=1):
        pfx = f"[{i:>3}/{len(plan)}] {endpoint:<28} {ticker:<8}"
        if not args.force:
            fresh, _ = is_fresh(cfg, endpoint, ticker, args.stale_days)
            if fresh:
                report.add(
                    Result(endpoint=endpoint, ticker=ticker, status="fresh_skip")
                )
                print(f"{pfx}  fresh — skip")
                continue

        start = time.perf_counter()
        try:
            out_path = run_recording(cfg, endpoint, ticker)
            elapsed = time.perf_counter() - start
            r = Result(
                endpoint=endpoint,
                ticker=ticker,
                status="recorded",
                path=str(out_path),
                elapsed_s=elapsed,
            )
            print(f"{pfx}  ok  ({elapsed:5.1f}s)  -> {out_path.name}")
        except Exception as exc:  # pragma: no cover — live-browser failure modes
            elapsed = time.perf_counter() - start
            r = Result(
                endpoint=endpoint,
                ticker=ticker,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:200],
                elapsed_s=elapsed,
            )
            print(f"{pfx}  FAIL  ({elapsed:5.1f}s)  {r.error[:60]}")
            log_fh.write(
                f"{datetime.now(timezone.utc).isoformat()}  "
                f"{endpoint} {ticker} FAILED: {r.error}\n"
            )
        report.add(r)

    log_fh.close()

    endpoints_seen = tuple(e for e in ALL_ENDPOINTS if e not in skip_endpoints)
    print()
    print("=" * 60)
    print(f"Coverage matrix ({len(plan)} planned, {len(na_pairs)} n/a):")
    print(report.matrix(endpoints_seen))
    print()
    print(f"  recorded:    {len(report.recorded)}")
    print(f"  fresh skip:  {len(report.fresh_skips)}")
    print(f"  failed:      {len(report.failed)}")
    print(f"  n/a (skip):  {len(report.na)}")
    if report.failed:
        print()
        print(f"Failures logged to {LOG_FILE}. Re-run with `--only <ticker>` to retry.")

    # Exit non-zero if anything failed — lets wrappers / CI detect partial failure
    # without parsing stdout (fixes review issue #5).
    sys.exit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
