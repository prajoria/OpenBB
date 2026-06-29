# Ulcer Index

**Source:** <https://www.tradingview.com/support/solutions/43000773115-ulcer-index/>  
**Indicator ID:** 43000773115  
**Slug:** `ulcer-index`

[← back to index](./README.md)

---

The Ulcer Index, devised by Peter Martin in 1987 and published by Peter Martin and Byron McCann in 1989, is a volatility indicator that estimates **downside risk**. It gauges the depth and duration of relative price declines from previous highs over a defined lookback period. The indicator's name stems from the idea that price drops cause stress for most traders, stress being associated with stomach ulcers.

Unlike volatility measures such as [standard deviation](<https://en.wikipedia.org/wiki/Standard_deviation>), which capture both upside and downside volatility (risk), the Ulcer Index isolates **drawdowns** to provide an estimate of downside volatility for evaluating long positions. Traders often use the Ulcer Index to analyze the downside risk of an instrument and compare risk levels across instruments.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593519265/original/RLxcLbGr8wfDVFj3BkvRmLXMqrbxUQgxLw.png?1764033040)

#### Calculation

The Ulcer Index measures the **root mean square** of drawdowns in price from the highest value over a selected lookback period. The calculation is as follows:

> Highest Price = Highest(Price, Length)

> DD = ((Price − Highest Price) / Highest Price) × 100

> Mean Square DD = Sum(DD × DD, Length) / Length

> Ulcer Index = √(Mean Square DD)

Where:

  * **Length** is the number of bars in the period
  * **Highest Price** is the highest price value in the period
  * **DD** is the percentage drawdown from the highest value on each bar
  * **Mean Square DD** is the average of squared drawdowns over the period
  * **Ulcer Index** is the square root of the average squared drawdown



The resulting index provides a direct estimate of downside volatility over a lookback period:

  * Lower values indicate relatively stable or increasing prices with minimal drawdowns across the period
  * Higher values indicate larger, more sustained price declines over the period



The indicator's value scales with the depth and persistence of drawdowns across the lookback period, with increasing emphasis on larger and more prolonged price drops.

In addition to gauging the potential downside risk of an instrument, and comparing potential risks across multiple instruments, Peter Martin suggests substituting standard deviation with the Ulcer Index in other risk-related metrics.

For example, the Ulcer Performance Index (UPI), also known as the Martin Ratio, is an alternative to the [Sharpe Ratio](<https://www.tradingview.com/support/solutions/43000756107/>) that measures risk-adjusted performance by dividing the average excess return by the Ulcer Index rather than standard deviation. 

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593519470/original/lp_VXHA-V4z-7kHSQOn3lvnYKbSHW1BGMg.png?1764033155)

#### Source

The series of values for which to calculate the Ulcer Index.

#### Length

The number of bars in the lookback period.

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

True Strength Index

NextNext

Ultimate Oscillator (UO)

Launch Supercharts

---

[← back to index](./README.md)
