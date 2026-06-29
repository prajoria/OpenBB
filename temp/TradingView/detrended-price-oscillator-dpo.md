# Detrended Price Oscillator (DPO)

**Source:** <https://www.tradingview.com/support/solutions/43000502246-detrended-price-oscillator-dpo/>  
**Indicator ID:** 43000502246  
**Slug:** `detrended-price-oscillator-dpo`

[← back to index](./README.md)

---

#### Definition

The [Detrended Price Oscillator indicator (DPO)](<https://www.tradingview.com/scripts/detrendedpriceoscillator/>) is used to remove trend from price. This is done in order to identify and isolate short-term cycles. DPO is not typically aligned with the most current prices. It is offset to the left (the past) which helps to remove current trend. Because it is offset to the past, the DPO is not considered a momentum oscillator. It only measures past prices against a Simple Moving Average as a way to gauge a cycle's high/low range as well as typical duration.

#### Calculation
[code]
    (Price of (N/2 + 1) periods ago) - (N Period SMA) = DPO
    N = The user defined look-back period
[/code]

#### The basics

The Detrended Price Oscillator indicator (DPO) compares past prices to a displaced (shifted to the past) Simple Moving Average. The SMA is displayed a Zero Line, with DPO fluctuating between positive (above the line) and negative (below the line) values. Simply put, a positive values means that price was above the SMA and a negative value means price was below the SMA.

#### What to look for

The main purpose of the DPO is to analyze historical data in order to observe cycle's in a market's movement. DPO can give the technical analyst a better sense of a cycle's typical high/low range as well as its duration.

##### Cycle High/Low Range

##### Cycle Duration

#### Summary

The Detrended Price Oscillator (DPO)is not necessarily intended to be a signal-generating indicator. Instead it is best served as a way for a technical analyst to build confidence when identifying the characteristics of a trading instrument's typical cycle. Because of this, it would be prudent to use the DPO alongside additional indicators which are designed to gauge trend or momentum.

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43586537314/original/McF25flI4hIeTxE2pYEo2mtvXaS8B4NuBA.png?1760615712)

##### Period

The time period to be used in calculating the DPO.

##### Centered

When the DPO is centered, the DPO line stays offset towards the left. When it is not centered, it shifts back to the right to match current price.

#### Style

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43586537360/original/7zMxd2C8AmqkagaDpfr39X_5-ZPsocHAEg.png?1760615726)

##### Detrended Price Oscillator

Can toggle the visibility of the DPO as well as the visibility of a price line showing the actual current value of the DPO. Can also select the DPO Line's color, line thickness and visual style (Line is the Default).

##### Zero Line

Can toggle the visibility of the Zero Line. Can also select the line’s value, line thickness, value and visual type (dashes is the default).

##### Precision

Sets the number of decimal places to be left on the indicator's value before rounding up. The higher this number, the more decimal points will be on the indicator's value.

PreviousPrevious

Cumulative Volume Index (CVI)

NextNext

Difficulty

Launch Supercharts

---

[← back to index](./README.md)
