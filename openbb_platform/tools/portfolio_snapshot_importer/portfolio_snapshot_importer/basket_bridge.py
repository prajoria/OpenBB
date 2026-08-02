"""Bridge helpers: portfolio_snapshot_importer → notebook basket.json.

Reads a snapshot from the SQLite store and emits the ``{"basket": [{...}]}``
shape that ``notebooks/portfolio/03-basket-xray-and-risk.ipynb`` (and every
downstream NB) consumes via ``.notebook_state/basket.json``.

Design rules:
- **Aggregate-only stdout.** This module NEVER prints per-row brokerage data.
- **Symbol renormalization.** Percent weights come from the snapshot's
  ``percent_of_account`` column (stored as fraction 0-1). If weights don't
  sum to ~1 (e.g. because Cash/Money-Market rows were excluded), they get
  renormalized so the downstream x-ray math still balances.
- **Cash-instrument filter.** SPAXX / FCASH / FDRXX / money-market tickers
  are excluded by default (they carry no sector for look-through; they
  distort HHI). Pass ``include_cash=True`` to keep them.
"""

from __future__ import annotations

import json
from pathlib import Path

from portfolio_snapshot_importer.store import PortfolioStore

_CASH_SYMBOLS = {
    "SPAXX**",
    "SPAXX",
    "FCASH**",
    "FCASH",
    "FDRXX**",
    "FDRXX",
    "FZDXX",
    "FZDXX**",
    "SPRXX",
    "SPRXX**",
}


def snapshot_to_basket(
    store: PortfolioStore,
    *,
    user_id: str,
    snapshot_date: str | None = None,
    include_cash: bool = False,
    account_number: str | None = None,
    top_n: int | None = None,
) -> dict:
    """Return a basket dict of shape ``{"basket": [{"symbol", "weight"}...],
    "metadata": {...}}``.

    - ``snapshot_date=None`` → picks the latest snapshot for ``user_id``.
    - ``account_number`` filters to one Fidelity account (else aggregates
      across all accounts belonging to the user).
    - ``top_n`` truncates to the largest N holdings by absolute value
      AFTER weight renormalization.
    """
    if snapshot_date is None:
        latest = store.latest_snapshot(user_id)
        if not latest:
            raise LookupError(f"no snapshots for user_id={user_id!r}")
        snap_id = latest["snapshot_id"]
        snap_date = latest["snapshot_date"]
    else:
        rows = store.list_snapshots(user_id=user_id)
        matches = [r for r in rows if r["snapshot_date"] == snapshot_date]
        if not matches:
            raise LookupError(f"no snapshot for user_id={user_id!r} on {snapshot_date}")
        snap_id = matches[0]["snapshot_id"]
        snap_date = snapshot_date

    positions = store.positions_for(snap_id)
    kept = []
    for p in positions:
        sym = (p["symbol"] or "").strip()
        if not sym:
            continue
        if not include_cash and sym in _CASH_SYMBOLS:
            continue
        if account_number and (p["account_number"] or "") != account_number:
            continue
        weight = p["percent_of_account"] or 0.0
        value = p["current_value"] or 0.0
        kept.append(
            {
                "symbol": sym,
                "weight": float(weight),
                "current_value": float(value),
                "account_number": p["account_number"],
            }
        )

    # Aggregate across accounts by symbol (a user may hold XYZ in both a
    # brokerage and an IRA).
    agg: dict[str, dict] = {}
    for row in kept:
        s = row["symbol"]
        if s not in agg:
            agg[s] = {"symbol": s, "weight": 0.0, "current_value": 0.0}
        agg[s]["weight"] += row["weight"]
        agg[s]["current_value"] += row["current_value"]

    items = sorted(agg.values(), key=lambda r: -r["current_value"])

    if top_n:
        items = items[:top_n]

    # Renormalize weights so they sum to 1.0 (cash excluded or top-N truncation
    # will pull the sum below 1 otherwise).
    total_w = sum(r["weight"] for r in items)
    if total_w > 0:
        for r in items:
            r["weight"] = r["weight"] / total_w

    basket = [{"symbol": r["symbol"], "weight": round(r["weight"], 6)} for r in items]

    return {
        "basket": basket,
        "metadata": {
            "source": "portfolio_snapshot_importer",
            "snapshot_id": snap_id,
            "snapshot_date": snap_date,
            "user_id": user_id,
            "account_number": account_number,
            "include_cash": include_cash,
            "top_n": top_n,
            "n_positions_in_snapshot": len(positions),
            "n_positions_in_basket": len(basket),
            "cash_symbols_excluded": None if include_cash else sorted(_CASH_SYMBOLS),
        },
    }


def write_basket_json(
    store: PortfolioStore,
    out_path: str | Path,
    **kwargs,
) -> dict:
    """Materialize ``snapshot_to_basket`` output to disk. Returns the dict."""
    basket = snapshot_to_basket(store, **kwargs)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(basket, indent=2), encoding="utf-8")
    return basket


# ---------------------------------------------------------------------------
# #1460: PII-safe preview renderer for notebook cells
# ---------------------------------------------------------------------------
_WEIGHT_BUCKETS = [
    (0.05, "<5%"),
    (0.15, "5-15%"),
    (0.30, "15-30%"),
    (float("inf"), ">30%"),
]


def _bucket_weight(w: float) -> str:
    """Bucket a fraction weight into a coarse label for pedagogy without
    leaking the precise concentration figure.
    """
    for threshold, label in _WEIGHT_BUCKETS:
        if w < threshold:
            return label
    return ">30%"


def redact_basket_preview(
    basket: dict,
    *,
    level: str = "aggregate",
) -> str:
    """Render a basket dict as human-readable stdout with PII-appropriate
    redaction. Never returns raw symbol/CUSIP/weight strings unless
    ``level='raw'`` is explicitly requested.

    Levels:
    - ``'aggregate'`` (default): counts only. No per-row output. Safe to
      commit into notebook outputs.
    - ``'bucketed'``: per-row output with symbol masked to ``SYM_i``,
      cusips/isins hidden, and weights bucketed into <5% / 5-15% /
      15-30% / >30%. Pedagogically useful ("you can be surprisingly
      concentrated") without leaking numbers.
    - ``'raw'``: pass-through, prints real symbols + weights. **Never
      run in a notebook that will be committed** — emits a warning to
      stderr on use. This is what the CLI shows for a live-driven
      allocation decision.

    All levels emit the same top-line metadata (snapshot count, position
    counts) since those are aggregate.
    """
    meta = basket.get("metadata", {})
    rows = basket.get("basket") or []
    lines: list[str] = []

    n_positions = meta.get("n_positions_in_basket", len(rows))
    n_in_snap = meta.get("n_positions_in_snapshot", "?")
    lines.append(
        f"basket contains {n_positions} positions (kept of {n_in_snap} in snapshot)"
    )
    lines.append("(cash rows excluded; weights renormalized to sum to 1)")

    if level == "aggregate":
        return "\n".join(lines)

    if level == "bucketed":
        lines.append("")
        lines.append(f"  {'Position':<10}{'Weight bucket':>20}")
        lines.append(f"  {'-'*10}{'-'*20}")
        for i, row in enumerate(rows, start=1):
            label = f"SYM_{i}"
            bucket = _bucket_weight(float(row.get("weight") or 0))
            lines.append(f"  {label:<10}{bucket:>20}")
        return "\n".join(lines)

    if level == "raw":
        import sys as _sys

        _sys.stderr.write(
            "WARNING: redact_basket_preview(level='raw') printed real "
            "portfolio data. Do NOT commit this notebook with executed "
            "outputs. See CLAUDE.md 'PII / private-data leak prevention'.\n"
        )
        lines.append("")
        lines.append(f"  {'Symbol':<12}{'Weight':>10}")
        lines.append(f"  {'-'*12}{'-'*10}")
        for row in rows:
            sym = str(row.get("symbol") or "?")
            w = float(row.get("weight") or 0) * 100.0
            lines.append(f"  {sym:<12}{w:>9.2f}%")
        return "\n".join(lines)

    raise ValueError(
        f"redact_basket_preview: unknown level={level!r} "
        "(expected 'aggregate', 'bucketed', or 'raw')"
    )
