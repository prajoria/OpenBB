# Design Spec - S&P 500 Top-50 Intraday Drift Backtest

- **Status:** Approved for implementation
- **Issue:** #1986 (test top-50 S&P intraday drift theory)
- **Target branch:** `feat/top50-intraday-gh-1986`

## Goal

Test whether the current top 50 S&P 500 constituents by index weight have a
lower price at 9:00 AM Pacific than at 1:00 PM Pacific over the requested
window of available intraday data, and provide a reusable strategy script.

**Provider constraint (discovered during review):** Yahoo Finance retains only
~60 calendar days of 30-minute intraday bars. A six-month intraday window is
therefore **not obtainable** from this source. The script must fail loudly
rather than silently reporting a two-month sample as a six-month answer; see
"Window Completeness" below.

## Definitions

- "Top 50" means the first 50 holdings in the current S&P 500 weight table.
  This makes the study reproducible but introduces current-constituent and
  survivorship bias, which the output must disclose.
- Pacific times use the `America/Los_Angeles` timezone, so daylight-saving
  changes are handled correctly.
- For US equities, 9:00 AM Pacific maps to the **open of the 12:00 ET
  30-minute bar** (the 12:00-12:30 ET interval). The 1:00 PM Pacific
  market-close price maps to the **close of the 15:30 ET 30-minute bar** (the
  15:30-16:00 ET interval, whose close is the 16:00 ET session close).
- **Bar alignment is not top-of-hour.** Yahoo Finance anchors intraday bars to
  the 09:30 ET regular-session open, so the 60-minute grid is
  `09:30, 10:30, 11:30, 12:30, 13:30, 14:30, 15:30` — **there is no 12:00
  hourly bar**. Matching on hour alone (`hour == 12`) selects the *12:30* ET
  bar, i.e. 09:30 PT, which is 30 minutes late and answers a different
  question. The 30-minute grid
  (`09:30, 10:00, ..., 12:00, ..., 15:30`) is the coarsest interval that
  contains a true 12:00 ET bar, so `interval="30m"` is mandatory and entry/exit
  selection must match **hour *and* minute** exactly.
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
2. A batched Yahoo Finance **30-minute** price loader for the requested
   interval. Because the provider rejects any request whose *start* falls
   outside its ~60-day intraday retention (even when part of the range is
   inside), requests are split into **end-anchored** chunks of at most 59 days
   walking backwards from the requested end, stopping at the first empty chunk
   once data has been collected.
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

- Use adjusted 30-minute OHLC data so splits do not create false returns.
- Request data in batches and preserve per-symbol failures in a missing-symbol
  list rather than silently treating missing observations as losses.
- Fail with a clear message if the constituent source cannot supply 50 symbols,
  no 30-minute bars are returned, or no complete stock-days remain.
- Exclude days missing either required bar and report observed versus expected
  stock-day coverage.
- **Drop currently-forming exit intervals.** A session is only usable when its
  exit interval has *ended* (15:30 ET bar ends 16:00 ET). The filter takes an
  injected timezone-aware `now`, so it stays pure and testable; live callers
  get the current New York time by default.
- Use the latest timestamp actually returned by the provider as the study end
  date; do not claim coverage through a future or unavailable session.

## Window Completeness

- The script computes the requested window from `--months` and compares it with
  the earliest session actually returned.
- If the actual start materially postdates the requested start (tolerance 7
  calendar days, to absorb weekends/holidays), the run **fails loudly** with an
  `INCOMPLETE WINDOW:` error naming both dates, the ~60-day retention limit,
  and the opt-in flag.
- `--allow-partial-window` permits a best-effort run. The report then leads with
  `*** PARTIAL WINDOW -- BEST-EFFORT RESULT, NOT A SIX-MONTH ANSWER ***`, prints
  both the requested and the actual window, and tags every headline percentage
  with `(PARTIAL WINDOW)`. Such a run must never be quoted as a six-month
  result.

## Validation

Unit tests will use realistic 09:30-aligned 30-minute multi-index frames and
verify:

- timezone-aware entry/exit extraction at exactly 12:00 and 15:30 ET;
- **reverse-locks** that the 12:30 ET bar is *never* selected as the entry and
  that a 60-minute (09:30-aligned) grid yields **zero** observations;
- daylight-saving-safe local-time matching;
- currently-forming exit intervals are dropped against an injected `now`;
- missing-bar exclusion and coverage accounting;
- strict win classification and equal-weight basket aggregation;
- the download layer requests `interval="30m"` and stops at retention;
- window-completeness failure by default and `--allow-partial-window` labelling;
- CLI/report behavior without network access.

After unit tests pass, run the script against live public data and record the
**actual available window** and its result in the issue/hand-off summary. Given
the ~60-day retention, that record must be labelled a PARTIAL WINDOW result and
must not be presented as a six-month answer. The result is descriptive, before
transaction costs, and is not investment advice.
