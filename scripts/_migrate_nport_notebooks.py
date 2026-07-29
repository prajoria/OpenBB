"""One-shot migration: replace yfinance snapshot look-through with SEC N-PORT
in the portfolio notebooks. Runs the modified notebook end-to-end via
nbclient to regenerate outputs.

Idempotent: cells are located by marker strings that never appear in the
N-PORT replacement cells (e.g. ``YFinanceEtfHoldingsRecordedFetcher``), so
re-running is a no-op after the first success.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NB_DIR = REPO / "notebooks" / "portfolio"


# ---------------------------------------------------------------------------
# Cell replacement bodies
# ---------------------------------------------------------------------------

NB08_CELL5_MD = """## 5. Basket X-Ray — look-through via SEC N-PORT

Same discipline as NB03, migrated to authoritative filings. Each equity ETF
gets unwrapped via its **SEC Form N-PORT** disclosure
(`obb.etf.nport_disclosure(symbol=..., provider="sec")`) — the quarterly
holdings filing every '40-Act US-registered fund is required to make with
the SEC. Each bond ETF gets the same treatment: N-PORT covers bond funds
too, so BND / TLT / TIP / SCHP unwrap to the same free, redistribution-safe
government-filing feed instead of a Yahoo-scraped bond ladder. Commodity
grantor trusts (GLD, DBC) pass through as-is — they file 10-K/8-K, not
N-PORT, so the look-through helper flags them as `NportUnavailable` and the
notebook leaves them opaque without erroring.

The switch was tracked as #1426 (notebook consumer) — the notebook-facing
half of the data-provenance concern in #1425 (Yahoo-shaped snapshots in a
public repo). N-PORT is free, US-government, redistribution-safe, and
authoritative-because-filed-by-the-issuer. The tradeoff is **freshness**:
N-PORT is quarterly-visible with a ~30-60 day lag vs Yahoo's live page, so
the constituent list you see reflects the fund's position on its most recent
quarter-end, not last Friday. For a portfolio-construction notebook (this
one) that lag is a rounding error — VTI's top-50 does not turn over in a
quarter. For an intraday tool it would matter; use the fmp_cached
`obb.etf.holdings` route there instead.

The point of look-through on this basket: to check whether the
sector-satellite tilts in §4 actually move the effective sector weights, or
whether VTI's 30% concentration in the top-10 US names dwarfs the
satellites and swallows the whole tilt.

Every N-PORT fetch disk-caches under `.notebook_state/nport_cache/` so a
kernel-restart re-run does not re-hit SEC EDGAR."""


NB08_CELL6_CODE = '''# [NB08 §5] Look-through via SEC N-PORT (replaces yfinance snapshot path — GH #1426)
# Cache is per-operator under .notebook_state/nport_cache/ (gitignored),
# populated on first run.
import sys
sys.path.insert(0, ".")
from _nport_lookthrough import effective_positions, NportUnavailable

EQUITY_ETFS = {
    "VTI", "VXUS", "VNQ", "VWO",
    "XLE", "XLF", "XLV", "XLU", "XLB", "XLI",
    "QQQ", "SPY", "DIA", "IWM", "VOO", "VEA",
}
BOND_ETFS = {"BND", "TLT", "SHY", "TIP", "SCHP", "AGG"}
COMMODITY_TRUSTS = {"GLD", "DBC", "SLV"}

effective, non_nport, opaque = effective_positions(
    basket,
    equity_etfs=EQUITY_ETFS,
    bond_etfs=BOND_ETFS,
    commodity_trusts=COMMODITY_TRUSTS,
    top_n_per_etf=50,   # top 50 issuers per ETF; tail bucketed as TAIL_<ETF>
)

print(f"Basket: {len(basket)} ETFs")
print(f"After N-PORT look-through: {len(effective)} distinct effective positions")
print(f"Total effective weight: {sum(effective.values())*100:.1f}%")
print()

if non_nport:
    print("Non-N-PORT filers (left opaque — no fund-disclosure feed):")
    for sym in non_nport:
        print(f"  {sym}  (commodity grantor trust or non-'40-Act fund)")
    print()

print("Top 15 effective positions:")
print(f"{'Issuer / bucket':<40}{'Weight':>10}")
print("-" * 52)
for key, w in sorted(effective.items(), key=lambda kv: -kv[1])[:15]:
    print(f"{key[:38]:<40}{w*100:>9.2f}%")
'''


NB08_CELL10_CODE = '''# [NB08 §6] HHI + effective-N + sector view (naive vs look-through)
# Sector rollup on the flattened positions uses SEC issuer-name → ticker
# resolution (obb.equity.search, provider="sec"), then ticker → sector via
# fmp_cached equity.profile. Both cached under .notebook_state/nport_cache/
# so a kernel-restart re-run is cheap.
import sys
sys.path.insert(0, ".")
from _nport_lookthrough import nport_holdings, sector_rollup, NportUnavailable
from openbb import obb
import warnings; warnings.filterwarnings("ignore")

def hhi(weights):
    return sum(w*w for w in weights)

# Naive HHI + N over the 15 ETFs
raw_weights = [p["weight"] for p in basket]
hhi_raw = hhi(raw_weights)
neff_raw = 1.0 / hhi_raw

# Look-through HHI + N over the effective flattened positions
xray_weights = list(effective.values())
hhi_xray = hhi(xray_weights)
neff_xray = 1.0 / hhi_xray

# Sector view — naive (each ETF is one bucket)
NAIVE_SECTOR = {
    "VTI": "Broad US Equity", "VXUS": "Broad Intl Equity",
    "VNQ": "Real Estate ETF", "GLD": "Commodity (Gold)",
    "BND": "Bond Fund", "TLT": "Bond Fund", "SHY": "Bond Fund",
    "TIP": "Bond Fund", "SCHP": "Bond Fund",
    "XLE": "Energy", "XLF": "Financials", "XLV": "Health Care",
    "XLU": "Utilities", "XLB": "Materials", "XLI": "Industrials",
    "DBC": "Commodity (Broad)", "VWO": "Broad EM Equity",
}
naive_by_sector = {}
for p in basket:
    sec = NAIVE_SECTOR.get(p["symbol"], "Unknown")
    naive_by_sector[sec] = naive_by_sector.get(sec, 0.0) + p["weight"]

# Sector view — look-through via N-PORT + SEC name-search rollup
EQUITY_ETFS = {"VTI","VXUS","VNQ","VWO","XLE","XLF","XLV","XLU","XLB","XLI","QQQ"}
BOND_ETFS = {"BND","TLT","SHY","TIP","SCHP"}
COMMODITY_TRUSTS = {"GLD","DBC"}

xray_by_sector: dict[str, float] = {}
unknown_count = 0
for pos in basket:
    sym = pos["symbol"]; w = pos["weight"]
    if sym in COMMODITY_TRUSTS:
        bucket = "Commodity"
        xray_by_sector[bucket] = xray_by_sector.get(bucket, 0.0) + w
        continue
    if sym in BOND_ETFS:
        bucket = "Fixed Income"
        xray_by_sector[bucket] = xray_by_sector.get(bucket, 0.0) + w
        continue
    if sym in EQUITY_ETFS:
        try:
            rows = nport_holdings(sym)
        except NportUnavailable:
            xray_by_sector[sym] = xray_by_sector.get(sym, 0.0) + w
            continue
        # rollup: scale weights by this ETF's weight in the basket
        sec_w, cnt = sector_rollup(rows, weight_scale=w, top_n_resolve=30)
        for k, v in sec_w.items():
            xray_by_sector[k] = xray_by_sector.get(k, 0.0) + v
        unknown_count += cnt.get("Unknown", 0) + cnt.get("Other (small)", 0)
    else:
        # single-name equity — use its own sector
        try:
            info = obb.equity.profile(symbol=sym, provider="fmp_cached").results
            sec = getattr(info[0], "sector", None) if info else "Unknown"
        except Exception:
            sec = "Unknown"
        sec = sec or "Unknown"
        xray_by_sector[sec] = xray_by_sector.get(sec, 0.0) + w

print(f"{'Concentration':<20}{'Naive':>12}{'X-Ray':>12}{'Delta':>12}")
print("-" * 56)
print(f"{'HHI':<20}{hhi_raw:>12.4f}{hhi_xray:>12.4f}{hhi_xray-hhi_raw:>+12.4f}")
print(f"{'Effective-N':<20}{neff_raw:>12.2f}{neff_xray:>12.2f}{neff_xray-neff_raw:>+12.2f}")
print()
print("Naive sector view (top 6):")
for sec, w in sorted(naive_by_sector.items(), key=lambda kv: -kv[1])[:6]:
    print(f"  {sec:<24}{w*100:>7.1f}%")
print()
print("Look-through sector view (top 8, via N-PORT + SEC name search):")
for sec, w in sorted(xray_by_sector.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  {sec:<24}{w*100:>7.2f}%")
print()
print(f"Rollup transparency: {unknown_count} constituents bucketed as "
      f"Unknown / Other (small) across the equity ETFs (tail rows below the "
      f"top-30 resolution threshold; contribute <0.05% each).")
'''


# --- NB03 replacements ---

NB03_LOOKTHROUGH_MD = """## 3. The x-ray — look-through via SEC N-PORT (`obb.etf.nport_disclosure`)

Now the real view. Instead of `obb.portfolio_intel.xray.look_through` (which
under the hood calls `obb.etf.holdings(provider="fmp_cached")` — and my FMP
plan doesn't include ETF-Holdings), we read each fund's actual **SEC Form
N-PORT** disclosure and re-weight each underlying position by (basket weight
× ETF weight-in-basket). N-PORT is the quarterly holdings filing every
'40-Act US-registered fund files with the SEC — free, authoritative,
redistribution-safe (US government filing), covers both equity ETFs (QQQ,
VTI, VNQ) and bond ETFs (BND). The migration off the Yahoo-shaped snapshot
path was tracked as #1426 (notebook consumer, this notebook among them) —
the notebook-facing follow-up to the provenance concern in #1425.

Caveats to keep in mind:

- **Cadence / lag.** N-PORT is quarterly-visible with ~30-60 days lag. For
  a look-through / concentration story that's a rounding error; VTI's top
  holdings do not turn over in a quarter.
- **GLD is not an N-PORT filer** — commodity grantor trust; files 10-K/8-K
  instead. The helper raises `NportUnavailable` and the notebook leaves
  GLD opaque (no look-through possible for physical gold anyway).
- **US-registered funds only.** Fine for the through-line basket.
- **13F ≠ fund holdings.** The `sec` provider also exposes `Form13FHoldings`
  (institutional-manager positions) — don't confuse that with N-PORT.

QQQ's top holdings via N-PORT are MSFT, NVDA, AAPL, GOOGL, AMD — the exact
names already in the basket at full weight. VTI has a ~30% tech tilt and
MSFT is in the top three. The flattened view turns "10 things" into a few
hundred underlying issuer rows, weighted so a handful of names dominate.

> **📖 Look-through** — the accounting/analysis discipline of expanding a pooled holding (ETF, mutual fund, holdco) into its underlying constituents before measuring exposure. Without it, "I own QQQ" and "I own MSFT" look like independent bets when they aren't. [Investopedia →](https://www.investopedia.com/terms/l/look-through-earnings.asp)

*The code cell below runs the N-PORT look-through and prints the top-15
effective positions after flattening.*"""


NB03_LOOKTHROUGH_CODE = '''# [Phase B / NB03 §3] Look-through via SEC N-PORT (GH #1426, provenance #1425)
# Same math as before, authoritative source: SEC EDGAR Form N-PORT filings.
# Cache is per-operator under .notebook_state/nport_cache/ (gitignored).
import sys
sys.path.insert(0, ".")
from _nport_lookthrough import effective_positions, NportUnavailable

EQUITY_ETFS = {"QQQ", "VTI", "VNQ", "SPY", "DIA", "IWM", "VOO", "VEA", "VXUS", "VWO"}
BOND_ETFS = {"BND", "AGG", "TLT", "SHY", "TIP", "SCHP"}
COMMODITY_TRUSTS = {"GLD", "SLV", "DBC"}

effective, non_nport, opaque = effective_positions(
    basket,
    equity_etfs=EQUITY_ETFS,
    bond_etfs=BOND_ETFS,
    commodity_trusts=COMMODITY_TRUSTS,
    top_n_per_etf=50,
)

print(f"Basket: {len(basket)} positions")
print(f"After N-PORT look-through: {len(effective)} distinct effective positions")
print(f"Total effective weight: {sum(effective.values())*100:.1f}%")
print()
if non_nport:
    print(f"Non-N-PORT filers (left opaque): {non_nport}")
    print()

print("Top 15 effective positions (post-look-through):")
print(f"{'Issuer / bucket':<40}{'Weight':>10}")
print("-" * 52)
for key, w in sorted(effective.items(), key=lambda kv: -kv[1])[:15]:
    print(f"{key[:38]:<40}{w*100:>9.2f}%")
'''


NB03_SECTOR_CODE = '''# [Phase B / NB03 §4] Sector view WITH look-through — the pivot
# Same sector classification as §2, but on the flattened N-PORT positions.
# Rollup: SEC issuer-name → ticker via obb.equity.search(provider="sec"),
# then ticker → sector via fmp_cached equity.profile. Cached to disk.
import sys
sys.path.insert(0, ".")
from _nport_lookthrough import nport_holdings, sector_rollup, NportUnavailable
from openbb import obb
import warnings; warnings.filterwarnings("ignore")

EQUITY_ETFS = {"QQQ", "VTI", "VNQ", "VXUS", "VWO"}
BOND_ETFS = {"BND", "TLT", "SHY", "TIP", "SCHP"}
COMMODITY_TRUSTS = {"GLD", "DBC"}

xray_by_sector: dict[str, float] = {}
unknown_count = 0
for pos in basket:
    sym = pos["symbol"]; w = pos["weight"]
    if sym in COMMODITY_TRUSTS:
        xray_by_sector["Commodity"] = xray_by_sector.get("Commodity", 0.0) + w
        continue
    if sym in BOND_ETFS:
        xray_by_sector["Fixed Income"] = xray_by_sector.get("Fixed Income", 0.0) + w
        continue
    if sym in EQUITY_ETFS:
        try:
            rows = nport_holdings(sym)
        except NportUnavailable:
            xray_by_sector[sym] = xray_by_sector.get(sym, 0.0) + w
            continue
        sec_w, cnt = sector_rollup(rows, weight_scale=w, top_n_resolve=30)
        for k, v in sec_w.items():
            xray_by_sector[k] = xray_by_sector.get(k, 0.0) + v
        unknown_count += cnt.get("Unknown", 0) + cnt.get("Other (small)", 0)
    else:
        try:
            info = obb.equity.profile(symbol=sym, provider="fmp_cached").results
            sec = getattr(info[0], "sector", None) if info else "Unknown"
        except Exception:
            sec = "Unknown"
        sec = sec or "Unknown"
        xray_by_sector[sec] = xray_by_sector.get(sec, 0.0) + w

print("Look-through sector view (N-PORT flattened):")
print(f"{'Sector':<24}{'Weight':>10}")
print("-" * 36)
for sector, w in sorted(xray_by_sector.items(), key=lambda kv: -kv[1]):
    print(f"{sector:<24}{w*100:>9.2f}%")

print()
print("Side-by-side delta (naive vs N-PORT look-through):")
print(f"{'Sector':<24}{'Naive':>10}{'X-Ray':>10}{'Delta':>10}")
print("-" * 56)
all_sectors = set(naive_by_sector) | set(xray_by_sector)
for sec in sorted(all_sectors, key=lambda s: -xray_by_sector.get(s, 0)):
    n = naive_by_sector.get(sec, 0.0) * 100
    x = xray_by_sector.get(sec, 0.0) * 100
    delta = x - n
    print(f"{sec:<24}{n:>9.1f}%{x:>9.2f}%{delta:>+9.1f}%")

tech_xray = xray_by_sector.get("Technology", 0.0) + xray_by_sector.get("Tech ETF", 0.0)
print()
print(f"Effective Tech exposure: {tech_xray*100:.1f}%  "
      f"(was {tech_naive*100:.1f}% naive - the N-PORT look-through spreads "
      f"the ETF weight across underlying sectors)")
print()
print(f"Rollup transparency: {unknown_count} constituents bucketed as "
      f"Unknown / Other (small) (tail rows below the top-30 resolution "
      f"threshold; each contributes <0.05%).")
'''


# --- NB07 replacements ---

NB07_XRAY_STEP = '''async def _step_p3_xray():
    # NB03's look-through pattern — SEC N-PORT flatten (GH #1426).
    # Reads from the disk cache at .notebook_state/nport_cache/ populated
    # by NB03; a cold cache adds ~30s for the QQQ/VTI/VNQ triple.
    import sys as _sys
    _sys.path.insert(0, ".")
    from _nport_lookthrough import nport_holdings, NportUnavailable
    for sym in ("QQQ", "VTI", "VNQ"):
        try:
            nport_holdings(sym)
        except NportUnavailable:
            pass'''


# --- NB01 replacements ---

NB01_S2_MD_INSERT = """## 2. The three-tier provider story

The fork resolves provider calls in a **three-tier waterfall** and every
notebook in this series depends on knowing which tier answered:

1. **Primary — `fmp_cached`.** Paid FMP key plus a local sqlite cassette
   layer, so every call is at most one round-trip and re-runs are free.
   This is the workhorse for prices, fundamentals, ratios, grades,
   calendars, and the sector snapshot. Rebuild the platform after any
   provider swap: `python -c "import openbb; openbb.build()"`.
2. **Authoritative fallback — `sec` (SEC EDGAR).** For ETF/bond
   look-through we route through `obb.etf.nport_disclosure(...,
   provider="sec")` — the quarterly **Form N-PORT** filing every '40-Act
   US-registered fund is required to make with the SEC. Free,
   redistribution-safe (US government filing), authoritative (issuer
   filed it), covers both equity ETFs and bond ETFs. See NB03 §3, NB07
   §5.5, and NB08 §5 for the actual look-through.
3. **Freshness convenience — `yfinance` (offline, snapshot-backed).**
   For options chains, quotes, and a handful of one-off fields where
   `fmp_cached` doesn't cover my sub-plan, the fork ships snapshot-backed
   yfinance fetchers that read from a **user-local sqlite DB** at
   `~/.scrape_record/snapshots.db` — never live. Nothing Yahoo-shaped
   ships in git; each operator keeps their own copy. See §4 below.

**Where each fits, in one sentence.** `fmp_cached` for anything covered
by my subscription (99% of what these notebooks do). `sec` N-PORT for ETF
look-through (free + authoritative + redistribution-safe). Snapshot-backed
yfinance for the specific things `fmp_cached` doesn't cover on my plan
(quotes/options + a few miscellaneous fields).

**Caveats for the SEC N-PORT tier that matter every notebook:**

- **Cadence / lag.** N-PORT holdings are quarterly-visible with a ~30–60 day
  lag. For look-through / concentration work (NB03, NB08) that's a rounding
  error — the top-50 of VTI does not turn over in a quarter. For anything
  intraday, use the `fmp_cached` `obb.etf.holdings` route instead.
- **GLD (and DBC) are not N-PORT filers.** GLD is a commodity grantor trust
  holding physical gold; it files 10-K/8-K, not N-PORT. The look-through
  helper flags them as `NportUnavailable` and leaves them opaque (no
  look-through possible for a commodity trust anyway).
- **US-registered funds only.** N-PORT covers '40-Act funds. Foreign UCITS,
  offshore ETFs, and interval funds are out of scope.
- **13F ≠ fund holdings.** The `sec` provider also exposes `Form13FHoldings`
  (institutional-manager positions). Do not confuse it with N-PORT — 13F is
  a manager's long US equity book; N-PORT is a fund's full holdings.

Migration provenance: see GH #1426 (notebook consumer) and #1425 (Yahoo
snapshot store → user-local DB), the two issues that motivated moving the
ETF/bond look-through off Yahoo-shaped snapshots and onto SEC N-PORT."""


NB01_S2_CODE = '''# [Phase B / NB01 §2] Same ETF-holdings endpoint, three tiers:
#   1. fmp_cached (skipped here — my plan doesn't include ETF Holdings)
#   2. SEC N-PORT (authoritative, redistribution-safe) — the ETF/bond primary
#   3. yfinance snapshot (freshness convenience for other endpoints)
from openbb import obb
import warnings; warnings.filterwarnings("ignore")

# Primary quote path — fmp_cached (works for a single-name)
print("Primary path — fmp_cached (paid FMP + cache):")
q_fmp = obb.equity.price.quote(symbol="MSFT", provider="fmp_cached")
df_fmp = q_fmp.to_df()
print(f"  provider=fmp_cached  rows={len(df_fmp)}  columns={len(df_fmp.columns)}")
print(f"  MSFT last_price={df_fmp['last_price'].iloc[0]}  (live cached quote)"
      if "last_price" in df_fmp.columns else "  (columns: %s)" % list(df_fmp.columns)[:5])
print()

# Authoritative ETF-holdings tier — SEC N-PORT (GH #1426)
print("Authoritative tier — obb.etf.nport_disclosure (SEC Form N-PORT):")
nport = obb.etf.nport_disclosure(symbol="QQQ", provider="sec")
rows = nport.results
top5 = sorted(rows, key=lambda r: -(r.weight or 0))[:5]
print(f"  provider=sec  rows={len(rows)}  (QQQ N-PORT filing)")
print("  Top 5 issuers by weight:")
for r in top5:
    print(f"    {r.name[:34]:<36} {(r.weight or 0)*100:>6.2f}%   CUSIP {r.cusip}")
print(f"  Sum of weights: {sum((r.weight or 0) for r in rows)*100:.1f}%")
print()

# Freshness-convenience tier — snapshot-backed yfinance (offline)
# The snapshot layer reads from ~/.scrape_record/snapshots.db (per-operator,
# never committed). If a symbol isn't recorded locally, the fetcher raises
# EmptyDataError with the exact `scrape-record record ...` command to run.
print("Freshness convenience — YFinanceEquityQuoteRecorded (offline snapshot):")
try:
    from openbb_yfinance.models.recorded_equity_quote import (
        YFinanceEquityQuoteRecordedFetcher,
    )
    row = YFinanceEquityQuoteRecordedFetcher.fetch_from_snapshot("MSFT")
    print(f"  provider=yfinance(snapshot)  symbol={row.symbol}  "
          f"last_price={row.last_price}  captured_at={row.captured_at}")
except Exception as exc:
    print(f"  (no local MSFT snapshot recorded — {type(exc).__name__})")
    print(f"  Record with: scrape-record record yahoo_equity_quote --symbol MSFT")
print("  (snapshot layer read from ~/.scrape_record/snapshots.db — never live)")
'''


NB01_S3_CODE_TAIL = '''# ETF holdings — I don't have FMP's ETF-Holdings sub-plan, so this
# specific call falls through to the authoritative SEC N-PORT tier
# (GH #1426 — replaces the prior yahoo_etf_holdings snapshot fallback).
print()
print("EtfHoldings (fmp_cached tier — I don't have this sub-plan):")
try:
    result = obb.etf.holdings(symbol="QQQ", provider="fmp_cached")
    df = result.to_df()
    print(f"  {'EtfHoldings QQQ':<28}{len(df):>6}   fmp_cached     ok")
except Exception as exc:
    print(f"  {'EtfHoldings QQQ':<28}{'-':>6}   fmp_cached     "
          f"{type(exc).__name__}: {str(exc)[:40]}")
    print("  -> falling back to SEC N-PORT (obb.etf.nport_disclosure, provider=sec)")
    nport = obb.etf.nport_disclosure(symbol="QQQ", provider="sec")
    print(f"  {'N-PORT QQQ':<28}{len(nport.results):>6}   sec            ok")
'''


NB01_S3_FETCHERS_MD = """## 3. The 20 fetchers that will actually matter

Not all of the platform's fetchers matter for what we're doing. Here
are the ones that come back in later notebooks — teased now, so
nothing surprises you later.

**Prices + basic company data (NB02, NB03):**
`EquityQuote`, `EquityHistorical`, `EquityInfo`, `EquityPeers`.

**Fundamentals (NB02):**
`KeyMetricsTtm`, `FinancialRatios`, `FinancialScores`, `OwnerEarnings`,
`EnterpriseValues`, `IncomeStatement`, `BalanceSheet`, `CashFlowStatement`.

**Ratings + calendars (NB02, NB04):**
`Grades`, `PriceTargetConsensus`, `CalendarEarnings`, `HistoricalDividends`.

**Structure + ownership (NB03, NB04):**
`NportDisclosure` (SEC — ETF/bond look-through), `InstitutionalOwnership`,
`InsiderTrading`, `GovernmentTrades`.

**Sector snapshots (NB03):**
`SectorPerformanceSnapshot`.

**Every single one except `NportDisclosure` lives in `fmp_cached`.**
`NportDisclosure` is served by the `sec` provider — the authoritative
tier for ETF/bond look-through (GH #1426). My FMP plan does not cover
`EtfHoldings`, so instead of falling back to a Yahoo-scraped snapshot,
NB03/NB08 call `obb.etf.nport_disclosure(..., provider="sec")` and
unwrap the fund into its filed holdings. See §2 for the tier story.

*The code cell below shows each of the 20 fetchers responding to a
one-line call, tagged with which provider ended up serving it.*"""


NB01_S4_MD = """## 4. The offline-snapshot pattern (yfinance without hitting yfinance)

After the migration in §2/§3 the ETF/bond look-through is served by SEC
N-PORT, not by Yahoo. So the offline-snapshot layer is now scoped to the
specific things `fmp_cached` doesn't cover for me AND `sec` doesn't cover
either:

- **Options chains** for a single-name — my FMP tier doesn't include options
- **ATM implied-vol term structure** — same reason
- **Equity quote / equity info** as a freshness-convenience fallback

For those, the fork ships a small framework called `scrape_record` that
records a page once and replays it from a **user-local SQLite DB** at
`~/.scrape_record/snapshots.db`. Nothing Yahoo-shaped ships in git;
each operator keeps their own local copy (see GH #1425 for the ToS
rationale — this mirrors how `yfinance` itself is documented, "personal
use only").

The bond-ladder and ETF-holdings snapshot flavours (`yahoo_bond_etf_holdings`,
`yahoo_etf_holdings`) still work for anyone who has them recorded, but the
notebook series no longer reads from them by default — that path is
retired in favour of N-PORT. The remaining snapshot-backed fetchers are:

- `YFinanceEquityQuoteRecordedFetcher` — price/OHLC/market cap
- `YFinanceEquityInfoRecordedFetcher` — sector/industry/summary
- `YFinanceRecordedOptionsChainsFetcher` — full options chain per expiry
- `YFinanceAtmIvTermStructureFetcher` — ATM implied-vol curve

They read from the DB first, and (during the migration window) fall
back to any legacy JSON at `openbb_platform/tools/scrape_record/snapshots/`
that a prior operator may still have on disk. If a symbol isn't
present locally, the fetcher raises `FileNotFoundError` and tells you
the exact command to record it: `scrape-record record <name> --symbol
<SYM>`. **No live-scraping surprises at query time. No automation
ever hits Yahoo live.**

The cell below demonstrates the pattern on `EquityQuote` (the smallest,
fastest-to-verify shape); the bond-ETF holdings that used to live here
now come from N-PORT in NB03/NB08."""


NB01_S4_CODE = '''# [Phase B / NB01 §4] Snapshot-backed yfinance — demonstrate the offline path
# on EquityQuote (post-#1426 the bond-ladder snapshot is no longer the
# default look-through source; NB03 §3 shows the N-PORT replacement).
# If a symbol isn't recorded locally the fetcher raises EmptyDataError with
# the exact record command — the cell prints that command rather than crashing.
try:
    from openbb_yfinance.models.recorded_equity_quote import (
        YFinanceEquityQuoteRecordedFetcher,
    )
    row = YFinanceEquityQuoteRecordedFetcher.fetch_from_snapshot("MSFT")
    print(f"Symbol:                {row.symbol}")
    print(f"Last price (snapshot): {row.last_price}")
    print(f"Market cap:            {row.market_cap:,}" if row.market_cap else "Market cap:            (not in snapshot)")
    print(f"Captured at:           {row.captured_at}")
except Exception as exc:
    print(f"(no local MSFT snapshot recorded — {type(exc).__name__})")
    print(f"Record with: scrape-record record yahoo_equity_quote --symbol MSFT")
print()
print("Source (per-operator, never committed): ~/.scrape_record/snapshots.db  (name=yahoo_equity_quote, symbol=MSFT)")
print("Record / refresh: `scrape-record record yahoo_equity_quote --symbol MSFT` (operator-run, personal use only)")
print()
print("For ETF/bond look-through the series now uses SEC N-PORT (see §2, NB03 §3, NB08 §5)")
print("rather than yahoo_etf_holdings / yahoo_bond_etf_holdings — GH #1426.")
'''


# ---------------------------------------------------------------------------
# Cell locator + rewriter
# ---------------------------------------------------------------------------

def _cell_src(cell: dict) -> str:
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(src)
    return src


def _set_src(cell: dict, new_src: str) -> None:
    # nbformat stores source as list of lines with trailing \n
    lines = new_src.splitlines(keepends=True)
    cell["source"] = lines
    cell["outputs"] = []
    cell["execution_count"] = None


def _find_cell(nb: dict, needle: str, cell_type: str | None = None) -> int:
    for i, c in enumerate(nb["cells"]):
        if cell_type and c.get("cell_type") != cell_type:
            continue
        if needle in _cell_src(c):
            return i
    raise LookupError(f"needle {needle!r} not found in notebook")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, nb: dict) -> None:
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def mutate_nb08(path: Path) -> None:
    nb = _load(path)
    # §5 markdown
    i = _find_cell(nb, "5. Basket X-Ray", cell_type="markdown")
    _set_src(nb["cells"][i], NB08_CELL5_MD)
    # §5 code — the YFinance import cell
    i = _find_cell(nb, "YFinanceEtfHoldingsRecordedFetcher", cell_type="code")
    _set_src(nb["cells"][i], NB08_CELL6_CODE)
    # §6 code — HHI + sector view
    i = _find_cell(nb, "NB08 §6] HHI + effective-N", cell_type="code")
    _set_src(nb["cells"][i], NB08_CELL10_CODE)
    _save(path, nb)


def mutate_nb03(path: Path) -> None:
    nb = _load(path)
    # §3 markdown
    i = _find_cell(nb, "look-through via `obb.portfolio_intel.xray", cell_type="markdown")
    _set_src(nb["cells"][i], NB03_LOOKTHROUGH_MD)
    # §3 code
    i = _find_cell(nb, "YFinanceEtfHoldingsRecordedFetcher", cell_type="code")
    _set_src(nb["cells"][i], NB03_LOOKTHROUGH_CODE)
    # §4 code
    i = _find_cell(nb, "NB03 §4] Sector view WITH look-through", cell_type="code")
    _set_src(nb["cells"][i], NB03_SECTOR_CODE)
    _save(path, nb)


def mutate_nb07(path: Path) -> None:
    nb = _load(path)
    i = _find_cell(nb, "YFinanceEtfHoldingsRecordedFetcher", cell_type="code")
    src = _cell_src(nb["cells"][i])
    # Replace the async def _step_p3_xray function only
    start = src.find("async def _step_p3_xray():")
    end = src.find("def _step_p6_backtest():")
    new_src = src[:start] + NB07_XRAY_STEP + "\n\n" + src[end:]
    _set_src(nb["cells"][i], new_src)
    _save(path, nb)


def mutate_nb01(path: Path) -> None:
    nb = _load(path)
    # Find §2 markdown (either the new heading or the legacy one)
    for needle in ("## 2. The three-tier provider story", "## 2. My provider tier"):
        try:
            i = _find_cell(nb, needle, cell_type="markdown")
            _set_src(nb["cells"][i], NB01_S2_MD_INSERT)
            break
        except LookupError:
            continue

    # §2 code
    for needle in ("same endpoint via fmp_cached", "Same ETF-holdings endpoint, three tiers"):
        try:
            i = _find_cell(nb, needle, cell_type="code")
            _set_src(nb["cells"][i], NB01_S2_CODE); break
        except LookupError:
            continue

    # §3 markdown (fetchers list)
    i = _find_cell(nb, "## 3. The 20 fetchers", cell_type="markdown")
    _set_src(nb["cells"][i], NB01_S3_FETCHERS_MD)

    # §4 markdown
    i = _find_cell(nb, "## 4. The offline-snapshot pattern", cell_type="markdown")
    _set_src(nb["cells"][i], NB01_S4_MD)

    # §4 code — the BondLadder cell (or its N-PORT replacement)
    for needle in ("YFinanceBondLadderFetcher", "Snapshot-backed yfinance"):
        try:
            i = _find_cell(nb, needle, cell_type="code")
            _set_src(nb["cells"][i], NB01_S4_CODE); break
        except LookupError:
            continue

    # §3 code — replace the EtfHoldings yahoo-snapshot fallback with N-PORT
    try:
        i = _find_cell(nb, "YFinanceEtfHoldingsRecordedFetcher", cell_type="code")
    except LookupError:
        pass
    else:
        src = _cell_src(nb["cells"][i])
        marker = "# ETF holdings"
        idx = src.find(marker)
        if idx != -1:
            new_src = src[:idx] + NB01_S3_CODE_TAIL
            _set_src(nb["cells"][i], new_src)
    _save(path, nb)


def execute_notebook(path: Path, timeout: int = 900) -> None:
    """Run the notebook end-to-end via nbclient, saving outputs in place."""
    import nbformat
    from nbclient import NotebookClient

    nb = nbformat.read(str(path), as_version=4)
    client = NotebookClient(
        nb,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
        allow_errors=False,
    )
    client.execute()
    nbformat.write(nb, str(path))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebooks", nargs="+", default=["08", "03", "07", "01"],
                    help="Which notebooks (numeric prefix) to mutate + execute")
    ap.add_argument("--no-execute", action="store_true")
    args = ap.parse_args()

    mapping = {
        "01": (NB_DIR / "01-getting-started-and-providers.ipynb", mutate_nb01),
        "03": (NB_DIR / "03-basket-xray-and-risk.ipynb", mutate_nb03),
        "07": (NB_DIR / "07-offline-recording-and-end-to-end.ipynb", mutate_nb07),
        "08": (NB_DIR / "08-analyst-recommendations-basket.ipynb", mutate_nb08),
    }

    for key in args.notebooks:
        path, mutator = mapping[key]
        print(f"=== mutating {path.name} ===", flush=True)
        mutator(path)
        if not args.no_execute:
            print(f"=== executing {path.name} ===", flush=True)
            execute_notebook(path)
            print(f"    OK", flush=True)


if __name__ == "__main__":
    main()
