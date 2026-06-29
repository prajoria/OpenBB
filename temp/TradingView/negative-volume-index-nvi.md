# Negative Volume Index (NVI)

**Source:** <https://www.tradingview.com/support/solutions/43000773005-negative-volume-index-nvi/>  
**Indicator ID:** 43000773005  
**Slug:** `negative-volume-index-nvi`

[← back to index](./README.md)

---

The Negative Volume Index (NVI), invented by Paul L. Dysart Jr. in the 1930s and adapted by Norman G. Fosback in the 1970s, is a trend indicator that accumulates the price change percentages from only the bars where volume **decreases** while ignoring the changes from bars where volume increases. 

The logic behind the NVI and its counterpart, the [Positive Volume Index (PVI)](<https://www.tradingview.com/support/solutions/43000773006/>), is based on the assumption that most market participants trade during high-volume periods, while a smaller set of more informed investors — sometimes referred to as "smart money" — is more active during low-volume periods. 

Traders often analyze the NVI, alongside a moving average, on market indices to identify underlying trends based on the price movements that occur as volume decreases. 

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593136328/original/tMVlJfQbh15hg0cCBXK_Da_O0s1dHRoiSQ.png?1763764731)

#### Calculation

Paul Dysart's original NVI was an indicator of broad market activity. It accumulated net advances in the market on days where volume decreased relative to the previous day. Norman Fosback adapted the concept to apply a Negative Volume Index to any market index with volume data. Instead of using advances and declines, Fosback's version of the NVI accumulates percentage changes in price. The calculation is as follows:

  1. Set the initial value of the NVI. The value defines the scale of the NVI, but it does not affect the indicator's behavior. The most common initial values are 1000, 100, and 1. This indicator uses 1000.
  2. If the volume on the current bar is less than that of the previous bar, add the current change percentage in close prices to the previous NVI value.
  3. If the volume on the current bar is greater than or equal to that of the previous bar, do not add the bar's change percentage to the NVI.



The result is a cumulative series that updates only on lower-volume bars, providing potential insights into how markets behave as trading activity decreases. Fosback derived trading signals by comparing the NVI to a one-year moving average. The NVI trending above the average suggests a possible underlying bullish trend in the market, and a value below the average suggests the opposite.

The NVI is primarily intended for analyzing market activity on major market indices, but you can apply this indicator to any chart that has volume data.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593136469/original/Z19UjZ8xGe6BNwPyKctdG0UyHQqzFp8hlA.png?1763764828)

#### EMA length

The length for the smoothing factor of the NVI-based [exponential moving average (EMA)](<https://www.tradingview.com/support/solutions/43000592270/>). The default is 255, which corresponds to approximately one year on a daily equities chart. 

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Multi-Time Period Charts indicator

NextNext

Net Volume

Launch Supercharts

---

[← back to index](./README.md)
