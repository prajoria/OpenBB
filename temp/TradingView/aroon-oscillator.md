# Aroon Oscillator

**Source:** <https://www.tradingview.com/support/solutions/43000773004-aroon-oscillator/>  
**Indicator ID:** 43000773004  
**Slug:** `aroon-oscillator`

[← back to index](./README.md)

---

The Aroon Oscillator, created by Tushar Chande in 1995, is a trend indicator that measures the recency of the highest highs versus the lowest lows in market prices over a lookback period. It calculates the difference between the Aroon Up and Aroon Down values from the [Aroon](<./aroon.md>) indicator to produce a single, bounded metric that oscillates between -100 and +100.

Traders often use the Aroon Oscillator to assess the strength of short-term trends and to identify potential trend reversals or turning points in the market. 

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593134217/original/vsIQBPJlQ3Mi2iUQl2zZ4hvX9XFwwz2qYA.png?1763763484)

#### Calculation

The Aroon Oscillator's calculation relies on the values of Aroon Up and Aroon Down, which respectively measure the recency of the highest high and lowest low prices for a given lookback period. Both values range between 0 and 100, where:

  * **Aroon Up** is 100 on bars where the market price reaches the highest high for the current period. The value decreases for each successive bar whose high price is less than the highest value.
  * **Aroon Down** is 100 on bars where the market price reaches the lowest low for the current period. The value decreases for each successive bar whose low price is greater than the lowest value.



The indicator transforms these two readings into a single oscillator by calculating their difference:

> Aroon Oscillator = Aroon Up - Aroon Down

The resulting oscillator ranges from -100 to +100, where:

  * A positive value means that Aroon Up is greater than Aroon Down, indicating that the market price reached the highest high more recently than the lowest low. If the value is +100, Aroon Up is 100 and Aroon Down is 0, meaning the price reached the highest high on the current bar without reaching the lowest low on any bar in the period.
  * A negative value means that Aroon Up is less than Aroon Down, indicating that the market price reached the lowest low more recently than the highest high. If the value is -100, Aroon Up is 0 and Aroon Down is 100, meaning the price reached the lowest low on the current bar without reaching the highest high on any bar in the period.
  * A value near 0 means that Aroon Up and Aroon Down are roughly equal. It indicates that the price recently moved from the highest high to the lowest low, or vice versa, across a small number of bars relative to the length of the lookback period.



This indicator plots the oscillator as a color-coded line with a background fill, and it displays horizontal levels at -90, 0, and +90 by default. You can customize the colors and the values of the levels from the "Style" tab of the indicator's settings.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593133277/original/3DiHBaQ1Ear-2nBpT2XKb3S6BCuP-2asJQ.png?1763762970)

#### Length

The number of bars to analyze for the Aroon Up and Aroon Down calculation. The length for the highest high and lowest low is one greater than this value.

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Aroon

NextNext

Auto Fib Extension

Launch Supercharts

---

[← back to index](./README.md)
