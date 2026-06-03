# Financial & Trading Domain Glossary for Developers

**Version:** 1.1
**Date:** 2026-03-23
**Audience:** Software engineers and developers with strong Python skills but limited financial background who are contributing to the OpenBB single-stock analysis pipeline.

This document explains every financial term, metric, and concept used in the analysis phases — from first principles. No prior finance knowledge is assumed. Academic and practitioner references are included so you can study further if you want to understand the mathematics or history behind each concept.

---

## Table of Contents

1. [The Big Picture: How Stock Analysis Works](#1-the-big-picture)
2. [Fundamental Analysis Terms](#2-fundamental-analysis-terms)
   - Growth Metrics
   - Profitability Metrics
   - Balance Sheet & Solvency
   - Cash Flow Quality
   - Capital Efficiency
   - Structural Efficiency
3. [Valuation Terms](#3-valuation-terms)
4. [Technical Analysis Terms](#4-technical-analysis-terms)
   - Trend Indicators
   - Momentum Indicators
   - Volatility Indicators
   - Volume Indicators
   - Institutional / Advanced Signals
5. [Risk & Portfolio Terms](#5-risk--portfolio-terms)
6. [Decision & Execution Terms](#6-decision--execution-terms)
7. [Key Formulas Reference](#7-key-formulas-reference)
8. [Further Reading](#8-further-reading)

---

## 1. The Big Picture

### What is stock analysis?

A stock represents a fractional ownership stake in a company. When you buy a share of Microsoft, you own a tiny piece of everything Microsoft owns — its buildings, software, brand, cash — minus everything it owes. The price of that share fluctuates based on what millions of buyers and sellers collectively think the future of the business is worth.

**The job of a stock analyst** is to answer: "Is this share worth more than what the market is currently charging for it?" If yes, and the analyst is right, the price will eventually converge to fair value and generate a profit.

**Learn more:**
- [Investopedia — How to Analyze Stocks](https://www.investopedia.com/articles/basics/09/how-to-analyze-stocks.asp)
- [FMP Education — Introduction to Stock Analysis](https://site.financialmodelingprep.com/educational/stock-analysis)
- [SEC — Beginners' Guide to Financial Statements](https://www.sec.gov/reportspubs/investor-publications/investorpubsbegfinstmtguide.htm)

### Two main schools of thought

| School | Core idea | Primary tool |
|---|---|---|
| **Fundamental analysis** | A stock is worth the present value of all future cash the business will generate | Financial statements (income statement, balance sheet, cash flow statement) |
| **Technical analysis** | Price and volume patterns predict near-term direction | Charts and indicators computed from historical prices |

Neither school is "right" — they answer different questions. Fundamental analysis tells you *what* to buy. Technical analysis tells you *when* to buy. The pipeline in this codebase uses both in sequence: fundamentals filter the universe, technicals time the entry.

**Learn more:**
- [Investopedia — Fundamental vs Technical Analysis](https://www.investopedia.com/ask/answers/difference-between-fundamental-and-technical-analysis/)

### The three financial statements

Every public company files three core documents with regulators (in the US: with the SEC):

1. **Income Statement** (also called Profit & Loss or P&L): shows revenue earned and costs incurred over a period. Think of it as a business's "scorecard" — was it profitable?
2. **Balance Sheet** (also called Statement of Financial Position): a snapshot at a specific date of everything the company *owns* (assets) minus everything it *owes* (liabilities). The difference is shareholders' equity — what owners actually have.
3. **Cash Flow Statement**: shows the actual cash that moved in and out during the period, regardless of accounting timing. Separated into: Operating (running the business), Investing (buying/selling assets), and Financing (debt/equity transactions).

> **Developer mental model:** The income statement is like a database transaction log. The balance sheet is a database snapshot. The cash flow statement is the diff log that reconciles them.

**Learn more:**
- [Investopedia — Three Financial Statements](https://www.investopedia.com/articles/04/033104.asp)
- [FMP Education — Reading Financial Statements](https://site.financialmodelingprep.com/educational/financial-statements)
- [SEC EDGAR — Company Filings Search](https://www.sec.gov/cgi-bin/browse-edgar)

---

## 2. Fundamental Analysis Terms

### 2A. Growth Metrics

---

#### Revenue (also: Sales, Top Line)
**What it is:** The total amount of money customers paid for the company's products or services before deducting any costs.
**Why it matters:** Revenue is the engine of the business. Without growing revenue, a company cannot sustainably grow profits — it can only cut costs, which is finite.
**Where it lives:** Top line of the income statement.

**Learn more:**
- [Investopedia — Revenue](https://www.investopedia.com/terms/r/revenue.asp)
- [FMP Education — Income Statement Explained](https://site.financialmodelingprep.com/educational/income-statement)

---

#### Revenue CAGR (Compound Annual Growth Rate)
**What it is:** The smoothed annual growth rate of revenue over multiple years, assuming the growth compounded every year at a constant rate.
**Formula:** `CAGR = (Revenue_end / Revenue_start)^(1/years) − 1`
**Example:** Revenue grew from $100M to $161M over 5 years. CAGR = (161/100)^(1/5) − 1 = 10%.
**Why CAGR instead of average growth?** Simple averages can be misleading. A stock that falls 50% one year and rises 100% the next has an average return of 25% per year but you are back to where you started (−50% × +100% = 0% net). CAGR shows actual compounding.
**Practical threshold:** > 8% for growth companies; > 3% for mature/value companies.
**Reference:** Damodaran, A. (2012). *Investment Valuation*. Wiley, Ch. 2.

**Learn more:**
- [Investopedia — CAGR](https://www.investopedia.com/terms/c/cagr.asp)
- [CFI — CAGR Formula and Calculator](https://corporatefinanceinstitute.com/resources/excel/cagr-formula/)

---

#### EPS (Earnings Per Share)
**What it is:** Net income (total profit after all costs and taxes) divided by the total number of shares outstanding.
**Formula:** `EPS = Net Income / Shares Outstanding`
**Why it matters:** Investors own *shares*, not the total company. EPS translates company-level profit into a per-share figure, making it comparable across companies of different sizes.
**Diluted vs basic EPS:** Diluted EPS assumes all stock options and convertible bonds have been exercised (worst case for existing shareholders). Always use diluted EPS for conservative analysis.

**Learn more:**
- [Investopedia — Earnings Per Share (EPS)](https://www.investopedia.com/terms/e/eps.asp)
- [FMP Education — EPS Explained](https://site.financialmodelingprep.com/educational/earnings-per-share)
- [Investopedia — Basic vs Diluted EPS](https://www.investopedia.com/ask/answers/difference-between-basic-and-diluted-earnings-per-share.asp)

---

#### Free Cash Flow (FCF)
**What it is:** The cash a business generates from its operations after paying for the capital it needs to maintain and grow its assets.
**Formula:** `FCF = Operating Cash Flow − Capital Expenditures (Capex)`
**Why it matters:** Profits on the income statement can be manipulated through accounting choices. Cash is harder to fake. FCF is the cash a company could theoretically pay out to shareholders today — it is the "real" return of the business.
**Developer analogy:** Revenue is the number of API calls billed. Net income is revenue minus salaries and server costs. FCF is what's left after also paying for new server capacity and software licences you need to keep growing.

**Learn more:**
- [Investopedia — Free Cash Flow (FCF)](https://www.investopedia.com/terms/f/freecashflow.asp)
- [FMP Education — Free Cash Flow](https://site.financialmodelingprep.com/educational/free-cash-flow)
- [CFI — FCF Guide](https://corporatefinanceinstitute.com/resources/valuation/free-cash-flow-fcf/)

---

### 2B. Profitability Metrics

---

#### Gross Profit and Gross Margin
**What it is:** Revenue minus the direct cost of producing what was sold (Cost of Goods Sold / COGS).
**Formula:** `Gross Profit = Revenue − COGS`; `Gross Margin = Gross Profit / Revenue`
**Example:** A software company charges $100/seat. It costs $5 in server/hosting to deliver each seat. Gross Margin = 95%.
**Why it matters:** Gross margin reveals pricing power — how much of each revenue dollar survives after paying the direct costs of the product. High gross margin businesses have more room to invest in growth, R&D, and marketing. A declining gross margin over several years is an early signal of competitive pressure.

**Learn more:**
- [Investopedia — Gross Margin](https://www.investopedia.com/terms/g/grossmargin.asp)
- [Investopedia — Gross Profit](https://www.investopedia.com/terms/g/grossprofit.asp)
- [FMP Education — Profitability Ratios](https://site.financialmodelingprep.com/educational/profitability-ratios)

---

#### Operating Income and Operating Margin
**What it is:** Gross Profit minus operating expenses (salaries, rent, R&D, sales & marketing).
**Formula:** `Operating Income = Gross Profit − Operating Expenses`; `Operating Margin = Operating Income / Revenue`
**Why it matters:** Operating margin shows how efficiently management runs the full business, not just the product economics. Two companies with identical gross margins can have very different operating margins depending on how efficiently they staff and manage their operations.

**Learn more:**
- [Investopedia — Operating Margin](https://www.investopedia.com/terms/o/operatingmargin.asp)
- [Investopedia — Operating Income](https://www.investopedia.com/terms/o/operatingincome.asp)

---

#### Net Income and Net Margin
**What it is:** Operating Income minus interest expenses (on debt) and taxes.
**Formula:** `Net Margin = Net Income / Revenue`
**Why it matters:** The "bottom line." But be careful: net income is the most manipulable metric because it includes non-cash charges (depreciation, amortisation), tax credits, and one-time items. Always read FCF alongside net income.

**Learn more:**
- [Investopedia — Net Profit Margin](https://www.investopedia.com/terms/n/net_margin.asp)
- [Investopedia — Net Income](https://www.investopedia.com/terms/n/netincome.asp)

---

#### ROIC (Return on Invested Capital)
**What it is:** How much profit the business earns for every dollar of capital invested in it (by both equity holders and debt holders).
**Formula:** `ROIC = NOPAT / Invested Capital` where `NOPAT = Operating Income × (1 − tax rate)` and `Invested Capital = Total Equity + Total Debt − Excess Cash`
**Why it matters:** ROIC is the single most important long-term return predictor for individual stocks because it measures whether the business creates or destroys value with every dollar reinvested. A company with ROIC = 20% and WACC = 9% creates 11 cents of value for every reinvested dollar. ROIC < WACC = value destruction.
**Reference:** Koller, T., Goedhart, M. & Wessels, D. (2020). *Valuation: Measuring and Managing the Value of Companies* (7th ed.). Wiley/McKinsey.

**Learn more:**
- [Investopedia — Return on Invested Capital (ROIC)](https://www.investopedia.com/terms/r/returnoninvestmentcapital.asp)
- [FMP Education — ROIC](https://site.financialmodelingprep.com/educational/return-on-invested-capital)
- [CFI — ROIC Guide](https://corporatefinanceinstitute.com/resources/valuation/roic-return-on-invested-capital/)

---

### 2C. Balance Sheet & Solvency Metrics

---

#### Debt/Equity Ratio
**What it is:** Total debt (short-term + long-term borrowings) divided by total shareholders' equity.
**Formula:** `D/E = Total Debt / Total Equity`
**Why it matters:** A high D/E ratio means the company has borrowed a lot relative to what shareholders own. If business deteriorates, the company must still pay interest on its debt — potentially squeezing out profits or requiring asset sales.
**Context is key:** A D/E of 2.0 is normal for a utility (stable cash flows support debt). A D/E of 2.0 for a volatile technology company is alarming. Always compare within sectors.

**Learn more:**
- [Investopedia — Debt-to-Equity Ratio](https://www.investopedia.com/terms/d/debtequityratio.asp)
- [FMP Education — Leverage Ratios](https://site.financialmodelingprep.com/educational/leverage-ratios)

---

#### Interest Coverage Ratio
**What it is:** How many times over the company can cover its interest payments from operating earnings.
**Formula:** `Interest Coverage = EBIT / Interest Expense` where EBIT = Earnings Before Interest and Taxes
**Example:** EBIT = $100M, Interest = $20M → Coverage = 5×. For every $1 of interest, the company earns $5 in operating profit.
**Why it matters:** A company with coverage of 1.5× is living close to the edge — a small revenue decline could make it unable to service its debt. Coverage < 2× is a distress warning.

**Learn more:**
- [Investopedia — Interest Coverage Ratio](https://www.investopedia.com/terms/i/interestcoverageratio.asp)
- [CFI — Interest Coverage Ratio](https://corporatefinanceinstitute.com/resources/accounting/interest-coverage-ratio/)

---

#### Current Ratio
**What it is:** Current Assets (cash, receivables, inventory) divided by Current Liabilities (bills due within 12 months).
**Formula:** `Current Ratio = Current Assets / Current Liabilities`
**Why it matters:** Measures short-term liquidity — can the company pay its near-term bills without selling long-term assets?
**Threshold:** > 1.2 generally considered safe. < 1.0 means short-term obligations exceed liquid assets.

**Learn more:**
- [Investopedia — Current Ratio](https://www.investopedia.com/terms/c/currentratio.asp)
- [FMP Education — Liquidity Ratios](https://site.financialmodelingprep.com/educational/liquidity-ratios)

---

#### Net Debt / EBITDA
**What it is:** How many years of EBITDA it would take to pay off the company's net debt.
**Formula:** `Net Debt = Total Debt − Cash and Equivalents`; `EBITDA = Earnings Before Interest, Taxes, Depreciation and Amortisation`
**Why it matters:** This is how credit analysts and bankers assess debt sustainability. A company with Net Debt/EBITDA of 1.5× will pay off its debt in 1.5 years at current earnings, ignoring interest — manageable. At 5×+, a small earnings shortfall triggers refinancing risk.
**Threshold:** < 2× comfortable; 2–3× manageable; > 4× elevated; > 5× high risk.

**Learn more:**
- [Investopedia — Net Debt/EBITDA](https://www.investopedia.com/terms/n/net-debt-to-ebitda-ratio.asp)
- [Investopedia — EBITDA](https://www.investopedia.com/terms/e/ebitda.asp)

---

#### Altman Z-Score
**What it is:** A mathematical model using 5 financial ratios to predict the probability of bankruptcy within the next 2 years.
**Formula:** `Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5` where:
- X1 = Working Capital / Total Assets
- X2 = Retained Earnings / Total Assets
- X3 = EBIT / Total Assets
- X4 = Market Value of Equity / Book Value of Total Debt
- X5 = Revenue / Total Assets

**Interpretation:** Z > 2.99: safe zone. 1.81–2.99: grey zone (monitor). < 1.81: distress zone — high bankruptcy probability.
**Reference:** Altman, E.I. (1968). "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy." *Journal of Finance*, 23(4), 589–609. Documented 72–80% accuracy predicting bankruptcies 2 years in advance.

**Learn more:**
- [Investopedia — Altman Z-Score](https://www.investopedia.com/terms/a/altman.asp)
- [FMP Education — Altman Z-Score](https://site.financialmodelingprep.com/educational/altman-z-score)
- [NYU Stern — Altman Z-Score Data (Damodaran)](http://pages.stern.nyu.edu/~adamodar/)

---

### 2D. Cash Flow Quality

---

#### CFO / Net Income (Cash Conversion Ratio)
**What it is:** Operating Cash Flow (CFO) divided by Net Income — measures the fraction of reported profits that are backed by real cash.
**Formula:** `CFO / NI = Operating Cash Flow / Net Income`
**Why it matters:** Net income includes accrual accounting entries (revenue booked before cash received, costs deferred after cash paid). If the ratio is well below 1.0, profits are "papery" — not backed by cash. Healthy range: 0.9–1.2.
**Example:** Net Income = $100M, CFO = $50M → Ratio 0.5 → every $1 of reported profit only generated $0.50 in cash. Dangerous.

**Learn more:**
- [Investopedia — Cash Flow to Net Income](https://www.investopedia.com/terms/c/cashflowstatement.asp)
- [Investopedia — Operating Cash Flow](https://www.investopedia.com/terms/o/operatingcashflow.asp)
- [CFI — Cash Flow Statement Guide](https://corporatefinanceinstitute.com/resources/accounting/cash-flow-statement/)

---

#### Accruals Ratio (Sloan Ratio)
**What it is:** A measure of how much of a company's net income consists of accounting accruals (non-cash adjustments) rather than actual cash earnings.
**Formula:** `Accruals = Net Income − Operating Cash Flow`; `Accruals Ratio = Accruals / Average Net Operating Assets`
**Why it matters — the academic story:** Richard Sloan published research in 1996 showing that companies with high accruals (much more income than cash) consistently *underperformed* the stock market in subsequent years, because accrual-heavy earnings tend to reverse. This finding was so reliable and so large (10% per year abnormal returns) that it became known as the "accrual anomaly."
**Practical meaning:** A company can legally book revenue before cash arrives (accounts receivable), defer cost recognition, or capitalise expenses as assets. None of this is fraud — it's standard accounting. But it means the income statement overstates economic performance. High accruals are a warning: the income statement will likely "catch down" to the cash flow statement in future periods.
**Reference:** Sloan, R.G. (1996). "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?" *The Accounting Review*, 71(3), 289–315.

**Learn more:**
- [Investopedia — Accrual Accounting](https://www.investopedia.com/terms/a/accrualaccounting.asp)
- [Investopedia — Earnings Quality](https://www.investopedia.com/terms/e/earningsquality.asp)
- [CFA Institute — Earnings Quality Analysis](https://www.cfainstitute.org/en/membership/professional-development/refresher-readings/analysis-income-taxes)

---

### 2E. Capital Efficiency

---

#### DuPont Analysis (3-Factor ROE Decomposition)
**What it is:** A mathematical decomposition of Return on Equity into three drivers: how profitable the business is per sale, how efficiently it uses its assets to generate sales, and how leveraged it is.
**Formula:** `ROE = Net Margin × Asset Turnover × Equity Multiplier`
- `Net Margin = Net Income / Revenue` (profitability per dollar of revenue)
- `Asset Turnover = Revenue / Total Assets` (revenue generated per dollar of assets)
- `Equity Multiplier = Total Assets / Equity` (leverage — how much of the assets are debt-funded)

**Why it matters:** Two companies can post the same 20% ROE with completely different business models. DuPont shows *why* ROE is what it is. A luxury brand might have Net Margin 25%, Asset Turnover 0.5×, and Equity Multiplier 1.6× = ROE 20%. A grocery retailer might have Net Margin 2%, Asset Turnover 5×, and Equity Multiplier 2× = ROE 20%. Same result, completely different businesses and risk profiles.
**Reference:** Penman, S. (2013). *Financial Statement Analysis and Security Valuation* (5th ed.). McGraw-Hill, Ch. 11.

**Learn more:**
- [Investopedia — DuPont Analysis](https://www.investopedia.com/terms/d/dupontanalysis.asp)
- [CFI — DuPont Analysis Guide](https://corporatefinanceinstitute.com/resources/accounting/dupont-analysis/)
- [FMP Education — Return on Equity (ROE)](https://site.financialmodelingprep.com/educational/return-on-equity)

---

#### Gross Profitability Ratio
**What it is:** Gross Profit divided by Total Assets — measures how much gross profit the business generates per dollar of assets it holds.
**Formula:** `Gross Profitability = Gross Profit / Total Assets`
**Why it matters:** Robert Novy-Marx discovered in 2013 that this simple ratio predicts future stock returns as powerfully as the classic "value" metric (Price-to-Book ratio). The reason: gross profit is the hardest income line to manipulate. Net income can be depressed by amortisation of past acquisitions, restructuring charges, or tax timing — all "real" but not reflecting current business economics. Gross profit strips all of that away. A company that generates a lot of gross profit per dollar of assets is doing something genuinely valuable that competitors struggle to replicate.
**Reference:** Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics*, 108(1), 1–28.

**Learn more:**
- [Investopedia — Gross Profitability](https://www.investopedia.com/terms/g/gross-profit.asp)
- [AQR — Quality Minus Junk (related factor paper)](https://www.aqr.com/Insights/Research/Journal-Article/Quality-Minus-Junk)
- [SSRN — Novy-Marx 2013 Paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2233698)

---

#### Share Dilution / Buyback Trend
**What it is:** The change in the total number of shares outstanding over time.
**Why it matters:** If a company issues new shares (stock options vested, secondary offering, acquisition with stock), the total pie is divided into more pieces — each existing shareholder owns a smaller percentage of the same company. This is "dilution" and it quietly reduces the value of your stake even if the company's total profits grow. Conversely, when a company buys back its own shares, each remaining share represents a larger ownership percentage — this is return of capital to shareholders and increases per-share metrics.
**Formula:** `Dilution Rate = (Shares_today − Shares_5yr_ago) / Shares_5yr_ago`
**Reference:** Loughran, T. & Ritter, J.R. (1995). "The New Issues Puzzle." *Journal of Finance*, 50(1), 23–51.

**Learn more:**
- [Investopedia — Stock Dilution](https://www.investopedia.com/terms/d/dilution.asp)
- [Investopedia — Share Buybacks](https://www.investopedia.com/terms/b/buyback.asp)
- [FMP Education — Shares Outstanding](https://site.financialmodelingprep.com/educational/shares-outstanding)

---

#### Operating Leverage
**What it is:** How sensitive a company's profits are to changes in revenue. A highly leveraged business has large fixed costs — so small revenue changes cause large profit swings.
**Formula:** `Operating Leverage = % Change in EBIT / % Change in Revenue`
**Example:** Revenue falls 10%. Operating Leverage = 2.5×. → EBIT falls 25%. This is the multiplier effect of fixed costs.
**Why it matters:** Operating leverage is invisible in financial ratios until revenue turns down. A software company with 80% gross margins and mostly fixed employee costs has enormous operating leverage — in good times margins expand rapidly; in a downturn, every lost revenue dollar hits profit almost fully. This is why pre-revenue growth stocks collapse so violently in bear markets.
**Reference:** Novy-Marx, R. (2011). "Operating Leverage." *Review of Finance*, 15(1), 103–134.

**Learn more:**
- [Investopedia — Operating Leverage](https://www.investopedia.com/terms/o/operatingleverage.asp)
- [CFI — Degree of Operating Leverage (DOL)](https://corporatefinanceinstitute.com/resources/accounting/degree-of-operating-leverage/)

---

## 3. Valuation Terms

---

#### Price-to-Earnings (P/E Ratio)
**What it is:** How many years of current earnings you are paying for the stock.
**Formula:** `P/E = Stock Price / EPS`
**Example:** MSFT at $400, EPS $12 → P/E = 33×. The market is willing to pay 33 years of today's profits for the stock.
**Why it matters:** P/E is the most-watched valuation metric. A high P/E means the market expects future growth to justify the price — or the stock is overvalued. A low P/E might mean the stock is cheap — or that the market correctly expects earnings to decline.
**Key nuance:** Compare P/E vs the company's *own historical P/E* (5-year median) and *sector peers* — not against an absolute number. A tech company trading at 25× P/E vs its own 5Y median of 35× P/E may be cheap, even though 25× sounds expensive.

**Learn more:**
- [Investopedia — P/E Ratio](https://www.investopedia.com/terms/p/price-earningsratio.asp)
- [FMP Education — Price to Earnings Ratio](https://site.financialmodelingprep.com/educational/price-to-earnings-ratio)
- [Damodaran Online — P/E Ratios by Sector](http://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html)

---

#### EV/EBITDA (Enterprise Value to EBITDA)
**What it is:** Enterprise Value (total value of the business — equity + debt − cash) divided by EBITDA (operating profit before non-cash charges and financing costs).
**Why it's better than P/E for some comparisons:** P/E is affected by capital structure (how much debt a company has) because interest expense reduces net income. EV/EBITDA removes this distortion — you can compare a debt-heavy company with a debt-free company on the same basis.
**Example:** Company A: P/E = 15×, but has $5B in debt. Company B: P/E = 20×, but debt-free. EV/EBITDA might show Company A is actually the more expensive one on an enterprise basis.

**Learn more:**
- [Investopedia — EV/EBITDA](https://www.investopedia.com/terms/e/ev-ebitda.asp)
- [Investopedia — Enterprise Value (EV)](https://www.investopedia.com/terms/e/enterprisevalue.asp)
- [FMP Education — EV/EBITDA](https://site.financialmodelingprep.com/educational/ev-ebitda)

---

#### DCF (Discounted Cash Flow)
**What it is:** A method to estimate what a company is worth today based on the present value of all the free cash flows it will generate in the future.
**The core idea — time value of money:** $100 today is worth more than $100 in 5 years because you could invest $100 today and have more in 5 years. The "discount rate" (WACC) represents the required return — how much you need to earn to justify waiting.
**Formula:**
```
Fair Value = Σ [ FCF_t / (1 + WACC)^t ]   for each future year t
           + Terminal Value / (1 + WACC)^last_year
```
**Terminal Value:** A company does not stop existing after 5 or 10 years. We capture the "rest of forever" using the Gordon Growth Model: `TV = FCF_last × (1 + g_terminal) / (WACC − g_terminal)` where g_terminal is the assumed long-run growth rate.
**Developer analogy:** DCF is like computing the NPV (Net Present Value) of a project in capital budgeting. The "project" is the business, and the "cash flows" are free cash flows to equity holders.
**Reference:** Damodaran, A. (2012). *Investment Valuation*. Wiley. Also: Koller, Goedhart & Wessels (2020). *Valuation*. Wiley/McKinsey.

**Learn more:**
- [Investopedia — Discounted Cash Flow (DCF)](https://www.investopedia.com/terms/d/dcf.asp)
- [FMP Education — DCF Valuation](https://site.financialmodelingprep.com/educational/discounted-cash-flow)
- [Damodaran Online — DCF Valuation Spreadsheets](http://pages.stern.nyu.edu/~adamodar/New_Home_Page/spreadsh.htm)
- [CFI — DCF Model Training](https://corporatefinanceinstitute.com/resources/valuation/dcf-model-training-free-guide/)

---

#### WACC (Weighted Average Cost of Capital)
**What it is:** The required rate of return for the business as a whole — a weighted average of the cost of equity and the after-tax cost of debt.
**Formula:** `WACC = (E/V × Re) + (D/V × Rd × (1−T))` where:
- E = equity market value, D = debt market value, V = E + D
- Re = cost of equity (from CAPM), Rd = cost of debt (interest rate), T = tax rate

**Why it matters:** WACC is the denominator in every DCF calculation. A higher WACC produces a lower fair value — it means investors require a higher return to compensate for the risk. Technology companies typically have higher WACCs than utilities because their cash flows are less predictable.
**Common mistake:** Using a single WACC for all companies. WACC must be calibrated to the specific company's risk profile.

**Learn more:**
- [Investopedia — WACC](https://www.investopedia.com/terms/w/wacc.asp)
- [FMP Education — WACC](https://site.financialmodelingprep.com/educational/wacc)
- [Damodaran Online — WACC by Sector](http://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/wacc.html)

---

#### Margin of Safety
**What it is:** The discount between a stock's current price and its estimated intrinsic (fair) value, expressed as a percentage.
**Formula:** `MOS = (Fair Value − Current Price) / Fair Value`
**Example:** DCF fair value = $120. Current price = $90. MOS = 25%.
**Why it matters:** Benjamin Graham (Warren Buffett's teacher) introduced the margin of safety concept to account for the fact that no DCF estimate is precise. If your fair value estimate could be off by 20%, a 25% margin of safety gives you a buffer — even if your model is wrong, you still paid a reasonable price.
**Reference:** Graham, B. & Dodd, D. (1934). *Security Analysis*. McGraw-Hill — foundational value investing text; margin of safety introduced in Ch. 20.

**Learn more:**
- [Investopedia — Margin of Safety](https://www.investopedia.com/terms/m/marginofsafety.asp)
- [FMP Education — Intrinsic Value](https://site.financialmodelingprep.com/educational/intrinsic-value)

---

#### Piotroski F-Score
**What it is:** A checklist of 9 yes/no questions about a company's financial health, producing a score from 0 to 9.
**The 9 tests** (each adds 1 point):
1. ROA > 0 (profitable)
2. Operating Cash Flow > 0
3. ROA increased vs last year
4. CFO / Total Assets > ROA (cash earnings > accounting earnings)
5. Long-term debt decreased
6. Current Ratio improved
7. No new shares issued
8. Gross Margin improved
9. Asset Turnover improved

**Interpretation:** 7–9: financially strong. 0–3: financially weak.
**Reference:** Piotroski, J.D. (2000). "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers." *Journal of Accounting Research*, 38 (Supplement), 1–41.

**Learn more:**
- [Investopedia — Piotroski Score](https://www.investopedia.com/terms/p/piotroski-score.asp)
- [FMP Education — Piotroski F-Score](https://site.financialmodelingprep.com/educational/piotroski-score)

---

#### Reverse-DCF
**What it is:** Instead of forecasting future cash flows to get a fair value, you start from the *current market price* and work backwards to find what growth rate the market is implicitly assuming.
**How it works:** You set Fair Value = Current Price in the DCF formula and solve for g_short (the growth rate). This is mathematically just an equation root-finding problem.
**Why it matters:** It reframes the question from "Is this stock cheap?" to "What does the market believe, and do I agree?" If a mature company with flat revenue growth is priced at an implied growth rate of 18%, you know the market is pricing in something that is not happening — the stock is expensive on realistic assumptions.
**Reference:** Mauboussin, M. & Johnson, P. (1997). "Competitive Advantage Period." *Financial Management*, 26(2), 67–74. Also: Rappaport, A. & Mauboussin, M. (2001). *Expectations Investing*. Harvard Business School Press.

**Learn more:**
- [Investopedia — Reverse DCF Model](https://www.investopedia.com/articles/fundamentals/11/reverse-engineering-dcf.asp)
- [CFI — Reverse DCF](https://corporatefinanceinstitute.com/resources/valuation/reverse-dcf-model/)

---

## 4. Technical Analysis Terms

> **Important context for developers:** Technical analysis works not because price patterns have mystical predictive power, but because many market participants observe the *same* levels and indicators and respond to them similarly. This creates self-fulfilling dynamics at widely-watched levels. The academic literature is mixed on whether TA works in isolation, but substantial evidence supports its value as a *timing* tool layered on top of fundamental selection.

---

### 4A. Trend Indicators

---

#### Simple Moving Average (SMA)
**What it is:** The arithmetic average of closing prices over a rolling window of N days.
**Formula:** `SMA(N) = (Price_1 + Price_2 + ... + Price_N) / N`
**Common periods:** SMA50 (50-day), SMA200 (200-day).
**Why it matters:** A moving average smooths out daily noise and reveals the underlying trend direction. Price above its 200-day SMA means the stock is in a long-term uptrend on average over the last ~10 months.

**Learn more:**
- [Investopedia — Simple Moving Average (SMA)](https://www.investopedia.com/terms/s/sma.asp)
- [FMP Education — Moving Averages](https://site.financialmodelingprep.com/educational/moving-averages)

---

#### Golden Cross / Death Cross
**What it is:** When a shorter-period SMA crosses above (Golden Cross) or below (Death Cross) a longer-period SMA.
**Standard definition:** SMA50 crossing above SMA200 = Golden Cross (bullish). SMA50 crossing below SMA200 = Death Cross (bearish).
**Why it matters:** These crosses signal a change in the intermediate trend. They are widely followed by institutional algorithmic strategies, creating mechanical buying (Golden Cross) and selling (Death Cross) pressure.

**Learn more:**
- [Investopedia — Golden Cross](https://www.investopedia.com/terms/g/goldencross.asp)
- [Investopedia — Death Cross](https://www.investopedia.com/terms/d/deathcross.asp)

---

#### ADX (Average Directional Index)
**What it is:** A measure of the *strength* of a price trend, regardless of direction (up or down). Range: 0–100.
**Formula:** Computed from True Range and Directional Movement indicators (complex; uses Wilder smoothing).
**Interpretation:** ADX < 20: trend is weak or absent (ranging market). ADX 20–25: trend beginning. ADX > 25: strong trend. ADX > 40: very strong trend.
**Key insight:** ADX does NOT tell you whether the trend is up or down — it only measures how strong the trend is. Use alongside direction indicators (price vs SMA, MACD) to get the full picture.
**Reference:** Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.

**Learn more:**
- [Investopedia — ADX](https://www.investopedia.com/terms/a/adx.asp)
- [StockCharts — ADX School](https://school.stockcharts.com/doku.php?id=technical_indicators:average_directional_index_adx)

---

#### VWAP (Volume-Weighted Average Price)
**What it is:** The average price a stock has traded at, weighted by the volume traded at each price. It gives more weight to prices where more shares changed hands.
**Formula:** `VWAP = Σ(Price_i × Volume_i) / Σ(Volume_i)` where typical price = (High + Low + Close) / 3
**Why it matters:** VWAP is the standard benchmark for institutional order execution. Large funds are evaluated against VWAP — did they buy below or above the average price? This makes VWAP a self-reinforcing support/resistance level: institutions constantly buying "at or below VWAP" creates a gravitational pull toward the VWAP line.
**Anchored VWAP:** The same calculation but reset to a specific anchor date (e.g., post-earnings gap), measuring the average price since that event.

**Learn more:**
- [Investopedia — VWAP](https://www.investopedia.com/terms/v/vwap.asp)
- [StockCharts — VWAP](https://school.stockcharts.com/doku.php?id=technical_indicators:vwap_intraday)

---

#### Ichimoku Cloud
**What it is:** A Japanese technical analysis system using five lines derived from price to identify trend direction, momentum, and support/resistance simultaneously.
**Five components:**
- **Tenkan-sen (Conversion Line, 9 periods):** Midpoint of the 9-period high-low range. Fast signal line.
- **Kijun-sen (Base Line, 26 periods):** Midpoint of the 26-period high-low range. Slow signal line. Price below Kijun = bearish.
- **Senkou Span A:** Average of Tenkan and Kijun, plotted 26 periods *forward*. Forms one boundary of the cloud.
- **Senkou Span B:** Midpoint of 52-period high-low range, plotted 26 periods forward. Forms the other boundary.
- **Chikou Span:** Current close plotted 26 periods backward. Acts as a confirmation — bullish when it plots above the historical candles.

**The Cloud (Kumo):** The area between Senkou Span A and B. Thick cloud = strong support/resistance. Thin cloud = weak support that can be easily broken.
**Three-confirmation buy signal:** Price above cloud + Tenkan above Kijun + Chikou above historical price 26 bars ago. This combination has a substantially lower false-signal rate than any single indicator.
**Reference:** Péloille, N. (2017). *Trading with Ichimoku Clouds*. Wiley.

**Learn more:**
- [Investopedia — Ichimoku Cloud](https://www.investopedia.com/terms/i/ichimoku-cloud.asp)
- [StockCharts — Ichimoku Cloud School](https://school.stockcharts.com/doku.php?id=technical_indicators:ichimoku_cloud)

---

### 4B. Momentum Indicators

---

#### RSI (Relative Strength Index)
**What it is:** A momentum oscillator measuring the speed and change of price movements. Scale: 0–100.
**Formula:** `RSI = 100 − 100 / (1 + RS)` where `RS = Average Gain / Average Loss` over 14 periods (using Wilder smoothing).
**Traditional interpretation:**
- RSI > 70: overbought (may be due for a pullback)
- RSI < 30: oversold (may be due for a bounce)

**Advanced interpretation for trend traders:** In strong uptrends, RSI tends to range between 40–80. A pullback to 40–50 RSI within an uptrend is a *buying opportunity* (trend resumption), not a sell signal. Context matters more than absolute RSI level.
**Reference:** Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.

**Learn more:**
- [Investopedia — RSI](https://www.investopedia.com/terms/r/rsi.asp)
- [StockCharts — RSI School](https://school.stockcharts.com/doku.php?id=technical_indicators:relative_strength_index_rsi)
- [FMP Education — RSI](https://site.financialmodelingprep.com/educational/relative-strength-index)

---

#### MACD (Moving Average Convergence Divergence)
**What it is:** A trend-following momentum indicator showing the relationship between two EMAs (Exponential Moving Averages).
**Three components:**
- **MACD Line:** EMA(12) − EMA(26) of closing price
- **Signal Line:** EMA(9) of the MACD Line
- **Histogram:** MACD Line − Signal Line (shows the momentum of momentum)

**What it signals:**
- MACD Line crossing above Signal Line: bullish momentum is accelerating
- MACD Line crossing below Signal Line: bearish momentum is accelerating
- Histogram shrinking: current momentum is fading
- MACD cross above zero line: medium-term trend is bullish (strongest signal)

**Reference:** Appel, G. (1979). *The Moving Average Convergence-Divergence Trading Method*. Scientific Investment Systems.

**Learn more:**
- [Investopedia — MACD](https://www.investopedia.com/terms/m/macd.asp)
- [StockCharts — MACD School](https://school.stockcharts.com/doku.php?id=technical_indicators:moving_average_convergence_divergence_macd)
- [FMP Education — MACD](https://site.financialmodelingprep.com/educational/macd)

---

#### Stochastic Oscillator (14,3,3)
**What it is:** Compares a closing price to its price range over a given period, producing %K and %D lines. Scale: 0–100.
**Formula:** `%K = (Close − Lowest_Low_14) / (Highest_High_14 − Lowest_Low_14) × 100`; `%D = SMA(3) of %K`
**Interpretation:** < 20: oversold. > 80: overbought. %K crossing above %D from below 20: bullish entry signal. Works best in ranging/sideways markets.

**Learn more:**
- [Investopedia — Stochastic Oscillator](https://www.investopedia.com/terms/s/stochasticoscillator.asp)
- [StockCharts — Stochastic Oscillator School](https://school.stockcharts.com/doku.php?id=technical_indicators:stochastic_oscillator_fast_slow_and_full)

---

#### Rate of Change (ROC)
**What it is:** The percentage change in price over a specified lookback period.
**Formula:** `ROC(n) = (Close_today / Close_{today−n} − 1) × 100`
**Why it matters:** ROC is the direct measure of the momentum anomaly — the documented finding (Jegadeesh & Titman, 1993) that stocks with strong 3–12 month price momentum continue to outperform in the following 3–12 months. ROC over 60–120 days is approximately what the institutional momentum strategies that drive the anomaly use.

**Learn more:**
- [Investopedia — Rate of Change (ROC)](https://www.investopedia.com/terms/p/pricerateofchange.asp)
- [StockCharts — Price ROC School](https://school.stockcharts.com/doku.php?id=technical_indicators:rate_of_change_roc_and_momentum)

---

### 4C. Volatility Indicators

---

#### ATR (Average True Range)
**What it is:** The average size of a stock's daily price range over 14 days (Wilder smoothing), measuring typical volatility.
**True Range = max of:**
1. High − Low (daily range)
2. |High − Previous Close| (gap up)
3. |Low − Previous Close| (gap down)

**Why it matters — for position sizing and stops:** ATR translates abstract percentage moves into dollar terms. If ATR = $5 on a $100 stock, a normal day's price swing is $5. Setting a stop at 2× ATR = $10 below entry gives room for the stock to fluctuate normally without stopping you out on random noise.

**Learn more:**
- [Investopedia — Average True Range (ATR)](https://www.investopedia.com/terms/a/atr.asp)
- [StockCharts — ATR School](https://school.stockcharts.com/doku.php?id=technical_indicators:average_true_range_atr)

---

#### Bollinger Bands
**What it is:** A price channel drawn at 2 standard deviations above and below a 20-day SMA.
**Formula:** Upper Band = SMA20 + 2×σ20; Lower Band = SMA20 − 2×σ20; BB Width = (Upper − Lower) / SMA20
**Bollinger Band Squeeze:** When BB Width contracts to its narrowest in months, volatility has compressed. This often precedes a large directional move (expansion). Direction of the breakout determines whether it's bullish or bearish.
**Reference:** Bollinger, J. (2001). *Bollinger on Bollinger Bands*. McGraw-Hill.

**Learn more:**
- [Investopedia — Bollinger Bands](https://www.investopedia.com/terms/b/bollingerbands.asp)
- [BollingerBands.com — Official Resource](https://www.bollingerbands.com/)
- [StockCharts — Bollinger Bands School](https://school.stockcharts.com/doku.php?id=technical_indicators:bollinger_bands)

---

### 4D. Volume Indicators

---

#### OBV (On-Balance Volume)
**What it is:** A cumulative total of daily volume, added on up-days and subtracted on down-days.
**Formula:** If close > prior close: `OBV = OBV_prior + Volume`; if close < prior close: `OBV = OBV_prior − Volume`
**Why it matters:** OBV reveals whether volume is flowing into or out of a stock over time. If price is rising but OBV is flat or falling, institutional sellers are distributing shares into the buying — a warning. If price is consolidating but OBV is rising, institutions are quietly accumulating — a bullish divergence.
**Reference:** Granville, J. (1963). *Granville's New Key to Stock Market Profits*. Prentice-Hall — introduced OBV.

**Learn more:**
- [Investopedia — On-Balance Volume (OBV)](https://www.investopedia.com/terms/o/onbalancevolume.asp)
- [StockCharts — OBV School](https://school.stockcharts.com/doku.php?id=technical_indicators:on_balance_volume_obv)

---

#### Chaikin Money Flow (CMF)
**What it is:** A normalised 21-day oscillator measuring the intensity of buying or selling pressure, weighted by where each close falls within the day's high-low range.
**Formula:** `Money Flow Multiplier = [(Close − Low) − (High − Close)] / (High − Low)`; `CMF = Σ(MFM × Volume, 21) / Σ(Volume, 21)`
**Interpretation:** CMF > 0: net buying pressure. CMF < 0: net selling pressure. A stock can have rising OBV (long-term accumulation) but negative CMF (recent near-term distribution) — this divergence is a near-term caution signal.

**Learn more:**
- [Investopedia — Chaikin Money Flow (CMF)](https://www.investopedia.com/terms/c/chaikinoscillator.asp)
- [StockCharts — CMF School](https://school.stockcharts.com/doku.php?id=technical_indicators:chaikin_money_flow_cmf)

---

### 4E. Institutional and Advanced Signals

---

#### Fibonacci Retracement Levels
**What it is:** Horizontal price levels derived from the Fibonacci sequence (0.236, 0.382, 0.500, 0.618, 0.786) marking how much of a prior swing has been retraced.
**How to draw:** Identify the most recent significant swing low and swing high. Apply the ratios to the range:
```
38.2% retracement = swing_high − 0.382 × (swing_high − swing_low)
```
**Why it works in markets:** Not because markets are inherently Fibonacci. Because enough market participants (institutional desks, algorithms, retail traders) watch these levels and place orders at them — creating the self-fulfilling support/resistance. The 61.8% level (the "golden ratio") is particularly watched.
**Reference:** Carney, S. (2010). *Harmonic Trading, Volume 1*. FT Press. Academic validation: Osler, C.L. (2000). *Support for Resistance*. Federal Reserve Bank of New York.

**Learn more:**
- [Investopedia — Fibonacci Retracement](https://www.investopedia.com/terms/f/fibonacciretracement.asp)
- [StockCharts — Fibonacci Retracements School](https://school.stockcharts.com/doku.php?id=chart_analysis:fibonacci_retracemen)

---

#### 52-Week High Proximity
**What it is:** The percentage distance between the current price and the highest price reached in the past 252 trading days (one year).
**Formula:** `Distance = (High_252 − Close) / High_252`
**Why it matters:** George & Hwang (2004) found that stocks within 3–5% of their 52-week high outperform in subsequent months. Two mechanisms: (1) investor anchoring — people who bought near the high are reluctant to sell until they "get back to break-even," creating reduced overhead supply as the level is approached; (2) breakout mechanics — algorithmic momentum strategies systematically buy new 52-week highs.
**Reference:** George, T.J. & Hwang, C. (2004). "The 52-Week High and Momentum Investing." *Journal of Finance*, 59(5), 2145–2176.

**Learn more:**
- [Investopedia — 52-Week High/Low](https://www.investopedia.com/terms/1/52weekhighlow.asp)
- [Investopedia — Anchoring Bias](https://www.investopedia.com/terms/a/anchoring.asp)

---

## 5. Risk & Portfolio Terms

---

#### Sharpe Ratio
**What it is:** The excess return over the risk-free rate (e.g., US Treasury bills), divided by the total volatility of returns. The most widely-used risk-adjusted return metric.
**Formula:** `Sharpe = (Annualised Return − Risk-Free Rate) / Annualised Standard Deviation of Returns`
**Interpretation:** > 1.0: acceptable. > 1.5: strong. > 2.0: excellent. < 0: the stock did not compensate for its volatility.
**Limitation:** Sharpe treats upside and downside volatility equally. A stock that jumps 15% on an earnings beat gets "penalised" the same as one that crashes 15%.
**Reference:** Sharpe, W.F. (1966). "Mutual Fund Performance." *Journal of Business*, 39(1), 119–138.

**Learn more:**
- [Investopedia — Sharpe Ratio](https://www.investopedia.com/terms/s/sharperatio.asp)
- [FMP Education — Sharpe Ratio](https://site.financialmodelingprep.com/educational/sharpe-ratio)
- [CFA Institute — Risk-Adjusted Performance Measures](https://www.cfainstitute.org/en/membership/professional-development/refresher-readings/portfolio-performance-evaluation)

---

#### Sortino Ratio
**What it is:** Like the Sharpe Ratio, but only penalises *downside* volatility (losses below a target return, usually 0).
**Formula:** `Sortino = (Annualised Return − Risk-Free Rate) / Downside Deviation`
**Why better than Sharpe in some cases:** Investors do not dislike upside volatility — they dislike losses. A stock with high Sortino and lower Sharpe has the good kind of volatility: big up-days and small down-days. The gap between Sortino and Sharpe tells you the asymmetry of returns.

**Learn more:**
- [Investopedia — Sortino Ratio](https://www.investopedia.com/terms/s/sortinoratio.asp)
- [CFI — Sortino Ratio](https://corporatefinanceinstitute.com/resources/career-map/sell-side/capital-markets/sortino-ratio/)

---

#### Beta
**What it is:** How much the stock typically moves for every 1% move in the market (usually measured vs the S&P 500).
**Formula:** `Beta = Covariance(Stock Returns, Market Returns) / Variance(Market Returns)`
**Interpretation:** Beta 1.0: moves with the market. Beta 1.5: moves 50% more than the market. Beta 0.6: moves 40% less than the market. Beta 0 (approximately): gold, uncorrelated to equity markets.
**Important nuance:** Beta is not stable over time. During market crashes, most stocks exhibit beta > their normal level — correlations rise in crises. This is why regime-conditional beta (separate up-market and down-market betas) is more informative.

**Learn more:**
- [Investopedia — Beta](https://www.investopedia.com/terms/b/beta.asp)
- [FMP Education — Beta](https://site.financialmodelingprep.com/educational/beta)
- [Investopedia — Capital Asset Pricing Model (CAPM)](https://www.investopedia.com/terms/c/capm.asp)

---

#### Value at Risk (VaR) and Conditional VaR (CVaR)
**VaR (95%):** The one-day loss that will not be exceeded on 95% of trading days. If daily VaR is −2%, then on 19 of every 20 days, you will not lose more than 2%.
**CVaR (95%):** The *average* loss on the worst 5% of days (beyond VaR). Also called Expected Shortfall.
**Why CVaR is more useful than VaR:** VaR tells you the threshold; CVaR tells you how bad it gets on the worst days. A portfolio with VaR −2% and CVaR −3% has well-behaved tails. A portfolio with VaR −2% and CVaR −15% has severe tail risk that VaR masks.
**Reference:** Artzner, P. et al. (1999). "Coherent Measures of Risk." *Mathematical Finance*, 9(3), 203–228 — foundational paper establishing CVaR as a more coherent risk measure than VaR.

**Learn more:**
- [Investopedia — Value at Risk (VaR)](https://www.investopedia.com/terms/v/var.asp)
- [Investopedia — Conditional Value at Risk (CVaR)](https://www.investopedia.com/terms/c/conditional_value_at_risk.asp)
- [CFA Institute — Risk Measures Overview](https://www.cfainstitute.org/en/membership/professional-development/refresher-readings/measuring-and-managing-market-risk)

---

#### Max Drawdown
**What it is:** The largest peak-to-trough percentage decline in the equity curve over a period — the worst case loss an investor would have experienced buying at the top and selling at the bottom.
**Formula:** `MaxDD = min((equity_curve / equity_curve.cummax()) − 1)`
**Why it matters psychologically:** Humans experience loss roughly twice as painfully as equivalent gains (Kahneman & Tversky prospect theory). A MaxDD of −50% means an investor needs a 100% gain just to break even. High MaxDD positions require extraordinary conviction and discipline that most investors lack under stress.

**Learn more:**
- [Investopedia — Maximum Drawdown (MDD)](https://www.investopedia.com/terms/m/maximum-drawdown-mdd.asp)
- [Investopedia — Prospect Theory](https://www.investopedia.com/terms/p/prospecttheory.asp)

---

#### Ulcer Index
**What it is:** A measure that captures both the *depth* and *duration* of drawdowns — squaring the drawdown values to penalise prolonged losses more heavily.
**Formula:** `Ulcer = sqrt(mean(drawdown_series^2))`
**Why it's better than MaxDD alone:** Two stocks can have identical MaxDD of −30% but very different recovery times. A stock that recovered in 3 weeks has a much lower Ulcer Index than one that stayed −20% to −30% underwater for 18 months. The Ulcer Index captures the "how long you suffered" dimension.

**Learn more:**
- [Investopedia — Ulcer Index](https://www.investopedia.com/terms/u/ulcerindex.asp)
- [Peter Martin — Original Ulcer Index Paper](https://www.tangotools.com/ui/ui.htm)

---

#### Calmar Ratio
**What it is:** Annualised return divided by the absolute magnitude of maximum drawdown.
**Formula:** `Calmar = Annualised Return / |Max Drawdown|`
**Interpretation:** Calmar 1.0: earned as much as you lost at the worst point. Calmar 2.0: earned twice the worst drawdown. Higher is better.
**Why useful:** The Sharpe Ratio tells you about average volatility; the Calmar Ratio tells you about the worst pain point. For investors with loss aversion, Calmar is a more emotionally honest measure of risk-adjusted return.

**Learn more:**
- [Investopedia — Calmar Ratio](https://www.investopedia.com/terms/c/calmarratio.asp)
- [CFI — Calmar Ratio](https://corporatefinanceinstitute.com/resources/career-map/sell-side/capital-markets/calmar-ratio/)

---

#### Kelly Criterion
**What it is:** A mathematical formula giving the theoretically optimal fraction of capital to bet on each trade to maximise long-run wealth growth.
**Formula:** `Kelly fraction = (p × b − q) / b` where p = probability of winning, q = 1−p, b = ratio of average win to average loss.
**In returns language:** `Kelly = win_rate × (avg_win / avg_loss) − (1 − win_rate)) / (avg_win / avg_loss)`
**Half-Kelly:** In practice, full Kelly produces very large position sizes and high volatility of outcomes. Professional traders and portfolio managers use "half-Kelly" (50% of the formula's output) as a compromise between growth maximisation and drawdown control.
**Reference:** Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917–926.

**Learn more:**
- [Investopedia — Kelly Criterion](https://www.investopedia.com/terms/k/kellycriterion.asp)
- [Investopedia — Position Sizing](https://www.investopedia.com/terms/p/positionsizing.asp)

---

#### Information Ratio
**What it is:** The excess return of a stock over its benchmark (sector ETF), divided by the standard deviation of that excess return (tracking error). Measures how consistently and efficiently the stock beats its benchmark.
**Formula:** `IR = (Return_stock − Return_ETF) / Std(Return_stock − Return_ETF)`
**Why it matters:** If you hold a single stock instead of the sector ETF, you are taking "active risk" — the risk that your stock diverges from the benchmark. The Information Ratio asks: "Is the stock compensating you for that active risk?" IR > 0.5 is considered good in institutional active management.
**Reference:** Grinold, R. & Kahn, R. (1999). *Active Portfolio Management* (2nd ed.). McGraw-Hill.

**Learn more:**
- [Investopedia — Information Ratio](https://www.investopedia.com/terms/i/informationratio.asp)
- [CFA Institute — Active Return and Tracking Error](https://www.cfainstitute.org/en/membership/professional-development/refresher-readings/portfolio-performance-evaluation)

---

## 6. Decision & Execution Terms

---

#### R-Multiple (Risk-Based Position Sizing)
**What it is:** A framework that normalises all trades by their initial risk (R), so outcomes are measured in multiples of what you risked rather than in dollar or percentage terms.
**How it works:**
- Define your stop: e.g., buy at $100, stop at $94 → R = $6 per share
- Target 1 = entry + 1R = $106
- Target 2 = entry + 2R = $112 (minimum acceptable reward for taking the trade)

**Why it matters:** It enforces consistent risk management and prevents "letting losers run" and "cutting winners early." If you only take trades with at least 2R potential, you only need to be right 33% of the time to break even.
**Reference:** Tharp, V.K. (2008). *Trade Your Way to Financial Freedom* (2nd ed.). McGraw-Hill — systematised the R-multiple framework.

**Learn more:**
- [Investopedia — Risk/Reward Ratio](https://www.investopedia.com/terms/r/riskrewardratio.asp)
- [Investopedia — Position Sizing in Trading](https://www.investopedia.com/articles/trading/09/determine-position-size.asp)

---

#### Staged Entry (Tranching)
**What it is:** Building a full position in 2–3 purchases ("tranches") over time rather than buying all at once.
**Why traders use it:** No one knows the exact bottom. By splitting entries, you reduce the impact of being early. If the stock dips after your first tranche, your second tranche lowers your average cost. If the stock immediately rises, your second and third tranches confirm the setup is working before full commitment.

**Learn more:**
- [Investopedia — Dollar-Cost Averaging](https://www.investopedia.com/terms/d/dollarcostaveraging.asp)
- [Investopedia — Scaling In](https://www.investopedia.com/terms/s/scalein.asp)

---

#### Time Stop
**What it is:** An exit rule that says: "If the stock has not moved meaningfully in the direction of my thesis within N days, exit regardless of whether the price stop has been hit."
**Why it matters:** Opportunity cost is real. Capital locked in a position that is going nowhere (even without hitting the stop) cannot be deployed into better opportunities. A time stop of 63 days (1 quarter) forces a reassessment each earnings cycle.

**Learn more:**
- [Investopedia — Time Stop](https://www.investopedia.com/terms/t/time-stop.asp)
- [Investopedia — Opportunity Cost](https://www.investopedia.com/terms/o/opportunitycost.asp)

---

#### Trailing Stop
**What it is:** A stop loss that moves up automatically as the price rises, locking in a portion of gains.
**Example:** Enter at $100, stop at $94. Price rises to $106 (1R gain). Move stop to $100 (break-even). Price rises to $112 (2R). Move stop to $104. If price reverses, you exit at $104 with a $4 gain per share.
**Why it matters:** Trailing stops convert the psychology from "I might lose" to "How much of my gain do I keep?" This allows winning positions to run while protecting against catastrophic reversals.

**Learn more:**
- [Investopedia — Trailing Stop](https://www.investopedia.com/terms/t/trailingstop.asp)
- [Investopedia — Stop-Loss Orders](https://www.investopedia.com/terms/s/stop-lossorder.asp)

---

## 7. Key Formulas Reference

| Metric | Formula | Notes |
|---|---|---|
| Revenue CAGR | `(Revenue_end/Revenue_start)^(1/n) − 1` | n = number of years |
| Gross Margin | `Gross Profit / Revenue` | |
| Operating Margin | `Operating Income / Revenue` | |
| Net Margin | `Net Income / Revenue` | |
| ROIC | `NOPAT / Invested Capital` | NOPAT = EBIT×(1−tax) |
| DuPont ROE | `Net Margin × Asset Turnover × Equity Multiplier` | |
| Gross Profitability | `Gross Profit / Total Assets` | Novy-Marx (2013) |
| Accruals Ratio | `(Net Income − CFO) / Avg Net Operating Assets` | Sloan (1996) |
| D/E Ratio | `Total Debt / Total Equity` | |
| Interest Coverage | `EBIT / Interest Expense` | |
| Net Debt/EBITDA | `(Total Debt − Cash) / EBITDA` | |
| Altman Z-Score | `1.2X1 + 1.4X2 + 3.3X3 + 0.6X4 + X5` | See §2C |
| FCF | `Operating Cash Flow − Capex` | |
| DCF | `Σ FCF_t/(1+WACC)^t + TV/(1+WACC)^n` | TV = Gordon Growth |
| MOS | `(Fair Value − Price) / Fair Value` | |
| P/E | `Price / EPS` | |
| EV/EBITDA | `Enterprise Value / EBITDA` | EV = Mkt Cap + Debt − Cash |
| Sharpe | `(Ann. Return − Rf) / Ann. StdDev` | |
| Sortino | `(Ann. Return − Rf) / Downside StdDev` | |
| Beta | `Cov(asset, market) / Var(market)` | |
| VaR (95%) | `returns.quantile(0.05)` | 5th percentile of daily returns |
| CVaR (95%) | `mean(returns where returns ≤ VaR)` | |
| Max Drawdown | `min(equity_curve / equity_curve.cummax() − 1)` | |
| Calmar | `Ann. Return / |Max Drawdown|` | |
| Information Ratio | `(Return_stock − Return_ETF) / StdDev(active_return)` | |
| Kelly fraction | `(p×b − q) / b` | p = win rate, b = win/loss ratio |
| RSI | `100 − 100/(1 + Avg_Gain/Avg_Loss)` | 14-period default |
| MACD | `EMA(12) − EMA(26)` | Signal = EMA(9) of MACD |
| ATR | Wilder-smoothed True Range | 14-period default |
| VWAP | `Σ(TypicalPrice × Vol) / Σ(Vol)` | TypicalPrice = (H+L+C)/3 |
| CMF | `Σ(MFM×Vol, 21) / Σ(Vol, 21)` | MFM = ((C−L)−(H−C))/(H−L) |
| ROC(n) | `(Close / Close.shift(n) − 1) × 100` | |
| BB Width | `(Upper − Lower) / SMA20` | Upper/Lower = SMA20 ± 2σ20 |
| Stochastic %K | `(Close − Low_14) / (High_14 − Low_14) × 100` | |

---

## 8. Further Reading

### Foundational Finance Books (accessible to developers)
| Book | Author | Why Read It | Free Resource |
|---|---|---|---|
| *The Intelligent Investor* | Benjamin Graham (1949) | The original value investing text; margin of safety concept | [Summary — Investopedia](https://www.investopedia.com/articles/basics/07/intelligent-investor.asp) |
| *Security Analysis* | Graham & Dodd (1934) | Deep fundamental analysis methodology | [Overview — CFA Institute](https://www.cfainstitute.org/en/research/cfa-digest/2019/q1/security-analysis) |
| *Investment Valuation* | Aswath Damodaran (2012) | Best modern DCF/valuation reference | [Free lecture videos + spreadsheets — NYU Stern](http://pages.stern.nyu.edu/~adamodar/) |
| *Valuation* (McKinsey) | Koller, Goedhart & Wessels (2020) | Industry-standard corporate finance; used by investment banks | [Companion website](https://www.wiley.com/en-us/Valuation%3A+Measuring+and+Managing+the+Value+of+Companies%2C+7th+Edition-p-9781119611868) |
| *Financial Statement Analysis* | Stephen Penman (2013) | DuPont, ROIC, and quality of earnings — developer-friendly structure | [Author page — Columbia Business School](https://www8.gsb.columbia.edu/faculty/spenman/) |

### Technical Analysis Books
| Book | Author | Why Read It | Free Resource |
|---|---|---|---|
| *Technical Analysis of the Financial Markets* | John Murphy (1999) | The complete TA reference; covers every indicator used in this pipeline | [StockCharts Chart School](https://school.stockcharts.com/doku.php?id=start) |
| *Trading for a Living* | Alexander Elder (1993) | Practical introduction to applying TA with risk management | [Book site](https://www.elder.com/) |
| *Trading with Ichimoku Clouds* | Nicolas Péloille (2017) | Best English-language Ichimoku reference | [Investopedia Ichimoku Guide](https://www.investopedia.com/terms/i/ichimoku-cloud.asp) |
| *Encyclopedia of Chart Patterns* | Thomas Bulkowski (2005) | Empirical success rates for every chart pattern | [Bulkowski's free pattern stats](https://thepatternsite.com/) |

### Risk & Portfolio Books
| Book | Author | Why Read It | Free Resource |
|---|---|---|---|
| *Active Portfolio Management* | Grinold & Kahn (1999) | Information Ratio, alpha, and institutional risk framework | [Overview — Investopedia](https://www.investopedia.com/terms/i/informationratio.asp) |
| *Options, Futures and Other Derivatives* | John Hull (2017) | Volatility, VaR, options pricing — the standard derivatives text | [Author resources](http://www.rotman.utoronto.ca/~hull/ofod/) |
| *Practical Portfolio Performance Measurement* | Carl Bacon (2008) | Every risk metric used in phase 5, with derivations | [CFA Institute review](https://www.cfainstitute.org/en/research/cfa-digest/2012/q3/practical-risk-adjusted-performance-measurement) |

### Key Academic Papers (all freely available via Google Scholar)
| Paper | Finding | Link |
|---|---|---|
| Sloan (1996), *Accounting Review* | Accruals anomaly — high accruals predict earnings reversals | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=395580) |
| Jegadeesh & Titman (1993), *Journal of Finance* | Momentum anomaly — 6–12 month winners continue to outperform | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2730412) |
| Novy-Marx (2013), *Journal of Financial Economics* | Gross profitability predicts returns as powerfully as value metrics | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2233698) |
| George & Hwang (2004), *Journal of Finance* | 52-week high proximity predicts momentum continuation | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=570011) |
| Altman (1968), *Journal of Finance* | Z-Score bankruptcy prediction model | [Altman Z-Score — Investopedia](https://www.investopedia.com/terms/a/altman.asp) |
| Asness, Moskowitz & Pedersen (2013), *Journal of Finance* | Value and momentum work better in combination than alone | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2174501) |
| Fama & French (2015), *Journal of Financial Economics* | 5-factor model including profitability and investment factors | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202) |

### Online Learning Platforms
| Resource | What it covers |
|---|---|
| [Investopedia Academy](https://academy.investopedia.com/) | Structured courses: investing basics, technical analysis, financial modelling |
| [FMP Education Hub](https://site.financialmodelingprep.com/educational) | All financial metrics with FMP API context — directly relevant to this codebase |
| [StockCharts Chart School](https://school.stockcharts.com/doku.php?id=start) | Every technical indicator explained with visual examples |
| [CFI (Corporate Finance Institute)](https://corporatefinanceinstitute.com/resources/knowledge/) | Free financial modelling and valuation courses |
| [Damodaran Online (NYU Stern)](http://pages.stern.nyu.edu/~adamodar/) | Free valuation spreadsheets, datasets, and lecture videos — the best free finance resource on the internet |
| [CFA Institute — Free Resources](https://www.cfainstitute.org/en/membership/professional-development/refresher-readings) | CFA-level refresher readings on every finance topic |

---

*Education document version 1.1 | Updated 2026-03-23 | Cross-reference: All phase documents in `Analysis/docs/phases/`*
