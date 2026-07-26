"""SEC N-PORT look-through helper for the portfolio notebook series.

Backs the "flatten an ETF into its underlying holdings" step across
NB01 §3/§4, NB03 §3/§4, NB07 §5.5, and NB08 §5/§6. Replaces the
prior ``YFinanceEtfHoldingsRecordedFetcher`` / ``YFinanceBondLadderFetcher``
snapshot-scrape path with the SEC EDGAR Form N-PORT filing path
(``obb.etf.nport_disclosure(..., provider="sec")``). See GH #1426
(notebook consumer) + #1425 (provenance rationale).

Design notes
------------
* Every call disk-caches into ``.notebook_state/nport_cache/`` so a
  kernel-restart re-run does not re-hit SEC EDGAR for every ETF. The
  cache directory is gitignored — this is per-operator local state,
  same policy as the rest of ``.notebook_state``.
* N-PORT rows do NOT carry an equity ``symbol``; they carry issuer
  ``name`` + ``cusip`` + ``lei`` + ``isin``. Ticker resolution for the
  sector rollup goes through ``obb.equity.search(query=name,
  provider="sec")``, also disk-cached, and only runs on the top-N
  holdings by weight (the tail is bucketed as "Other (small)" — those
  rows contribute <0.05% each and don't move HHI / effective-N).
* Non-N-PORT filers (GLD grantor trust, DBC commodity pool) raise
  ``NportUnavailable`` — callers catch it and treat the position as
  opaque (no look-through possible for physical commodities anyway).
* Weights sum to ~1.0 per ETF; caller multiplies by the ETF's
  basket-weight to get effective-portfolio weight.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Cache root — every notebook resolves this relative to its own cwd
# (``notebooks/portfolio/``) via the module-level default. Callers can
# override for tests.
_DEFAULT_CACHE_ROOT = Path(".notebook_state") / "nport_cache"


class NportUnavailable(LookupError):
    """Symbol is not an SEC N-PORT filer (commodity grantor trust,
    non-'40-Act fund, ADR/foreign, or simply not yet in the fund map)."""


def _cache_dir(root: Optional[Path] = None) -> Path:
    d = Path(root) if root else _DEFAULT_CACHE_ROOT
    d.mkdir(parents=True, exist_ok=True)
    return d


def nport_holdings(symbol: str, cache_root: Optional[Path] = None) -> list[dict]:
    """Return the N-PORT holdings for ``symbol`` as a list of dicts.

    Each row: ``{"name", "symbol", "weight", "cusip", "asset_category",
    "issuer_category", "country"}``. ``symbol`` is usually ``None`` on
    N-PORT rows (issuer identified by CUSIP/LEI/ISIN, not ticker).
    Weights sum to ~1.0.

    Raises :class:`NportUnavailable` for non-N-PORT filers.
    """
    sym = symbol.upper()
    path = _cache_dir(cache_root) / f"holdings_{sym}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    from openbb import obb

    try:
        result = obb.etf.nport_disclosure(symbol=sym, provider="sec")
    except Exception as exc:  # noqa: BLE001 — normalize to our sentinel
        msg = str(exc)
        if "No N-Port records" in msg or "not found" in msg.lower():
            raise NportUnavailable(
                f"{sym}: not an N-PORT filer (commodity grantor trust / "
                f"non-'40-Act fund / unseeded in sec_nport_fund_map)"
            ) from exc
        raise

    rows = [
        {
            "name": h.name,
            "symbol": h.symbol,  # almost always None for N-PORT
            "weight": float(h.weight or 0.0),
            "cusip": h.cusip,
            "asset_category": h.asset_category,
            "issuer_category": h.issuer_category,
            "country": h.country,
        }
        for h in result.results
    ]
    path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return rows


def _resolve_name_to_ticker(name: str, cache: dict) -> Optional[str]:
    """Best-effort SEC EDGAR search of issuer name → US-listed ticker."""
    if name in cache:
        return cache[name]
    from openbb import obb

    ticker: Optional[str] = None
    # Try the name as-is; if that fails, strip common suffixes.
    for query in (name, _strip_corp_suffix(name)):
        if not query:
            continue
        try:
            hits = obb.equity.search(query=query, provider="sec").results
        except Exception:
            hits = []
        if hits:
            ticker = hits[0].symbol
            break
    cache[name] = ticker
    return ticker


_SUFFIXES = (
    ", Inc.", ", Inc", " Inc.", " Inc", " Corp.", " Corp", " Corporation",
    " Co.", " Co", " Ltd.", " Ltd", " PLC", " plc", " LLC", " N.V.", " NV",
    " S.A.", " SA", " AG", " AB", " SE", " KGaA",
)


def _strip_corp_suffix(name: str) -> str:
    for suf in _SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)].strip()
    return name


def sector_rollup(
    holdings: list[dict],
    weight_scale: float = 1.0,
    top_n_resolve: int = 60,
    cache_root: Optional[Path] = None,
) -> tuple[dict[str, float], dict[str, int]]:
    """Bucket N-PORT holdings into a sector-weight dict.

    * Top ``top_n_resolve`` holdings by weight: resolve name→ticker via
      SEC search (cached), then ticker→sector via ``fmp_cached``
      ``equity.profile`` (cached in-process only — cheap enough).
    * The tail: bucketed by ``asset_category`` / ``issuer_category``
      (bonds → "Fixed Income"; the equity remainder → "Other (small)").
    * Returns ``(sector_weights, counts)`` where ``sector_weights`` sums
      to ``weight_scale * sum(row_weights)`` and ``counts`` records
      how many rows fell into each bucket for a transparency print.
    """
    from openbb import obb

    cache_path = _cache_dir(cache_root) / "name_to_ticker.json"
    name_cache: dict[str, Optional[str]] = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else {}
    )

    sector_weights: dict[str, float] = {}
    counts: dict[str, int] = {}
    profile_cache: dict[str, str] = {}

    sorted_holdings = sorted(holdings, key=lambda r: -(r.get("weight") or 0.0))

    for idx, h in enumerate(sorted_holdings):
        w = (h.get("weight") or 0.0) * weight_scale
        if w <= 0:
            continue

        # Fixed-income rows (bond ETFs) — bucket by category, no resolve
        asset_cat = h.get("asset_category") or ""
        if asset_cat in ("DBT", "ABS-APCP", "ABS-CBDO", "ABS-MBS", "ABS-O",
                         "ABS-CDO", "ABS-CMBS", "ABS-RMBS", "LOAN"):
            bucket = "Fixed Income"
        elif asset_cat == "STIV":
            bucket = "Short-Term / Cash"
        elif asset_cat == "RE":
            bucket = "Real Estate (direct)"
        elif asset_cat == "COMM":
            bucket = "Commodity"
        elif idx < top_n_resolve and h.get("name"):
            ticker = _resolve_name_to_ticker(h["name"], name_cache)
            sector: Optional[str] = None
            if ticker:
                if ticker in profile_cache:
                    sector = profile_cache[ticker]
                else:
                    try:
                        prof = obb.equity.profile(
                            symbol=ticker, provider="fmp_cached"
                        ).results
                        sector = getattr(prof[0], "sector", None) if prof else None
                    except Exception:
                        sector = None
                    profile_cache[ticker] = sector or "Unknown"
            bucket = sector or "Unknown"
        else:
            bucket = "Other (small)"

        sector_weights[bucket] = sector_weights.get(bucket, 0.0) + w
        counts[bucket] = counts.get(bucket, 0) + 1

    cache_path.write_text(json.dumps(name_cache, indent=1), encoding="utf-8")
    return sector_weights, counts


def effective_positions(
    basket: list[dict],
    equity_etfs: set[str],
    bond_etfs: set[str],
    commodity_trusts: set[str],
    top_n_per_etf: int = 100,
    cache_root: Optional[Path] = None,
) -> tuple[dict[str, float], list[str], list[tuple[str, str]]]:
    """Flatten a basket into effective positions via N-PORT.

    Returns ``(effective_dict, non_nport_symbols, opaque_reasons)`` where:

    * ``effective_dict`` maps the display key (equity: issuer ``name``
      for N-PORT rows, ETF ticker for opaque commodities; fixed-income:
      ``BOND_<ETF>``) → cumulative weight in the basket.
    * ``non_nport_symbols`` lists symbols that raised
      :class:`NportUnavailable` and were treated as opaque.
    * ``opaque_reasons`` is a list of ``(symbol, reason)`` for the report.

    ``top_n_per_etf`` truncates each ETF's per-issuer roll-up to its
    top-N by weight — the tail (typically <0.05% each) collapses into
    a single ``TAIL_<ETF>`` row to keep HHI / effective-N honest.
    """
    effective: dict[str, float] = {}
    non_nport: list[str] = []
    opaque: list[tuple[str, str]] = []

    for pos in basket:
        sym = pos.get("symbol") or pos.get("ticker")
        w = float(pos.get("weight") or 0.0)
        if sym in commodity_trusts:
            effective[sym] = effective.get(sym, 0.0) + w
            opaque.append((sym, "commodity trust — no look-through"))
            continue

        if sym in equity_etfs or sym in bond_etfs:
            try:
                rows = nport_holdings(sym, cache_root=cache_root)
            except NportUnavailable as exc:
                non_nport.append(sym)
                effective[sym] = effective.get(sym, 0.0) + w
                opaque.append((sym, str(exc)))
                continue

            # Sort by weight desc, keep top-N, collapse tail
            rows_sorted = sorted(rows, key=lambda r: -(r.get("weight") or 0.0))
            top = rows_sorted[:top_n_per_etf]
            tail = rows_sorted[top_n_per_etf:]

            for r in top:
                rw = (r.get("weight") or 0.0)
                if rw <= 0:
                    continue
                if sym in bond_etfs:
                    # Bond ETFs — keep as one opaque bond bucket per ETF
                    key = f"BOND_{sym}"
                else:
                    key = r.get("name") or r.get("cusip") or f"UNK_{sym}"
                effective[key] = effective.get(key, 0.0) + w * rw

            tail_w = sum((r.get("weight") or 0.0) for r in tail)
            if tail_w > 0:
                key = f"TAIL_{sym}"
                effective[key] = effective.get(key, 0.0) + w * tail_w
            continue

        # Not an ETF — pass through as-is (single-name equity)
        effective[sym] = effective.get(sym, 0.0) + w

    return effective, non_nport, opaque
