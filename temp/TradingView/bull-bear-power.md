# Bull Bear Power

**Source:** <https://www.tradingview.com/support/solutions/43000717955-bull-bear-power/>  
**Indicator ID:** 43000717955  
**Slug:** `bull-bear-power`

[← back to index](./README.md)

---

#### Definition

The Bull Bear Power (BBP) indicator, otherwise known as the Elder-Ray Index, estimates the relationship 

between the strength of bulls (buyers) and bears (sellers) on an instrument. When the indicator's value is nonzero, it supposedly suggests that either bulls or bears have more power in the market. The greater the distance is from zero, the greater the apparent dominance of bulls or bears. Positive values indicate higher bull power and negative values indicate higher bear power.

#### How to access the Bull Bear Power

From Supercharts, on the upper toolbar, click Indicators → Technicals → Bull Bear Power. Or simply type "Bull Bear Power" in the Search.

If you want to screen instruments with the Bull Bear Power, you can either open the desired screener from the right toolbar in the "Products" menu or access the standalone screener from the home page.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43600754790/original/DJjmEkg4q8c-NFqqIz3FJ8CB4F_uZK8Z3g.png?1767958564)

From there, click the "Add new filter" button and select the Bull Bear Power

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43600754966/original/Ub5B43O01G3JLdrrjpBS8DwjQMk2StiTHw.png?1767958614)

  


#### How is the Bull Bear Power calculated

The indicator's calculation consists of two separate components: "Bull Power" and "Bear Power". The "Bull Power" value is the difference between the current high price and the EMA of close prices, and the "Bear Power" value is the difference between the current low price and the same EMA. Taking the sum of the "Bull Power" and "Bear Power" gives us the Bull Bear Power value:

Bull Power = High - EMA

Bear Power = Low - EMA

Bull Bear Power = Bull Power + Bear Power

#### Inputs

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43582452802/original/qaXfqHquDjazjPZWOQZNvTO8Uz_jr5uPag.png?1758723265)

Length

The length for the EMA's smoothing parameter calculation. Its default value is 13.

PreviousPrevious

Bollinger Bars

NextNext

Chaikin Money Flow (CMF)

Launch Supercharts

---

[← back to index](./README.md)
