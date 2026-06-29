# Positive Volume Index (PVI)

**Source:** <https://www.tradingview.com/support/solutions/43000773006-positive-volume-index-pvi/>  
**Indicator ID:** 43000773006  
**Slug:** `positive-volume-index-pvi`

[← back to index](./README.md)

---

The Positive Volume Index (PVI), invented by Paul L. Dysart Jr. in the 1930s and adapted by Norman G. Fosback in the 1970s, is a trend indicator that accumulates the price change percentages from the bars where volume **increases** while ignoring the changes from bars where volume decreases. 

The logic behind the PVI and its counterpart, the [Negative Volume Index (NVI)](<https://www.tradingview.com/support/solutions/43000773005>), is based on the assumption that most market participants trade during high-volume periods, while a smaller set of more informed investors — sometimes referred to as "smart money" — is more active during low-volume periods. 

Traders often analyze the PVI, alongside a moving average, on market indices to identify short-term trends and momentum based on the price movements that occur as volume increases. 

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593137815/original/siAepNzBp8wpJwAicsM7PhiShjrtu2d8nw.png?1763765794)

#### Calculation

Paul Dysart's original PVI was an indicator of broad market activity. It accumulated net advances in the market only on days where volume increased relative to the previous day. Norman Fosback adapted the concept to apply a Positive Volume Index to any market index with volume data. Instead of using advances and declines, Fosback's version of the PVI accumulates percentage changes in price. The calculation is as follows:

  1. Set the initial value of the PVI. The value defines the scale of the PVI, but it does not affect the indicator's behavior. The most common initial values are 1000, 100, and 1. This indicator uses 1000.
  2. If the volume on the current bar is greater than that of the previous bar, add the current change percentage in close prices to the previous PVI value.
  3. If the volume on the current bar is less than or equal to that of the previous bar, do not add the bar's change percentage to the PVI.



The result is a cumulative series that updates only on higher-volume bars, providing potential insights into how markets behave as overall trading activity rises. Fosback derived trading signals by comparing the PVI to a one-year moving average. The PVI trending above the average suggests upward momentum and the possible onset of a bullish trend, and a value below the average suggests the opposite.

The PVI is primarily intended for analyzing market activity on major market indices, but you can apply this indicator to any chart that has volume data.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593137539/original/72O3xbEZEATN9j75GGOmGAZcyKRMAFZPfg.png?1763765548)

#### EMA length

The length for the smoothing factor of the PVI-based [exponential moving average (EMA)](<https://www.tradingview.com/support/solutions/43000592270/>). The default is 255, which corresponds to approximately one year on a daily equities chart. 

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Pivot Points Standard

NextNext

Power-Law Model

Launch Supercharts

---

[← back to index](./README.md)
