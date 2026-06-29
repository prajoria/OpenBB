# Zig Zag

**Source:** <https://www.tradingview.com/support/solutions/43000591664-zig-zag/>  
**Indicator ID:** 43000591664  
**Slug:** `zig-zag`

[← back to index](./README.md)

---

The Zig Zag indicator is a charting tool that highlights significant price swings and filters out smaller price fluctuations. It analyzes [high and low pivot points](<https://www.tradingview.com/support/solutions/43000589195/>), drawing straight lines to connect the points at the tops and bottoms of swings that meet or exceed a specified percentage threshold. 

Traders often use the Zig Zag indicator to identify broad price trends and reversals, locate potential support and resistance levels, and analyze patterns such as harmonic formations and Elliott waves. 

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43627034654/original/jx8Nrg-VjlJY3sbTZJWvIcG3A-p5uLlyfg.png?1781020692)

#### Calculation

The Zig Zag indicator compares pivot points in a price series to identify price swings. In this context, a pivot point is a bar's high or low price that is the most extreme over a specified number of previous and subsequent bars:

  * A bar's high is a confirmed **pivot high** if the price is greater than the highest price over the required number of bars before that bar, and greater than or equal to the highest price over the same number of bars after the bar.
  * A bar's low is a confirmed **pivot low** if the price is less than the lowest price over the required number of bars before that bar, and less than or equal to the lowest price over the same number of bars after that bar. 



The "Pivot legs" input defines the **total** number of bars required to confirm a pivot point. The indicator divides the value by two, rounding down if necessary, to specify the required left and right bars. For example, if the value is 10, a bar's high represents a confirmed pivot high only if the price is greater than the highest price over the latest five bars to the left and greater than or equal to the highest high across the next five bars to the right.

#### Constructing the Zig Zag

The Zig Zag indicator draws straight, solid lines connecting only the confirmed pivot points at the alternating tops and bottoms of significant price swings. A swing is considered significant if the reversal percentage meets or exceeds the threshold defined by the "Price deviation for reversals (%)" input. 

The first point saved in the Zig Zag is the earliest confirmed pivot high or pivot low. From that point onward, the indicator compares successive pivot points to its last saved point to identify new reversal points and update its display:

  * If a new pivot point is in the **opposite** direction from the last saved point, and the reversal distance from the previous point to the new point is greater than or equal to the required percentage, the indicator draws a new line connecting the two points. For example, if the last point is a pivot high and the percentage threshold is 5%, the indicator draws a new solid line after confirming a pivot low whose price is at least 5% below the last point's price.
  * If a new pivot point is in the **same** direction as the last saved point and has a more extreme price, the indicator invalidates the last point and anchors the latest line to the new point. For example, if the last displayed point is a pivot high, and a new pivot high occurs at any higher price, the new pivot high becomes the latest line's second point, and the previous one is no longer valid. 
  * If a new pivot point occurs and neither of the above conditions applies, the indicator **ignores** that point and does not update its confirmed structure. 



#### Projected pivots

This indicator can optionally display **projected pivots** when calculating on realtime bars. If the "Calculate projected pivots" input is selected, the indicator searches the bars after the last valid point in the Zig Zag's structure to find and display the next potential, but **unconfirmed** pivot that the Zig Zag can use. This behavior allows the Zig Zag to actively update its structure in response to the latest price updates rather than strictly waiting for the confirmation of a new pivot point.

On each new bar where a confirmed pivot point is not available, the indicator performs the following steps to calculate pivot projections:

  1. It compares the Zig Zag's latest point to the highs or lows of the bars after that point to confirm that the point remains valid. If the market reaches a more extreme price without first reversing by the required percentage, the indicator removes the latest point from the Zig Zag, then uses the Zig Zag's previous point as the latest valid point. Otherwise, it preserves the last saved point. 
  2. It searches each bar after the latest valid point in the Zig Zag for an unconfirmed pivot at the top or bottom of a sufficient price reversal. An unconfirmed pivot is a bar's high or low that is more extreme than the prices over the required number of bars to the left, but not yet confirmed by the required number of bars to the right. If the last valid point is a pivot high, the indicator searches for an unconfirmed pivot low. If the last point is a pivot low, it searches for an unconfirmed pivot high. 
  3. If an unconfirmed pivot is found and meets the required reversal percentage, the indicator draws a temporary **dashed** line connecting the Zig Zag's latest point to that pivot. Otherwise, it removes any previous projection line and does not display a new one. 



If the "Calculate projected pivots" setting is not enabled, the indicator does not search for projected pivots or display a dashed line. It draws a new solid line or updates its existing lines only after a new, confirmed pivot point becomes available. 

#### Information labels

The Zig Zag indicator can optionally display labels with additional information for each saved pivot point, and for the current projected pivot if the "Calculate projected pivots" setting is enabled. If at least one of the "Display" checkboxes is selected, the indicator displays green labels above the Zig Zag's pivot highs and red labels below the pivot lows. 

Each displayed label contains one or more of the following pieces of information, depending on the selected settings:

  * **Reversal price:** The price at the pivot point.
  * **Cumulative volume:** The cumulative sum of volume from the Zig Zag's previous point to the current point. 
  * **Reversal price change:** The distance from the previous pivot point to the current pivot point, expressed as a price difference or a percentage of the previous pivot's price. 



#### Limitations

The Zig Zag indicator has a few distinct limitations due to the way it calculates and represents its information:

  * The indicator **lags** ; it draws confirmed lines and labels into the past, because confirming a new pivot point to update the Zig Zag's structure requires a bar with supporting price action both **before** and **after** that bar. The confirmation lag directly depends on the value of the "Pivot legs" input. 
  * The latest solid line in the Zig Zag is **not final**. The indicator removes or redraws the latest line if subsequent price action invalidates its pivot points.
  * The projection line and label **can change** on each bar, because the indicator consistently updates these drawings to display the next potential pivot point. 
  * The maximum number of lines and labels that an indicator can display is approximately **500**. Therefore, this indicator displays only up to the latest ~500 pivots in the Zig Zag's structure. If the Zig Zag on your chart contains more than 500 pivots, you can use [Bar Replay](<https://www.tradingview.com/support/solutions/43000712747/>) to view the pivots on earlier bars.



#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43627035290/original/mQDNUa-VRcoUedG6mIQa_K-Rn0ZYXeNIyQ.png?1781020842)

#### Price deviation for reversals (%)

Sets the minimum absolute reversal percentage, relative to the last displayed pivot, that the Zig Zag requires to display a new pivot point in the opposite direction of the previous point. 

#### Pivot legs

Specifies the total number of bars required to confirm a pivot point. The indicator divides this number by two, rounding down if necessary, and then checks the resulting number of bars to the left and right of each bar. Larger values require more bars to confirm pivot points, thus increasing the indicator's lag.

#### Line color

Sets the color of the Zig Zag lines. 

#### Calculate projected pivots

Specifies whether the indicator calculates projected pivots on realtime bars. 

If selected, the indicator searches for unconfirmed pivots when a new confirmed pivot is not available. On each bar where the indicator detects a valid but unconfirmed pivot that the Zig Zag can use, it updates the latest solid line and corresponding label as necessary, then displays a temporary dashed line and a label to represent the projected point. The projection updates on each new bar until the indicator identifies the next confirmed pivot point. 

If not selected, the indicator updates its displayed structure only after new, confirmed pivot points become available. 

This setting does not affect the indicator's calculations on historical bars.

#### Display reversal price

Specifies whether the indicator's labels show the price value at each point in the Zig Zag. 

#### Display cumulative volume

Specifies whether the indicator's labels show the total volume accumulated between each point in the Zig Zag. 

#### Display reversal price change

The checkbox specifies whether the indicator's labels show the price change from one point in the Zig Zag to the next. The dropdown input specifies whether each label expresses the change as an absolute price difference or as a percentage of the previous point's price.

PreviousPrevious

Woodies CCI

NextNext

All Chart Patterns

Launch Supercharts

---

[← back to index](./README.md)
