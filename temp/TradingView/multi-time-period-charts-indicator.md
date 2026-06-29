# Multi-Time Period Charts indicator

**Source:** <https://www.tradingview.com/support/solutions/43000502591-multi-time-period-charts-indicator/>  
**Indicator ID:** 43000502591  
**Slug:** `multi-time-period-charts-indicator`

[← back to index](./README.md)

---

The Multi-Time Period Charts (MTPC) indicator displays data from higher-timeframe (HTF) bars directly on the chart. It draws color-coded boxes representing HTF ranges based on standard prices or [Heikin Ashi](<https://www.tradingview.com/support/solutions/43000619436-understanding-heikin-ashi-charts/>) values, enabling multi-timeframe bar analysis without the need to change the chart's timeframe or type.

  


#### Calculation

The indicator calculates bar ranges for an automatically selected timeframe or a specified timeframe, depending on the "Auto-timeframe" input. The table below shows which higher timeframe the indicator selects, based on the chart timeframe, when "Auto-timeframe" is enabled:

**Chart timeframe**| **Higher timeframe**  
---|---  
Seconds| 2 hours  
Lower than 1 day and not a seconds-based timeframe| 1 day  
Higher than or equal to 1 day and lower than 1 week| 1 week  
Higher than or equal to 1 week and lower than 1 month| 1 month  
Higher than or equal to 1 month and lower than 3 months| 3 months  
Higher than or equal to 3 months| 12 months  
  
Using standard or Heikin Ashi data for the selected higher timeframe, the indicator draws boxes showing price ranges for successive HTF bars. Each box begins on the chart bar where the HTF period opens, and ends on the bar where the period closes. The ranges that the boxes show for each HTF bar depend on the selected "Calculation" setting:

**Calculation**| **Description**  
---|---  
High/Low Range| Box top = High price  
Box bottom = Low price  
Open/Close Range| Box top = Maximum of the open and close prices  
Box bottom = Minimum of the open and close prices  
OHLC| Two boxes per HTF bar: one for the high-low range and one for the open-close range  
True Range| Box top: Maximum of the current high and the previous HTF close  
Box bottom: Minimum of the current low and the previous HTF close  
  
The border and fill colors of each box depend on the standard or Heikin Ashi open and close prices of the HTF bar. By default, the boxes show:

  * Red colors if the HTF bar's close price is less than its open price
  * Teal colors if the HTF bar's close price is greater than or equal to its open price



> **!Note:** This indicator displays up to ~500 boxes covering the most recent HTF bars. You can view the boxes for earlier bars by using [Bar Replay](<https://www.tradingview.com/support/solutions/43000712747/>) mode.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43590613221/original/i4DhdklH49ZKL739uw2_n9Ipb3RC1a6e_A.png?1762558694)

#### Auto-timeframe

If selected, the indicator automatically chooses the higher timeframe of the calculation based on the timeframe of the current chart, using the logic described in the first table from the previous section. If not selected, the indicator uses the timeframe specified by the "Timeframe" input instead.

#### Timeframe

The higher timeframe that the indicator uses when "Auto-timeframe" is not selected. This input provides direct control over the calculation timeframe for cases where the automatic selection does not fit your needs.

#### Calculation

Determines the ranges that the drawn boxes represent. The second table in the main "Calculation" section above describes each of the possible options and how they work.

#### Display Heikin Ashi values

If selected, the indicator uses Heikin Ashi values from a higher timeframe for the box calculations. Otherwise, it uses standard price values.

#### Use daily-based values

If selected, the indicator directly requests data for daily and higher timeframes. Otherwise, the indicator calculates the HTF data using the bars on the chart's timeframe. The two behaviors can produce slightly different results for some symbols, such as equities, where additional information from intraday bars, such as data from extended trading hours (ETH), might not be included in the higher-timeframe request.

#### Border and fill colors

These inputs specify the border and fill colors of the drawn boxes for "up" bars (the bars where close ≥ open) and "down" bars (the bars where close < open) separately.

PreviousPrevious

MovingAvg2Line Cross

NextNext

Negative Volume Index (NVI)

Launch Supercharts

---

[← back to index](./README.md)
