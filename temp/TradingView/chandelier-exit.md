# Chandelier Exit

**Source:** <https://www.tradingview.com/support/solutions/43000773013-chandelier-exit/>  
**Indicator ID:** 43000773013  
**Slug:** `chandelier-exit`

[← back to index](./README.md)

---

The Chandelier Exit, created by Charles Le Beau and popularized by Alexander Elder, is a volatility-based indicator that identifies stop-loss exit points based on local price extremes and [Average True Range (ATR)](<./average-true-range-atr.md>). The indicator's purpose is to help traders stay in a trend-following trade until the potential onset of a significant trend reversal.

Traders typically use Chandelier Exit levels as guides for stop-loss placement to aid in avoiding early trade exits, and as trend filters for signals from other indicators.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593144915/original/IIP0CMIgDnh75lQk3AFrxxVawjaaY051uA.png?1763771753)

#### Calculation

The Chandelier Exit indicator calculates two stop levels, one for long trades and the other for short trades, by finding the highest and lowest prices over a given lookback period, then adding and subtracting multiples of ATR. The formulas to calculate the exit levels are as follows:

> Long Exit = Highest Price − ATR × Multiplier

> Short Exit = Lowest Price + ATR × Multiplier

Where:

  * **Highest Price** and **Lowest Price** are the highest and lowest prices over the specified lookback period
  * **ATR** is the Average True Range with a given length
  * **Multiplier** is a scaling factor that affects the distance at which the stop levels trail behind the highest and lowest prices



The resulting levels trail behind the market price by a variable amount, expanding or contracting the trailing distance in response to changes in volatility or local price extremes.

The long exit value (blue line) increases when either of the following conditions occurs:

  * The highest price increases by a greater amount than the increase in ATR
  * The ATR decreases by a greater amount than the decrease in the highest price



Likewise, the short exit value (orange line) decreases when either of these conditions occurs:

  * The lowest price decreases by a greater amount than the increase in ATR
  * The ATR decreases by a greater amount than the increase in the lowest price



The objective of the Chandelier Exit indicator is to identify potential exit points based on significant price reversals after an established trend:

  * The market price crossing below the long exit level might suggest the end of an uptrend, signaling a possible exit point for a long position
  * The price crossing above the short exit level might suggest the end of a downtrend, signaling a possible exit point for a short position



Although the indicator's intended purpose is to identify exit points, some traders also use Chandelier Exit levels to help detect trends for creating or filtering trading signals. The market price crossing or persisting above the levels might suggest confirmation of a strong uptrend, and vice versa for a downtrend.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43593145035/original/DontH-vnasHOzN-3lDdTEgibWn6hXLhYmw.png?1763771852)

#### Length

The number of bars back to search to determine the highest high for the long exit level and the lowest low for the short exit level.

#### ATR length

The length for the smoothing factor of the Average True Range for both exit levels. A lower value provides more responsiveness to rapid fluctuations, while a higher value increases smoothing for longer-term volatility.

#### ATR multiplier

The ATR scaling factor for both exit levels. It affects the distance at which the levels trail behind the highest and lowest prices. A lower value causes the levels to follow the high and low more closely. A higher value increases the distance from the price extremes to the stop levels.

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Chande Momentum Oscillator (CMO)

NextNext

Chop Zone

Launch Supercharts

---

[← back to index](./README.md)
