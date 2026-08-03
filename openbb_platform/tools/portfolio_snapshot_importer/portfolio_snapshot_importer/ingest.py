"""Ingest algorithm — walks a folder or takes a single file, parses each
Fidelity CSV, and lands snapshots + positions rows into a ``PortfolioStore``.

Idempotent: re-importing the same file is a no-op. Bad rows / bad files are
logged and skipped, never crashed — the runbook is "make progress, surface
the miss in the report".
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from portfolio_snapshot_importer.filename import (
    FilenameParseError,
    parse_fidelity_filename,
)
from portfolio_snapshot_importer.store import SCHEMA_VERSION, PortfolioStore

# The 17 columns Fidelity ships (plus optional user_id column). This is
# the OLD format canonical form — the parser reads this shape from row
# dicts. The CURRENT Fidelity format uses different capitalization + a
# few merged/split columns; ``_HEADER_ALIASES`` maps current -> old so
# an old-format CSV and a current-format CSV both import cleanly.
# See docs/superpowers/specs/2026-08-03-fidelity-positions-csv-schema.md.
_EXPECTED_COLS = {
    "Account number",
    "Account name",
    "Symbol",
    "Description",
    "Quantity",
    "Last price",
    "Last price change",
    "Current value",
    "Today's gain/loss dollar",
    "Today's gain/loss percent",
    "Total gain/loss dollar",
    "Total gain/loss percent",
    "Percent of account",
    "Cost basis total",
    "Average cost basis",
    "Type",
}

# Current-format header -> canonical (old-format) header. Applied before
# the ``_EXPECTED_COLS`` presence check so current-format exports
# satisfy the header-completeness guard. The two split-column cases
# (``Account Name / Number``, ``Last Price Change (%|$)``) get special
# handling in ``_normalize_current_headers`` — the alias map alone can't
# split one column into two.
_HEADER_ALIASES: dict[str, str] = {
    # Current -> canonical for like-for-like renames + capitalization drift.
    "Symbol": "Symbol",
    "Description": "Description",
    "Quantity": "Quantity",
    "Last Price": "Last price",
    "Current Value": "Current value",
    "Today's Gain/Loss ($)": "Today's gain/loss dollar",
    "Today's Gain/Loss (%)": "Today's gain/loss percent",
    "Total Gain/Loss ($)": "Total gain/loss dollar",
    "Total Gain/Loss (%)": "Total gain/loss percent",
    "Percent of Portfolio": "Percent of account",
    "Total Cost Basis": "Cost basis total",
    "Cost Basis Per Share": "Average cost basis",
}


def _normalize_current_headers(
    header: list[str], rows: list[dict[str, str]]
) -> tuple[list[str], list[dict[str, str]]]:
    """Return (canonical_header, canonical_rows) from a current-format CSV.

    Handles three flavors of schema drift between OLD and CURRENT Fidelity
    Positions download formats:

    1. **Direct rename** — apply ``_HEADER_ALIASES`` to columns whose only
       change is capitalization / wording.
    2. **Split column** — ``Last Price Change ($)`` + ``Last Price Change
       (%)`` collapses to the old ``Last price change`` (dollar value
       wins; percent silently dropped — parser doesn't consume it anyway).
    3. **Merged column** — ``Account Name / Number`` splits into
       ``Account name`` + ``Account number`` via a regex on the descriptor
       (``Individual - X12345678`` -> name=Individual, number=X12345678).

    If the input header is already the OLD format (already contains
    ``Account number``, etc.), this is a no-op — canonical.
    """
    # Fast path: already canonical.
    if "Account number" in header and "Account name" in header:
        return header, rows

    # Rename direct-alias columns in every row + rebuild header.
    canonical_header: list[str] = []
    for col in header:
        canonical_header.append(_HEADER_ALIASES.get(col, col))

    canonical_rows: list[dict[str, str]] = []
    for r in rows:
        new_r: dict[str, str] = {}
        for k, v in r.items():
            new_r[_HEADER_ALIASES.get(k, k)] = v

        # Split "Last Price Change ($)" + "%" into the old single column.
        # We prefer the dollar variant since the parser reads it as money.
        if "Last Price Change ($)" in r or "Last Price Change (%)" in r:
            dollar = r.get("Last Price Change ($)") or ""
            new_r["Last price change"] = dollar
            new_r.pop("Last Price Change ($)", None)
            new_r.pop("Last Price Change (%)", None)

        # Split "Account Name / Number" into "Account name" +
        # "Account number". Format is typically:
        #   "Individual - X12345678"  or
        #   "Roth IRA - X87654321"
        # We split on the last " - " so descriptors with " - " in them
        # (rare but possible) still give us the trailing account number.
        merged = r.get("Account Name / Number")
        if merged is not None:
            parts = merged.rsplit(" - ", 1)
            if len(parts) == 2:
                new_r["Account name"] = parts[0].strip()
                new_r["Account number"] = parts[1].strip()
            else:
                # Unsplittable; put the whole thing under account_name
                # and leave account_number empty (parser guards against it).
                new_r["Account name"] = merged.strip()
                new_r["Account number"] = ""
            new_r.pop("Account Name / Number", None)

        # Current format has no ``Type`` column (dropped from the schema).
        # Synthesize an empty string so the parser's ``r.get("Type")``
        # + the _EXPECTED_COLS presence check both succeed. Downstream
        # reads normalize empty -> None.
        if "Type" not in new_r:
            new_r["Type"] = ""

        canonical_rows.append(new_r)

    # Rebuild the canonical header to include the split columns.
    if "Account Name / Number" in header:
        canonical_header = [
            c for c in canonical_header if c not in ("Account Name / Number",)
        ]
        canonical_header = ["Account number", "Account name"] + canonical_header
    if "Last Price Change ($)" in header or "Last Price Change (%)" in header:
        canonical_header = [
            c
            for c in canonical_header
            if c not in ("Last Price Change ($)", "Last Price Change (%)")
        ]
        canonical_header.append("Last price change")

    # Current format has no Type column; we synthesize an empty per-row
    # value in the loop above, so also add it to the canonical header
    # so the _EXPECTED_COLS presence check accepts current-format files.
    if "Type" not in canonical_header:
        canonical_header.append("Type")

    return canonical_header, canonical_rows


@dataclass
class IngestResult:
    """One-file outcome — informs the aggregate report and stdout summary."""

    path: Path
    status: str  # "imported" | "duplicate" | "skipped_unrecognized" | "skipped_no_positions" | "error"
    snapshot_id: str | None = None
    snapshot_date: str | None = None
    user_id: str | None = None
    row_count_raw: int = 0
    row_count_kept: int = 0
    row_count_skipped: int = 0
    message: str = ""


@dataclass
class IngestReport:
    """Aggregate outcome of ``import_file`` or ``import_folder``."""

    results: list[IngestResult] = field(default_factory=list)

    @property
    def imported(self) -> int:
        """Count of successfully imported files."""
        return sum(1 for r in self.results if r.status == "imported")

    @property
    def duplicates(self) -> int:
        """Count of files skipped as duplicates (already in the store)."""
        return sum(1 for r in self.results if r.status == "duplicate")

    @property
    def errors(self) -> int:
        """Count of files that hit an error during import."""
        return sum(1 for r in self.results if r.status == "error")

    @property
    def skipped(self) -> int:
        """Count of files skipped for any reason (unrecognized / empty / etc.)."""
        return sum(1 for r in self.results if r.status.startswith("skipped_"))


# ---------------------------------------------------------------------------
# CSV parsing helpers
# ---------------------------------------------------------------------------
def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return (header, rows) with UTF-8 BOM stripped from the first header cell."""
    text = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    header = list(rows[0])
    if header and header[0].startswith("﻿"):
        header[0] = header[0].lstrip("﻿")
    body = []
    for r in rows[1:]:
        # Trailing blank lines and Fidelity's footer notes have <3 non-empty cells.
        if len([c for c in r if c.strip()]) < 3:
            continue
        body.append(dict(zip(header, r)))
    return header, body


def _parse_money(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.strip()
    if not t or t in {"n/a", "N/A", "--", "-"}:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg = True
        t = t[1:-1]
    t = t.replace("$", "").replace(",", "").replace("+", "").strip()
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _parse_percent(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.strip().replace("%", "").replace("+", "").replace(",", "")
    if not t or t in {"n/a", "N/A", "--", "-"}:
        return None
    try:
        # Store as fraction of one, matching the rest of the ecosystem
        # (percent_of_account 0.12 = 12% of account).
        return float(t) / 100.0
    except ValueError:
        return None


def _parse_qty(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if not t or t in {"n/a", "N/A", "--", "-"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def import_file(
    path: str | Path,
    *,
    store: PortfolioStore,
    user_id_fallback: str | None = None,
) -> IngestResult:
    """Import one Fidelity CSV into ``store``. Idempotent on (sha256, user_id).

    Filename supplies date + (optionally) user_id. If the filename omits the
    user suffix and the CSV has no ``user_id`` column, ``user_id_fallback``
    is used; otherwise the file is skipped with ``skipped_no_user``.
    """
    p = Path(path)
    if not p.is_file():
        return IngestResult(p, "error", message=f"not a file: {p}")

    try:
        snap_date, user_from_name = parse_fidelity_filename(p.name)
    except FilenameParseError as exc:
        return IngestResult(p, "skipped_unrecognized", message=str(exc))

    try:
        header, rows = _read_csv(p)
    except OSError as exc:
        return IngestResult(p, "error", message=f"read failed: {exc}")

    if not header:
        return IngestResult(p, "skipped_no_positions", message="empty file")

    # Normalize CURRENT-format headers to the OLD canonical form so
    # exports from either era import cleanly. No-op on old-format files.
    header, rows = _normalize_current_headers(header, rows)

    missing = _EXPECTED_COLS - set(header)
    if missing:
        return IngestResult(
            p,
            "error",
            message=f"missing required columns: {sorted(missing)}",
        )

    # Resolve user_id: filename > in-file column > caller fallback
    user_id = user_from_name
    if not user_id:
        first_with_user = next(
            (r.get("user_id") for r in rows if r.get("user_id")), None
        )
        user_id = first_with_user or user_id_fallback
    if not user_id:
        return IngestResult(
            p,
            "skipped_unrecognized",
            snapshot_date=snap_date.isoformat(),
            message="user_id absent in filename and file; pass --user_id or add suffix",
        )

    sha = _sha256_of(p)
    existing = store.snapshot_exists(sha, user_id)
    if existing:
        return IngestResult(
            p,
            "duplicate",
            snapshot_id=existing,
            snapshot_date=snap_date.isoformat(),
            user_id=user_id,
            message=f"already imported as {existing[:12]}…",
        )

    snapshot_id = hashlib.blake2b(
        f"{sha}|{user_id}".encode(), digest_size=16
    ).hexdigest()

    row_count_raw = len(rows)
    kept: list[dict] = []
    skipped = 0
    for i, r in enumerate(rows, start=2):  # 2 = data starts on line 2
        symbol = (r.get("Symbol") or "").strip()
        account_number = (r.get("Account number") or "").strip()
        if not symbol or not account_number:
            skipped += 1
            continue
        kept.append(
            {
                "snapshot_id": snapshot_id,
                "snapshot_date": snap_date.isoformat(),
                "user_id": user_id,
                "account_number": account_number,
                "account_name": (r.get("Account name") or "").strip() or None,
                "basket_name": None,  # v1: no basket assignment
                "symbol": symbol,
                "description": (r.get("Description") or "").strip() or None,
                "type": (r.get("Type") or "").strip() or None,
                "quantity": _parse_qty(r.get("Quantity")),
                "last_price": _parse_money(r.get("Last price")),
                "last_price_change": _parse_money(r.get("Last price change")),
                "current_value": _parse_money(r.get("Current value")),
                "today_gain_loss_dollar": _parse_money(
                    r.get("Today's gain/loss dollar")
                ),
                "today_gain_loss_percent": _parse_percent(
                    r.get("Today's gain/loss percent")
                ),
                "total_gain_loss_dollar": _parse_money(r.get("Total gain/loss dollar")),
                "total_gain_loss_percent": _parse_percent(
                    r.get("Total gain/loss percent")
                ),
                "percent_of_account": _parse_percent(r.get("Percent of account")),
                "cost_basis_total": _parse_money(r.get("Cost basis total")),
                "average_cost_basis": _parse_money(r.get("Average cost basis")),
                "raw_row_number": i,
            }
        )

    store.insert_snapshot(
        {
            "snapshot_id": snapshot_id,
            "snapshot_date": snap_date.isoformat(),
            "user_id": user_id,
            "source_filename": p.name,
            "source_sha256": sha,
            "row_count_raw": row_count_raw,
            "row_count_kept": len(kept),
            "row_count_skipped": skipped,
            "schema_version": SCHEMA_VERSION,
        }
    )
    store.insert_positions(kept)

    return IngestResult(
        p,
        "imported",
        snapshot_id=snapshot_id,
        snapshot_date=snap_date.isoformat(),
        user_id=user_id,
        row_count_raw=row_count_raw,
        row_count_kept=len(kept),
        row_count_skipped=skipped,
    )


def import_folder(
    folder: str | Path,
    *,
    store: PortfolioStore,
    user_id_fallback: str | None = None,
) -> IngestReport:
    """Scan a folder recursively for ``Portfolio_Positions_*.csv`` and import each."""
    root = Path(folder)
    report = IngestReport()
    for path in sorted(root.rglob("Portfolio_Positions_*.csv")):
        report.results.append(
            import_file(path, store=store, user_id_fallback=user_id_fallback)
        )
    return report


def import_files(
    paths: Iterable[str | Path],
    *,
    store: PortfolioStore,
    user_id_fallback: str | None = None,
) -> IngestReport:
    """Import an explicit list of files."""
    report = IngestReport()
    for path in paths:
        report.results.append(
            import_file(path, store=store, user_id_fallback=user_id_fallback)
        )
    return report
