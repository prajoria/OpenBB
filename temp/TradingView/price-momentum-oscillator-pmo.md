# Price Momentum Oscillator (PMO)

**Source:** <https://www.tradingview.com/support/solutions/43000773010-price-momentum-oscillator-pmo/>  
**Indicator ID:** 43000773010  
**Slug:** `price-momentum-oscillator-pmo`

[← back to index](./README.md)

---

The Price Momentum Oscillator (PMO), created by Carl Swenlin, is a momentum indicator that measures the smoothed bar-by-bar [rate of change (ROC)](<./rate-of-change-roc.md>) in an instrument's price. The indicator applies two stages of smoothing to the ROC, and uses an [EMA](<./exponential-moving-average.md>) of the result as a signal line.

The PMO functions similarly to indicators such as the [MACD](<https://www.tradingview.com/support/solutions/43000502344-macd-moving-average-convergence-divergence/>). Traders typically use it to gauge short-term momentum, identify developing trends or mean reversion opportunities, and find divergences or other patterns. However, because the indicator smooths the single-bar ROC instead of calculating the difference between price averages, it is less sensitive to the absolute magnitude of price movements, often resulting in a more consistent scale across the chart's history.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593139585/original/LtnxZuIyuOkzxnVS9xReaylZnZBEAofS6Q.png?1763767289)

#### Calculation

The PMO indicator applies two stages of custom exponential smoothing, with different lengths, to the one-bar ROC of market prices. Then, it computes a signal line using a standard EMA. The steps to calculate the PMO and signal values are as follows:

  1. Calculate the percentage change in prices, representing the one-bar ROC.
  2. Apply an EMA with a custom smoothing factor to the ROC series. Instead of the standard smoothing factor of **2 / (length + 1)** , this EMA uses the factor **2 / length**.
  3. Multiply the smoothed series by 10, then apply a second EMA using the same custom smoothing factor formula to calculate the PMO.
  4. Apply a standard EMA to the PMO to calculate the signal line. 



The indicator plots the smooth PMO and its signal line in a separate pane, along with a horizontal line at zero to distinguish positive and negative momentum readings. The usual interpretation of this indicator is similar to that of the MACD indicator:

  * PMO values above 0 indicate average upward momentum. Values below 0 indicate average downward momentum.
  * The crossings between the PMO and the signal line indicate shorter-term momentum shifts. The PMO crossing over the signal line suggests that momentum is either shifting upward or continuing upward. The PMO crossing under the signal line suggests the opposite.
  * Divergences in the relative movements of the PMO and price might help to identify turning points or shifts in trends. For example, falling peaks in the PMO while the market price is rising might suggest the exhaustion of an uptrend. Likewise, rising dips in the PMO while the market price is falling might suggest the exhaustion of a downtrend.



#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593139695/original/xz9QFaQU5pJ2-QzBEpvEr1X-YY_19w4oHQ.png?1763767405)

#### Source

The series of values for which to calculate the PMO.

#### Length 1

The length for the first stage of exponential smoothing.

#### Length 2

The length for the second stage of exponential smoothing.

#### Signal length

The length for the standard EMA of the PMO (signal line).

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Premium

NextNext

Price target - indicator

Launch Supercharts

---

[← back to index](./README.md)
