# Design Spec - S&P 500 Top-50 Intraday Drift Backtest

- **Status:** Approved for implementation
- **Issue:** #1986 (test top-50 S&P intraday drift theory)
- **Target branch:** `feat/top50-intraday-gh-1986`

## Goal

Test whether the current top 50 S&P 500 constituents by index weight have a
lower price at 9:00 AM Pacific than at 1:00 PM Pacific over the latest six
months of available intraday data, and provide a reusable strategy script.

## Definitions

- "Top 50" means the first 50 holdings in the current S&P 500 weight table.
  This makes the study reproducible but introduces current-constituent and
  survivorship bias, which the output must disclose.
- Pacific times use the `America/Los_Angeles` timezone, so daylight-saving
  changes are handled correctly.
- For US equities, 9:00 AM Pacific maps to the open of the 12:00 PM New York
  hourly bar. The 1:00 PM Pacific market-close price maps to the close of the
  3:00 PM New York hourly bar.
- A stock-day is accurate when the exit price is strictly greater than the
  entry price. Ties are not wins.
- The requested headline percentage is the number of winning stock-days
  divided by all valid stock-days. The report also includes the percentage of
  sessions where the equal-weight top-50 basket return is positive.

## Architecture

Add a standalone example script under
`openbb_platform/extensions/backtest/examples/`. It will contain:

1. A constituent loader that reads the public S&P 500 weight table and returns
   the first 50 symbols.
2. A batched Yahoo Finance hourly-price loader for the latest six-month
   interval. The provider is appropriate for a quick public-data study and
   supports the required lookback.
3. Pure transformation functions that normalize timestamps to New York time,
   extract entry and exit prices, and reject incomplete stock-days.
4. Pure summary functions that calculate stock-day win rate, basket-day win
   rate, mean/median return, cumulative equal-weight strategy return, sample
   size, and coverage.
5. A CLI entry point that prints a concise report and can optionally write
   stock-day observations to CSV.

The example is research code rather than a registered daily strategy because
the existing strategy engine consumes session-level bars and cannot represent
two executions inside one session without fabricating timestamps.

## Data and Error Handling

- Use adjusted hourly OHLC data so splits do not create false returns.
- Request data in batches and preserve per-symbol failures in a missing-symbol
  list rather than silently treating missing observations as losses.
- Fail with a clear message if the constituent source cannot supply 50 symbols,
  no hourly bars are returned, or no complete stock-days remain.
- Exclude days missing either required bar and report observed versus expected
  stock-day coverage.
- Use the latest timestamp actually returned by the provider as the study end
  date; do not claim coverage through a future or unavailable session.

## Validation

Unit tests will use realistic multi-index hourly frames and verify:

- timezone-aware entry/exit extraction;
- daylight-saving-safe local-time matching;
- missing-bar exclusion and coverage accounting;
- strict win classification and equal-weight basket aggregation;
- CLI/report behavior without network access.

After unit tests pass, run the script against live public data and record the
actual six-month result in the issue/hand-off summary. The result is
descriptive, before transaction costs, and is not investment advice.

