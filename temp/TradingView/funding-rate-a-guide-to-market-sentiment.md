# Funding rate: a guide to market sentiment

**Source:** <https://www.tradingview.com/support/solutions/43000762390-funding-rate-a-guide-to-market-sentiment/>  
**Indicator ID:** 43000762390  
**Slug:** `funding-rate-a-guide-to-market-sentiment`

[← back to index](./README.md)

---

Funding rate is a periodic payment exchanged between traders holding perpetual futures positions. If the rate is positive, traders with long positions pay traders with short positions. If it is negative, shorts pay longs. This mechanism is used in crypto perpetual futures to help keep the contract price aligned with the underlying asset's spot price.

**CONTENTS:**

  * [How to read funding rate](<#How-to-use-funding-rate>)
    * [How to read contango and backwardation](<#How-to-read-contango-and-backwardation>)
  * [How funding rate is calculated](<#How-funding-rate-is-calculated>)
  * [How find funding rate on TradingView](<#How-find-funding-rate-on-TradingView>)
  * [Exchanges the metric covers](<#Exchanges-the-metric-covers>)



#### How to read funding rate

Funding rate can help you with different aspects of trading:

  * **Risk management:** A positive or negative funding rate can result in either passive gains or additional costs, which can significantly affect large or long-term positions
  * **Hedging:** If the funding rate favors your perpetual futures position, you can open an opposite position on the spot market and collect funding payments with lower risk
  * **Entry timing:** If the next funding payment is unfavorable and is due soon, you may wait for it to pass before opening a position
  * **Market sentiment:** Shows which side of the market is more crowded and whether it is in the contango or backwardation



#### How to read contango and backwardation

Because perpetual futures are tied to futures pricing dynamics, their price can deviate from the underlying asset's spot price. As a result, the market can be in one of two states:

  * **Contango:** The futures price is higher than the underlying asset's price, and the funding rate is positive
  * **Backwardation:** The futures price is lower than the underlying asset's price, and the funding rate is negative



Either state reflects stronger trader interest on one side of the market. When more traders open long positions, the futures price rises above the underlying price, the market moves into contango, and longs pay shorts. This discourages additional long positions, as traders would have to pay for holding them, while short positions would earn funding over time. The opposite happens in backwardation.

#### How funding rate is calculated

Funding rate is expressed as a percentage of your open position.

Its approximate formula is:

Funding rate = interest rate + premium index

  * **Interest rate:** A fixed component reflecting the cost of capital, usually set at the exchange's discretion
  * **Premium index:** The relative premium or discount of the perpetual contract compared with the underlying index price



> **Note:** Some exchanges may apply proprietary adjustments to this formula. Funding rates therefore usually differ across exchanges.

As you can see, this data can differ significantly. Aggregated data provides a better view of the broader market, while non-aggregated data may be more useful for short-term or exchange-specific trading.

#### How find funding rate on TradingView

On [Supercharts](<https://www.tradingview.com/chart/>), go to the Indicators dialog → Fundamentals → Derivatives → Funding rate.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622773309/original/P4sVyT6P7rAw0_fAC6HmOrmLQ3S-2wkywg.png?1778832948)

Since funding rate is calculated across many exchanges, you can choose how to display the data:

  * **Aggregated:** Shows the asset's funding rate across all available exchanges
  * **Non-aggregated:** Shows the asset's funding rate on a single exchange



> **Important:** TradingView's aggregated funding rate is weighted by open interest, giving more weight to markets with larger open interest. If one exchange has much more open interest than another, its funding rate has a bigger impact on the final aggregated value.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622773311/original/GZYQWgpq0HCTs73897gcTgTP4eYmK8AQiQ.png?1778832948)

> **Note:** The spot market only shows aggregated data. For non-aggregated data, select a futures contract.

Another way to access the metrics is via the [Crypto Coins Screener](<https://www.tradingview.com/support/solutions/43000718742/>).

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622773317/original/ykwx0BN9LJZQc_8WfDaF4ge6B9H1uD34pA.png?1778832948)

In [Fundamental Graphs](<https://www.tradingview.com/support/solutions/43000763376/>), you can more easily compare fundamental and exchange data. Simply select the symbol and its available metrics.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622773307/original/viofrjzhW6x0E8gC6GTVHT-JpwXAzMxHVA.png?1778832948)

On a coin's symbol page, find the [Derivatives tab](<https://www.tradingview.com/symbols/BTCUSD/derivatives/?exchange=CRYPTO>). There, you'll see this and other key data for the coin.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622773308/original/1Gc3xSWfdGV3du2Xde6AT34Be66X68Ue1Q.png?1778832948)

Symbol pages show aggregated data only.

#### Exchanges the metric covers

Funding rate is available for crypto perpetual futures on the following exchanges:

  * Binance
  * Bitget
  * Bybit
  * Coinbase
  * Deribit
  * HTX
  * Kraken
  * OKX
  * BitMEX (not available for aggregated data)



#### Funding rate in a nutshell

Funding rate is a periodic payment between traders holding perpetual futures positions: if it is positive, longs pay shorts, and if it is negative, shorts pay longs. It's used in crypto perpetual futures to keep the contract price close to the underlying asset's spot price.

Beyond the payment itself, funding rate can help you assess market sentiment, estimate holding costs, plan entries, and build lower-risk hedging strategies.A positive rate points to stronger long interest and contango, while a negative rate points to stronger short interest and backwardation.

Also read:

  * [Understanding crypto open interest](<https://www.tradingview.com/support/solutions/43000762388/>)
  * [Introduction to fundamental analysis](<https://www.tradingview.com/support/solutions/43000759574/>)
  * [Liquidation data: what to watch and why it matters](<https://www.tradingview.com/support/solutions/43000762400/>)
  * [TradingView indicators: simple steps to get started](<https://www.tradingview.com/support/solutions/43000543626/>)
  * [CEX Screener: discover crypto trading pairs, centralized](<https://www.tradingview.com/support/solutions/43000746110/>)



PreviousPrevious

Fisher Transform

NextNext

Hash Rate

Launch Supercharts

---

[← back to index](./README.md)
