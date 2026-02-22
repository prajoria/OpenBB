# Domain Knowledge — Finance & Tax

> **Purpose:** Financial and tax domain concepts relevant to this project.
> Reference this when working on cost basis, tax optimization, ESPP,
> or portfolio analysis features.

---

## 1. Cost Basis & Capital Gains

### Holding Period Classification

| Term | Holding Period | Tax Rate |
|------|---------------|----------|
| **Short-term** | ≤ 1 year from acquisition | Ordinary income rates (up to 37%) |
| **Long-term** | > 1 year from acquisition | Preferential rates (0%, 15%, or 20%) |

The acquisition date starts the day **after** purchase.  The 1-year
threshold is met on the **same calendar date** the following year.

### Cost Basis Methods

When selling partial positions, the IRS allows several methods to
select which lots are sold:

| Method | Full Name | Strategy |
|--------|-----------|----------|
| **FIFO** | First In, First Out | Sell oldest lots first (IRS default) |
| **LIFO** | Last In, First Out | Sell newest lots first |
| **HIFO** | Highest In, First Out | Sell highest-cost lots first (minimises gain) |
| **Specific Lot** | Specific Identification | Choose exact lots to sell |

**HIFO + Specific Lot** is typically the most tax-efficient for
minimising current-year capital gains.

### Wash Sale Rule (IRC §1091)

If you sell a security at a **loss** and repurchase **substantially
identical** securities within **30 days before or after** the sale:

- The loss is **disallowed** for tax purposes.
- The disallowed loss is **added to the cost basis** of the replacement shares.
- The holding period of the replacement shares **includes** the original
  holding period.

**Scope:** Applies across all accounts owned by the taxpayer (including
IRAs, spouse accounts).  Does **not** apply to gains.

---

## 2. ESPP (Employee Stock Purchase Plan)

### IRC §423 Qualified Plans

An ESPP lets employees buy company stock at a discount using after-tax
payroll deductions.

| Concept | Definition |
|---------|------------|
| **Offering period** | Enrollment window (typically 3–6 months) during which payroll deductions accumulate |
| **Purchase date** | End of offering period when shares are automatically purchased |
| **Look-back provision** | Purchase price is based on the **lower** of FMV at offering start or purchase date |
| **Discount** | Typically **15%** off the look-back price |
| **Purchase price** | `85% × min(FMV_offering_start, FMV_purchase_date)` |

### ESPP Tax Treatment

Two key computed values determine tax treatment:

| Value | Formula | Significance |
|-------|---------|--------------|
| **Discount %** | `(FMV_start − price) / FMV_start × 100` | Effective discount received |
| **Bargain element** | `(FMV_purchase − price) × quantity` | Taxable compensation (Form 3922) |

### Disposition Types

| Type | Condition | Tax Treatment |
|------|-----------|---------------|
| **Qualifying** | Sold **after** both: (a) 2 years from offering start, AND (b) 1 year from purchase date | Bargain element (capped at offering-start discount) taxed as ordinary income; remainder as LTCG |
| **Disqualifying** | Sold **before** either threshold | Full bargain element taxed as ordinary income; additional gain as STCG or LTCG based on holding period |

**Qualified disposition date** = the **later** of:
- 2 years after `offering_period_start`
- 1 year after `purchase_date`

### Relevance to This Project

- `ESPP_Plan` table stores `discount_pct` and `bargain_element` computed
  at insert time.
- `qualified_disposition_date` enables tax-optimal sell timing.
- Future work: compare current price vs qualified disposition date to
  flag shares eligible for qualifying disposition.

---

## 3. Account Types & Tax Treatment

| Account Type | Tax Treatment | In Portfolio? |
|-------------|---------------|---------------|
| **Individual (TOD)** | Taxable brokerage — gains/losses realised annually | Yes |
| **Roth IRA** | Tax-free growth — no tax on qualified withdrawals | Yes |
| **401(k)** | Tax-deferred — taxed as ordinary income on withdrawal | Yes |
| **529 Plan** | Tax-free growth for qualified education expenses | Yes |
| **HSA** | Triple tax advantage — deductible, tax-free growth, tax-free for medical | Yes |

**Implication for analysis:** Only gains/losses in the Individual (TOD)
account affect current-year taxes.  Retirement and education accounts
are tax-sheltered.

---

## 4. Market Structure

### Trading Calendar

US equity markets (NYSE, NASDAQ) are open Monday–Friday except:

| Holiday | Observation Rule |
|---------|-----------------|
| New Year's Day (Jan 1) | Observed: if Sun → Mon; if Sat → Fri |
| MLK Jr. Day | 3rd Monday in January |
| Presidents' Day | 3rd Monday in February |
| Good Friday | Friday before Easter Sunday |
| Memorial Day | Last Monday in May |
| Juneteenth (Jun 19) | Since 2022; observed like New Year's |
| Independence Day (Jul 4) | Observed like New Year's |
| Labor Day | 1st Monday in September |
| Thanksgiving | 4th Thursday in November |
| Christmas (Dec 25) | Observed like New Year's |

**Special closures** (rare): National day of mourning for a former
president (e.g., Bush 2018-12-05, Carter 2025-01-09).

### Relevance to This Project

- `market_holidays` table: 162 rows covering 2010–2026.
- `_get_basic_market_holidays()` in `equity_historical.py` computes
  holidays with a fallback when DB is unavailable.
- Gap detection skips holidays to avoid false "missing data" reports.

---

## 5. Equity Price Data

### Daily OHLCV

| Field | Meaning |
|-------|---------|
| **Open** | First trade price of the day |
| **High** | Highest trade price |
| **Low** | Lowest trade price |
| **Close** | Last trade price (used for most analysis) |
| **Adj Close** | Close adjusted for splits and dividends |
| **Volume** | Number of shares traded |

**Adjusted close** is critical for historical analysis — it makes
prices comparable across stock splits and dividend reinvestment.

### Corporate Actions

| Action | Effect on Price Data |
|--------|---------------------|
| **Stock split** (e.g., 4:1) | Historical prices divided by split ratio |
| **Reverse split** (e.g., 1:10) | Historical prices multiplied by ratio |
| **Dividend** | Adjusted close reduced by dividend amount |

FMP's historical data is already split-adjusted.  The `equity_historical`
cache stores adjusted prices.

---

## 6. Ticker Symbol Conventions

| Format | Example | Source |
|--------|---------|--------|
| Standard | `AAPL`, `MSFT` | Most equities |
| Dot-separated | `BRK.B` | Some providers |
| Hyphenated | `BRK-B` | FMP API format |
| No separator | `BRKB` | Fidelity/portfolio format |
| CUSIP | `NHX202764` | 9-char alphanumeric, used for some fixed income |

**Known mapping issue:** Portfolio stores `BRKB` but FMP expects `BRK-B`.

---

*Last updated: 2026-02-21*
