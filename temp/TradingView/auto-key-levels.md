# Auto key levels

**Source:** <https://www.tradingview.com/support/solutions/43000783958-auto-key-levels/>  
**Indicator ID:** 43000783958  
**Slug:** `auto-key-levels`

[← back to index](./README.md)

---

#### Definition

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43620915174/original/tK-gHzzTgj1y52yCuhzI1oq9kGkEC4dK8w.png?1777994437)

Auto Key Levels is a specialized technical analysis indicator designed to automatically calculate and display the most significant price levels - Point of Control (POC), Value Area High (VAH), Value Area Low (VAL), and OHLC - across various time periods.

Unlike the classic Volume Profile indicator, which displays volume distribution histograms, Auto Key Levels focuses exclusively on horizontal lines. This allows traders to maintain a "clean" chart while simultaneously tracking the hierarchy of daily, weekly, and monthly levels.

#### Calculation

The indicator uses algorithms identical to the built-in Periodic Volume Profile tool with default parameters. To ensure high accuracy, calculations are performed on a lower timeframe, which is selected automatically based on the current chart period. The calculation and timeframe selection algorithm is described in detail in the [Volume profile](<https://www.tradingview.com/support/solutions/43000502040/>) article.

In cases where the selected period is smaller than the data available on the current chart timeframe, a calculation error will be generated: "Not enough data to build the period 'period_name'." In this instance, it is recommended to disable that specific period or switch to a timeframe with greater data depth.

#### The basics

The indicator is based on volume profile data and price action at key moments within a specific period, calculating the following levels:

  * POC (Point of Control): The price level with the highest traded volume for the selected period.
  * VAH (Value Area High): The upper boundary of the Value Area, where 70% of the total volume for the period is concentrated.
  * VAL (Value Area Low): The lower boundary of the Value Area.
  * OHLC: Classic Open, High, Low, and Close levels for the period.



#### Level types

The indicator divides levels into three categories:

  1. Current: Levels of the current unfinished period. These are dynamic and can move in real-time as new trades are executed.
  2. Previous: Fixed levels of the last fully completed period (e.g., "Previous day POC"). These often act as strong support or resistance zones.
  3. Custom: Levels calculated over an arbitrary timeframe or anchored to specific events (earnings reports, dividends, splits).



#### Level labels

For quick identification, each level is labeled with an abbreviation:

  * dPOC / dVAL / dVAH / dO / dH / dL / dC - current daily levels.
  * wPOC / wVAL / wVAH / wO / wH / wL / wC - current weekly levels.
  * mPOC / mVAL / mVAH / mO / mH / mL / mC - current monthly levels.
  * pdPOC / pwPOC / pmPOC - levels of the previous day, week, or month, respectively.
  * Custom POC, Custom VAL, Custom VAH - levels of the custom-configured period.



Levels have a preset visual hierarchy: monthly levels are drawn on top of weekly levels, and weekly levels on top of daily levels. This ensures visibility even when prices overlap exactly.

#### What to look for

#### Mean reversion

The pVAH (previous Value Area High) and pVAL (previous Value Area Low) boundaries act as strong dynamic support and resistance levels.

  * If the price opens inside the previous day's Value Area (between pVAH and pVAL), it often seeks to test the boundaries of the previous period.
  * A false breakout of pVAH or pVAL followed by a return inside the zone provides a signal for a move toward the opposite boundary or the POC.



#### Support/Resistance POC

The Point of Control (POC) represents the "fair price" level. After a strong impulse move, the price often corrects back to the previous period's POC (pPOC) to fill liquidity.

#### OHLC confirmation

Open and High/Low levels complement volume analysis. If the price quickly moves above dOpen while staying above pVAH, it is a sign of a strong trending day (imbalance). The strongest signals occur when volume levels coincide with OHLC. For example, if pPOC aligns with yesterday's pdHigh, that level becomes critical for sellers to defend.

#### Developing levels

If the current day's Value Area (VAH/VAL) is forming higher or lower than yesterday's dVAH/dVAL (without crossing or only partially overlapping), it confirms a steady bullish or bearish trend.

#### Alerts

You can set alerts for POC, VAL, and VAH of any period and type: Current, Previous, or Custom.

Alerts on indicator values support all alert operator types described[ here](<https://www.tradingview.com/support/solutions/43000520149/>).

To set an alert:

  1. Ensure the indicator is added to the chart.
  2. Enable the specific levels you want to track in the indicator settings.
  3. Open the "Create Alert" dialog and select Auto Key Levels as the condition.



The process of creating an alert is described in more detail[ here](<https://www.tradingview.com/support/solutions/43000481368/>).

> **Note:** The level for which the alert is being set must be enabled in the indicator inputs; otherwise, the level values will not be calculated and the alert will never trigger. Disabled levels will still appear in the "Create Alert" dialog, but they will not function.

#### Summary

The Auto Key Levels indicator is an automation tool for traders who utilize volume analysis and market structure in their strategies. By combining calculations of POC, Value Areas (VA), and OHLC levels across multiple time intervals, the indicator simplifies market context visualization. Its primary goal is to provide objective data on volume distribution and price extremes while keeping the workspace clean and informative.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43620912982/original/JX_JydCcvvfDHnrJ1Tsf4LVhxp1O_0jkqw.png?1777993901)

The settings are divided into logical groups for easy management of the visual hierarchy.

#### Current

#### Day / Week / Month

Enables the display of levels for the current corresponding period. Enabling a period unlocks checkboxes for specific levels (POC, VAL, VAH, OHLC) and allows you to set the display color for that entire group.

#### Previous

#### Prev Day / Prev Week / Prev Month

Enables the display of levels for the previous completed period. Similar to the Current group, enabling a period unlocks the selection of POC, VAL, VAH, and OHLC levels, as well as color customization.

#### Custom

#### Custom

Enables the display of levels for a user-defined period specified in the Anchor input. Which levels will be displayed is determined by further checkboxes that are unlocked when the period checkbox is enabled. POC, VAL, VAH, and OHLC levels are available. It also allows setting the line display color for all levels of this period. When the Custom checkbox is enabled, the Anchor input is also unlocked.

#### Anchor

Allows you to set a specific anchor for calculation:

  * Custom - calculation for the last days/weeks/months.
  * Earnings - calculation of levels since the last report for the instrument.
  * Split - calculation of levels since the last split or consolidation event.
  * Dividends - calculation of levels since the last dividend payment event.



#### Common

#### Levels start from

Determines where the level lines are drawn - either from the start of the period or from the current bar to the right.

PreviousPrevious

Auto Fib Retracement

NextNext

Auto Pitchfork

Launch Supercharts

---

[← back to index](./README.md)
