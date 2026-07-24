# Portfolio Notebook Series — Snapshot Universe

The list of tickers whose Yahoo Finance snapshots are recorded via the
sub-epic #1374 sweep. Every ticker is captured for at least the
following endpoints:

- `yahoo_equity_quote` — price / OHLC / market cap (all tickers)
- `yahoo_equity_info` — company profile (all tickers)

Plus, per ticker classification (see `scripts/record_universe_snapshots.py`):

- `yahoo_etf_holdings` — for equity ETFs (QQQ / VTI / VNQ / SPY / DIA / IWM / VOO / VEA)
- `yahoo_bond_etf_holdings` — for bond ETFs (BND; DOM-scrape, separate recording)
- Physical commodity trusts (GLD): quote + info only — no equity-holdings endpoint

## Refresh policy

Snapshots whose envelope `captured_at` is older than 7 days are
re-captured by `scripts/record_universe_snapshots.py`. Force a full
re-record with `--force`. Add a ticker by editing the fenced code
block below and re-running the sweep — the script is idempotent and
skip-if-fresh.

## Basket + benchmarks + top-40 S&P

**55 tickers total:** 10 basket (from `STORY_BIBLE.md` §3) + 5
benchmarks + 40 top S&P names to seed `EquityPeers` demos.

Sweep plan (per the routing above): **10 basket + 5 benchmarks + 40
equities** — 55 tickers × 2 endpoints (quote + info) + 8 equity ETFs
× 1 (etf-holdings) + 1 bond ETF × 1 (bond-etf-holdings) = **119
captures**.

**Do not add real portfolio names or account-specific tickers here.**
This file is checked into the public fork; only publicly-listed
instruments belong.

```universe
# Through-line basket (STORY_BIBLE §3) — 10
MSFT
NVDA
GOOGL
AAPL
AMD
QQQ
VTI
VNQ
BND
GLD

# Benchmarks — 5
SPY
DIA
IWM
VOO
VEA

# Top-40 S&P (for peer sets in NB02 / NB04)
BRK-B
LLY
JPM
XOM
UNH
V
JNJ
PG
MA
HD
CVX
MRK
ABBV
KO
PEP
COST
AVGO
BAC
WMT
TMO
CSCO
DIS
ABT
ADBE
ORCL
PFE
NFLX
INTC
CRM
ACN
MCD
CMCSA
QCOM
LIN
DHR
NKE
NEE
TXN
UPS
AMGN
```
