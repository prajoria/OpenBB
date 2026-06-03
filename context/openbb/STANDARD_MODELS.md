# OpenBB Standard Models — Catalog

> **Purpose:** Reference catalog of all 161 standard model definitions in
> `openbb_core/provider/standard_models/`.  These define the unified
> interface that all providers implement.
>
> **See also:** `context/openbb/CORE.md` for Data and QueryParams base classes.

---

## 1. How Standard Models Work

Each standard model file defines two Pydantic classes:

```python
class FooQueryParams(QueryParams):
    """Standard query parameters — shared across all providers."""
    symbol: str
    start_date: dateType | None = None

class FooData(Data):
    """Standard response fields — shared across all providers."""
    date: dateType
    value: float
```

**Provider implementations** inherit these and add extra fields:

```python
class FMPFooQueryParams(FooQueryParams):
    """FMP-specific fields."""
    interval: str = "1d"  # FMP-only parameter

class FMPFooData(FooData):
    """FMP-specific fields."""
    adj_close: float | None = None  # FMP-only field
```

The `RegistryMap` introspects all providers to build a grand map separating
standard fields from provider-specific extras.

---

## 2. Common Field Patterns

### Query Parameters
| Field | Type | Appears In |
|-------|------|-----------|
| `symbol` | `str` | Most equity/etf/crypto models |
| `start_date` | `dateType \| None` | Historical data models |
| `end_date` | `dateType \| None` | Historical data models |
| `limit` | `NonNegativeInt \| None` | Paginated models |
| `query` | `str` | Search models |

### Data Fields
| Field | Type | Appears In |
|-------|------|-----------|
| `date` | `dateType \| datetime` | Time series data |
| `symbol` | `str` | Multi-symbol results |
| `open`, `high`, `low`, `close` | `float` | OHLCV data |
| `volume` | `float \| int \| None` | OHLCV data |
| `period_ending` | `dateType` | Financial statements |
| `fiscal_period` | `str \| None` | Financial statements |
| `fiscal_year` | `int \| None` | Financial statements |

### Validators
Common validators applied across standard models:
- `to_upper(symbol)` — Uppercase symbol normalization
- `date_validate(date)` — Flexible date parsing via `dateutil.parser`

---

## 3. Complete Model Catalog

### Equity & Market Data

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `EquityHistorical` | symbol, start_date, end_date | date, open, high, low, close, volume, vwap | `/equity/price/historical` |
| `EtfHistorical` | symbol, start_date, end_date | date, open, high, low, close, volume, vwap | `/etf/historical` |
| `CryptoHistorical` | symbol, start_date, end_date | date, open, high, low, close, volume, vwap | `/crypto/price/historical` |
| `CurrencyHistorical` | symbol, start_date, end_date | date, open, high, low, close, volume, vwap | `/currency/price/historical` |
| `IndexHistorical` | symbol, start_date, end_date | date, open, high, low, close, volume | `/index/price/historical` |
| `FuturesHistorical` | symbol, start_date, end_date, expiration | date, open, high, low, close, volume | `/derivatives/futures/historical` |
| `EquityQuote` | symbol | symbol, name, exchange, bid, ask, last_price, open, high, low, close, volume, prev_close, change, change_percent, year_high, year_low, +15 more | `/equity/price/quote` |
| `EquityNBBO` | symbol | exchange, bid, ask, bid_size, ask_size | `/equity/price/nbbo` |
| `EquitySearch` | query | symbol, name, exchange, cik, lei | `/equity/search` |
| `EquityScreener` | various filters | symbol, name, market_cap, sector, industry, +more | `/equity/screener` |
| `EquityInfo` | symbol | symbol, name, exchange, sector, industry, market_cap, description, +many | `/equity/profile` |
| `EquityPeers` | symbol | peers_list | `/equity/compare/peers` |
| `CryptoSearch` | query | symbol, name | `/crypto/search` |
| `CurrencyPairs` | query | name, symbol, currency, exchange | `/currency/search` |
| `EtfSearch` | query | symbol, name, exchange | `/etf/search` |
| `IndexSearch` | query | symbol, name | `/index/search` |
| `IndexInfo` | symbol | symbol, name, description, +more | `/index/info` |
| `IndexConstituents` | symbol | symbol, name, sector, weight | `/index/constituents` |
| `MarketSnapshots` | (none) | symbol, open, high, low, close, volume, +many | `/equity/market_snapshots` |
| `HistoricalMarketCap` | symbol | date, market_cap | `/equity/historical_market_cap` |

### Price & Performance

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `PricePerformance` | symbol | one_day, wtd, one_week, mtd, one_month, qtd, ytd, one_year, +more | `/equity/price/performance` |
| `EtfPricePerformance` | symbol | one_day, wtd, one_week, +more | `/etf/price_performance` |
| `PriceTarget` | symbol | analyst, target_price, adj_price_target, date, +more | `/equity/estimates/price_target` |
| `PriceTargetConsensus` | symbol | target_high, target_low, target_consensus, target_median | `/equity/estimates/consensus` |
| `RecentPerformance` | symbol | performance metrics | `/equity/discovery` |
| `CurrencySnapshots` | base, currencies | date, symbol, open, high, low, close, volume | `/currency/snapshots` |
| `IndexSnapshots` | region | symbol, name, price, change, change_percent | `/index/snapshots` |
| `OptionsSnapshots` | (none) | contract, underlying, strike, type, expiration, +more | `/derivatives/options/snapshots` |
| `MarketMovers` | (none) | symbol, price, change, volume | ETF discovery |

### Financial Statements

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `BalanceSheet` | symbol, limit | period_ending, fiscal_period, fiscal_year | `/equity/fundamental/balance` |
| `BalanceSheetGrowth` | symbol, limit | period_ending, growth metrics | `/equity/fundamental/balance_growth` |
| `IncomeStatement` | symbol, limit | period_ending, fiscal_period, fiscal_year | `/equity/fundamental/income` |
| `IncomeStatementGrowth` | symbol, limit | period_ending, growth metrics | `/equity/fundamental/income_growth` |
| `CashFlowStatement` | symbol, limit | period_ending, fiscal_period, fiscal_year | `/equity/fundamental/cash` |
| `CashFlowStatementGrowth` | symbol, limit | period_ending, growth metrics | `/equity/fundamental/cash_growth` |
| `FinancialRatios` | symbol, limit | period_ending, +many ratio fields | `/equity/fundamental/ratios` |
| `KeyMetrics` | symbol, limit | period_ending, +many metric fields | `/equity/fundamental/metrics` |
| `ReportedFinancials` | symbol | period_ending, +dynamic | `/equity/fundamental/reported_financials` |
| `RevenueBusinessLine` | symbol | date, business_line, revenue | `/equity/fundamental/revenue_per_segment` |
| `RevenueGeographic` | symbol | date, region, revenue | `/equity/fundamental/revenue_per_geography` |
| `ShareStatistics` | symbol | outstanding_shares, float_shares, +more | `/equity/ownership/share_statistics` |

### Estimates & Analysts

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `AnalystEstimates` | symbol | date, estimated_revenue_low/avg/high, estimated_ebitda_low/avg/high, +more | `/equity/estimates/analyst` |
| `AnalystSearch` | query | name, firm, +more | Search analysts |
| `ForwardEpsEstimates` | symbol | date, eps estimates by period | `/equity/estimates/forward_eps` |
| `ForwardEbitdaEstimates` | symbol | date, ebitda estimates | `/equity/estimates/forward_ebitda` |
| `ForwardPeEstimates` | symbol | date, pe estimates | `/equity/estimates/forward_pe` |
| `ForwardSalesEstimates` | symbol | date, sales estimates | `/equity/estimates/forward_sales` |
| `HistoricalEps` | symbol | date, actual_eps, estimated_eps, surprise | `/equity/fundamental/historical_eps` |
| `EarningsCallTranscript` | symbol | date, content | `/equity/fundamental/transcript` |

### Calendar & Events

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `CalendarDividend` | start_date, end_date | ex_dividend_date, symbol, amount, record_date, payment_date | `/equity/calendar/dividends` |
| `CalendarEarnings` | start_date, end_date | symbol, date, eps, revenue | `/equity/calendar/earnings` |
| `CalendarIpo` | start_date, end_date | symbol, company, date, shares, price_range | `/equity/calendar/ipo` |
| `CalendarSplits` | start_date, end_date | symbol, date, ratio | `/equity/calendar/splits` |
| `CalendarEvents` | start_date, end_date | date, description | `/equity/calendar/events` |
| `EconomicCalendar` | start_date, end_date | date, country, event, actual, forecast, previous | `/economy/calendar` |

### Corporate Actions & History

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `HistoricalDividends` | symbol | date, amount | `/equity/fundamental/dividends` |
| `HistoricalSplits` | symbol | date, ratio | Corporate actions |
| `HistoricalEmployees` | symbol | date, employee_count | Company history |
| `ExecutiveCompensation` | symbol | name, title, salary, bonus, stock_awards | `/equity/fundamental/management` |
| `KeyExecutives` | symbol | name, title, +more | `/equity/fundamental/management` |
| `InsiderTrading` | symbol | date, name, transaction_type, shares, price | `/equity/ownership/insider_trading` |
| `InstitutionalOwnership` | symbol | investor, shares, value, weight | `/equity/ownership/institutional` |
| `EquityOwnership` | symbol | date, investor, shares | Ownership |
| `GovernmentTrades` | symbol | date, representative, type, amount | `/uscongress/trades` |

### Fixed Income

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `TreasuryRates` | start_date, end_date | date, month_1, month_3, year_1, year_5, year_10, year_30 | `/fixedincome/government/treasury_rates` |
| `YieldCurve` | date | maturity, rate | `/fixedincome/government/yield_curve` |
| `TreasuryPrices` | date | cusip, maturity_date, rate, yield_, price | `/fixedincome/government/treasury_prices` |
| `TreasuryAuctions` | (various) | issue_date, maturity, +many | `/fixedincome/government/treasury_auctions` |
| `BondPrices` | query | date, price, yield_, +more | `/fixedincome/corporate/bond_prices` |
| `BondReference` | query | issuer, coupon, maturity, +more | `/fixedincome/corporate/bond_reference` |
| `BondIndices` | index | date, value | `/fixedincome/bond_indices` |
| `MortgageIndices` | index | date, rate | `/fixedincome/mortgage_indices` |
| `CommercialPaper` | maturity | date, rate | `/fixedincome/corporate/commercial_paper` |
| `Ameribor` | start_date, end_date | date, rate | `/fixedincome/rate/ameribor` |
| `SOFR` | start_date, end_date | date, rate | `/fixedincome/rate/sofr` |
| `FederalFundsRate` | start_date, end_date | date, rate | `/fixedincome/rate/federal_funds` |
| `TipsYields` | (various) | date, maturity, yield_ | `/fixedincome/government/tips_yields` |

### Economy & Macro

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `ConsumerPriceIndex` | country, units, frequency | date, value | `/economy/cpi` |
| `GDPNominal` | country | date, value | `/economy/gdp/nominal` |
| `GDPReal` | country | date, value | `/economy/gdp/real` |
| `GDPForecast` | country | date, value | `/economy/gdp/forecast` |
| `RiskPremium` | (none) | country, risk_premium | `/economy/risk_premium` |
| `Unemployment` | country | date, value | `/economy/unemployment` |
| `BalanceOfPayments` | country | date, +many fields | `/economy/balance_of_payments` |
| `CompositeLeadingIndicator` | country | date, value | `/economy/composite_leading_indicator` |
| `MoneyMeasures` | start_date, end_date | date, M1, M2, +more | `/economy/money_measures` |
| `FredSearch` | query | id, title, observation_start/end, frequency | `/economy/fred_search` |
| `FredSeries` | symbol | date, value | `/economy/fred_series` |
| `FredReleaseTable` | release_id | date, value, name | `/economy/fred_release_table` |
| `CountryProfile` | country | population, gdp, +many | `/economy/country_profile` |
| `EconomicIndicators` | country, symbol | date, value, +more | `/economy/indicators` |
| `AvailableIndicators` | country | symbol, name | `/economy/available_indicators` |
| `SharePriceIndex` | country | date, value | `/economy/share_price_index` |
| `HousePriceIndex` | country | date, value | `/economy/house_price_index` |
| `CountryInterestRates` | country | date, value | `/economy/interest_rates` |
| `RetailPrices` | country | date, value | `/economy/retail_prices` |
| `PersonalConsumptionExpenditures` | date | date, name, value | `/economy/pce` |

### ETF Details

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `EtfInfo` | symbol | name, inception_date, expense_ratio, holdings_count, +more | `/etf/info` |
| `EtfHoldings` | symbol, date | symbol, name, weight, shares, market_value | `/etf/holdings` |
| `EtfSectors` | symbol | sector, weight | `/etf/sectors` |
| `EtfCountries` | symbol | country, weight | `/etf/countries` |
| `EtfEquityExposure` | symbol | equity_symbol, weight, shares | `/etf/equity_exposure` |
| `NportDisclosure` | symbol | name, weight, market_value, +more | `/etf/nport_disclosure` |

### Filings & SEC

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `CompanyFilings` | symbol, type, limit | date, type, url, description | `/equity/fundamental/filings` |
| `DiscoveryFilings` | start_date, end_date | date, type, company, symbol, url | `/equity/discovery/filings` |
| `CikMap` | symbol | cik | `/regulators/sec/cik_map` |
| `SymbolMap` | cik | symbol | `/regulators/sec/symbol_map` |
| `Form13FHR` | cik | period, company, +holdings | `/regulators/sec/forms_13f` |
| `EquityFTD` | symbol | date, quantity, price | `/regulators/sec/ftd` |

### News

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `CompanyNews` | symbol, start_date, end_date, limit | date, title, text, url, images | `/news/company` |
| `WorldNews` | limit | date, title, text, url, images | `/news/world` |

### ESG

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `EsgScore` | symbol | date, environment_score, social_score, governance_score, total | ESG endpoints |
| `EsgRiskRating` | symbol | date, risk_rating, +more | ESG endpoints |
| `EsgSector` | sector | sector, environment, social, governance | ESG endpoints |

### Options & Derivatives

| Model Name | Query Fields | Data Fields | Used By |
|-----------|-------------|-------------|---------|
| `OptionsChains` | symbol | contract, strike, expiration, type, bid, ask, volume, open_interest, +more | `/derivatives/options/chains` |
| `OptionsUnusual` | symbol | contract, underlying, strike, type, volume, open_interest | `/derivatives/options/unusual` |
| `FuturesCurve` | symbol | date, expiration, price | `/derivatives/futures/curve` |
| `FuturesInfo` | symbol | symbol, name, exchange, +more | `/derivatives/futures/info` |
| `FuturesInstruments` | query | symbol, name | `/derivatives/futures/search` |
| `Spot` | (various) | date, price | `/commodity/spot_prices` |

---

## 4. Model File Count by Category

| Category | Count | Key Models |
|----------|-------|-----------|
| Equity/Market | ~25 | EquityHistorical, EquityQuote, EquityInfo, EquitySearch |
| Financial Statements | ~15 | BalanceSheet, IncomeStatement, CashFlowStatement + Growth |
| Estimates/Analysts | ~10 | AnalystEstimates, ForwardEps/Ebitda/Pe/Sales |
| Fixed Income | ~20 | TreasuryRates, YieldCurve, Ameribor, SOFR |
| Economy/Macro | ~25 | CPI, GDP, Unemployment, FRED, BalanceOfPayments |
| ETF | ~8 | EtfInfo, EtfHoldings, EtfSectors |
| Calendar/Events | ~6 | CalendarDividend/Earnings/Ipo/Splits |
| News | ~2 | CompanyNews, WorldNews |
| Options/Derivatives | ~8 | OptionsChains, FuturesCurve |
| Filings/SEC | ~6 | CompanyFilings, CikMap, Form13FHR |
| ESG | ~3 | EsgScore, EsgRiskRating |
| Ownership | ~4 | InsiderTrading, InstitutionalOwnership |
| Other | ~30 | Various specialized models |
| **Total** | **~161** | |

---

## 5. Key Design Principles

1. **Minimal standard, extensible extra:** Standard models define only the
   most common fields.  Providers add the rest via inheritance.

2. **`extra="allow"`:** Both `Data` and `QueryParams` accept extra fields,
   ensuring no data is lost even if the standard model doesn't declare it.

3. **Consistent naming:** `period_ending` (not `date`) for financial statements,
   `date` for time series, `symbol` for equity identifiers.

4. **Optional fields:** Most data fields are optional (`None` default) because
   not all providers supply all fields.

5. **Validators over transforms:** Data normalization happens in Pydantic
   validators (e.g., `to_upper` for symbols) rather than in business logic.

6. **Type unions:** When providers disagree on types (e.g., `int | float`),
   the standard model uses the union.

---

*Last updated: 2026-02-21*
