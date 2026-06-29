# Pring's Special K

**Source:** <https://www.tradingview.com/support/solutions/43000773011-pring-s-special-k/>  
**Indicator ID:** 43000773011  
**Slug:** `pring-s-special-k`

[← back to index](./README.md)

---

The Special K, invented by Martin J. Pring, is a trend and momentum indicator that combines average rates of change over multiple lengths into a single oscillator, providing a filtered, composite view of price cycles over the short, medium, and long term. Building on the concepts of the [Know Sure Thing indicator (KST)](<./know-sure-thing-kst.md>) and years of market observations, Pring designed the Special K to identify primary trends and reversals, and to aid in timing short-term, pro-trend trades. 

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593142213/original/zoAnDNrSrIgXIa7my-C7uKJmEYoK-Z8F8g.png?1763769495)

#### Calculation

The Special K is a weighted sum of [simple moving averages (SMAs)](<./simple-moving-average.md>) of the market price's [rate of change (ROC)](<./rate-of-change-roc.md>) over multiple lookback lengths. Pring selected the weight and the lookback lengths for each average ROC based on his observations of cycles and trends. The sum combines the following values:

  * 10-bar SMA of the 10-bar ROC
  * 10-bar SMA of the 15-bar ROC × 2
  * 10-bar SMA of the 20-bar ROC × 3
  * 15-bar SMA of the 30-bar ROC × 4
  * 50-bar SMA of the 40-bar ROC
  * 65-bar SMA of the 65-bar ROC × 2
  * 75-bar SMA of the 75-bar ROC × 3
  * 100-bar SMA of the 100-bar ROC × 4
  * 130-bar SMA of the 195-bar ROC
  * 130-bar SMA of the 265-bar ROC × 2
  * 130-bar SMA of the 390-bar ROC × 3
  * 195-bar SMA of the 530-bar ROC × 4



The result is a composite oscillator representing a weighted combination of significant market cycles with reduced noise. The indicator also includes a twice-smoothed signal line for detecting reversals. By default, it calculates the 100-bar SMA of the Special K, then applies a second 100-bar SMA to the result. You can customize the signal line's smoothing lengths from the "Inputs" tab of the indicator's settings.

> **!Note:** Because the Special K calculates up to the 195-bar SMA of the 530-bar ROC, it requires a chart with at least **725 bars** of data. The indicator displays an error if the chart's history contains fewer than 725 bars.

The main intention of the Special K is to detect primary trends and reversal points:

  * Rising peaks and dips in the Special K suggest that the primary trend is bullish. Falling peaks and dips suggest the opposite.
  * A positive Special K indicates long-term bullish strength, and a negative value indicates long-term bearish strength.
  * Crossings between the Special K and the signal line can indicate the reversal or continuation of a primary trend. The Special K crossing over the signal line suggests that the trend is either shifting upward or continuing upward. The Special K crossing under the signal line suggests the opposite.
  * Pring also recommends drawing trendlines on the Special K to find reversal points. The Special K breaching a long-term trendline might indicate a shift in the primary trend from bullish to bearish or vice versa.



Traders also use the indicator in conjunction with the KST, moving average crosses, or other momentum indicators to filter short-term signals based on the trends suggested by the Special K.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593142522/original/dhELAtrbhz5N4sUS1XxIyakd-FvoCkCLqQ.png?1763769636)

#### Source

The series of values for which to calculate the Special K.

#### Signal length 1

The number of bars for the first SMA in the signal line calculation.

#### Signal length 2

The number of bars for the second SMA in the signal line calculation.

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Price Volume Trend (PVT)

NextNext

Rank Correlation Index (RCI)

Launch Supercharts

---

[← back to index](./README.md)
