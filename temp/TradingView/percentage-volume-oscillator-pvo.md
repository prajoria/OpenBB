# Percentage Volume Oscillator (PVO)

**Source:** <https://www.tradingview.com/support/solutions/43000591350-percentage-volume-oscillator-pvo/>  
**Indicator ID:** 43000591350  
**Slug:** `percentage-volume-oscillator-pvo`

[← back to index](./README.md)

---

The Percentage Volume Oscillator (PVO) is a momentum indicator for volume. It measures the relative difference between two volume-based moving averages. Similar to the [MACD](<https://www.tradingview.com/support/solutions/43000502344-macd-moving-average-convergence-divergence/>) and [PPO](<https://www.tradingview.com/support/solutions/43000502346/>) indicators, the PVO consists of three components: the main oscillator, a smoothed signal line, and a histogram line that represents the difference between those values. 

The PVO closely resembles the PPO. Both indicators measure the difference between two moving averages as a percentage of the slower moving average, offering a relative scale for comparing momentum values across history or across instruments. However, while the PPO measures the relative momentum of **price** , the PVO measures the relative momentum of **volume**.

Traders often analyze the PVO along with price action and price momentum indicators to identify high- and low-volume movements, and to help confirm breakouts or other signals based on relative volume changes.

#### 

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43595986471/original/0xevQ_8mnS0TLP3_8jBYdyW1ZeTXwIJhlA.png?1765219061)

Calculation

At its core, the Percentage Volume Oscillator uses the same formula as the [PPO](<https://www.tradingview.com/support/solutions/43000502346/>). The only difference in the PVO's formula is that it calculates moving averages of **volume** instead of price values. The calculation is as follows:

> PVO = (Fast Volume MA − Slow Volume MA) / Slow Volume MA × 100

> Signal = Moving average of PVO

> Histogram = PVO − Signal

Where:

  * **Fast Volume MA** is the volume-based moving average with the lowest length
  * **Slow Volume MA** is the volume-based moving average with the highest length



The indicator plots the PVO and signal values as lines, and the histogram values as color-coded columns. It also displays a horizontal zero line to distinguish positive and negative values.

Because the PVO measures the momentum of volume instead of prices, its interpretation differs from that of the PPO or MACD:

  * A PVO value above 0 means that the fast MA of volume is greater than the slow MA, indicating above-average volume or market participation. A PVO value below 0 means the opposite.
  * A histogram value above 0, or the PVO moving above the signal line, suggests that the short-term average volume is increasing. A histogram value below 0, or the PVO moving below the signal line, suggests the opposite.



#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43595986797/original/-U9lBQW88j5r7tklS_uOK_x8ZpNMzG3KlQ.png?1765219176)

#### Fast length

The length value for the fast moving average.

#### Slow length

The length value for the slow moving average.

#### Signal length

The length value for the moving average of the PVO (signal line).

#### Oscillator MA type

Specifies the type for the fast and slow averages in the PVO calculation. Select "EMA" to use two [exponential moving averages](<./exponential-moving-average.md>), or "SMA" to use [simple moving averages](<./simple-moving-average.md>) instead.

#### Signal MA type

Specifies which type of moving average the indicator applies to the PVO to calculate the signal line. Select "EMA" for an exponential moving average, or "SMA" for a simple moving average.

#### Timeframe

Sets the timeframe that the indicator uses for its calculations. The "Wait for timeframe closes" checkbox below determines whether the indicator shows results only when a bar on the specified timeframe closes. See the [Leveraging multi-timeframe analysis](<https://www.tradingview.com/support/solutions/43000591555-leveraging-multi-timeframe-analysis/>) article to learn more.

PreviousPrevious

Percentage Price Oscillator (PPO)

NextNext

Performance

Launch Supercharts

---

[← back to index](./README.md)
