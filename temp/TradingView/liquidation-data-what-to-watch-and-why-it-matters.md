# Liquidation data: what to watch and why it matters

**Source:** <https://www.tradingview.com/support/solutions/43000762400-liquidation-data-what-to-watch-and-why-it-matters/>  
**Indicator ID:** 43000762400  
**Slug:** `liquidation-data-what-to-watch-and-why-it-matters`

[← back to index](./README.md)

---

Liquidations are automatic closures of leveraged positions. Crypto exchanges allow opening leveraged perpetual futures positions, increasing both potential gains and losses. Liquidations occur when a remaining margin falls below the exchange's maintenance margin requirement.

**CONTENTS:**

  * [How to read liquidations data](<#How-to-read-liquidations-data>)
  * [How to protect from a margin call](<#How-to-protect-from-a-margin-call>)
  * [How to find liquidations data on TradingView](<#How-to-find-liquidations-data-on-TradingVIew>)
  * [Exchanges the metric covers](<#Exchanges-the-metric-covers>)



#### How to read liquidations data

Liquidation becomes possible when a trade is leveraged, meaning an exchange lends money to traders so they can open larger positions. The exchange defines a liquidation price based on the amount of funds it lends.

For example, with 2x leverage, the liquidation price would be approximately 50% away from the current price in the opposite direction of the trade. If you open a long trade on Bitcoin at $100,000 with 2x leverage, you might earn 100% if the price reaches $150,000 instead of 50%. But if the price falls to approximately $50,000, you could receive a margin call and the position might eventually be liquidated.

Liquidations exist because exchanges need to protect leveraged positions from falling below required margin levels. When the price moves in the opposite direction, the trade’s loss increases, and the exchange may forcefully close the position to prevent further losses.

Liquidations appear like other trades on the order book, as they are no different from any other trade — it is the same buy or sell transaction.

A **long liquidation** means long positions were forcibly closed.

A **short liquidation** means short positions were forcibly closed.

Whether you are a day trader or gradually building your [portfolio](<https://www.tradingview.com/support/solutions/43000760937/>), liquidations data can support your decision-making:

  * **Support and resistance:** Liquidation clusters often form around key price levels where volatility may increase
  * **Volatility expectations:** Rising liquidations can signal that short-term volatility is likely to remain high
  * **Market sentiment:** Liquidation imbalances can reveal whether the market is too bullish or too bearish, helping spot crowded sentiment
  * **Trend strength:** If price keeps moving after large liquidations, the trend may still be strong. If the move quickly stalls, it may signal exhaustion
  * **Potential reversals:** Large liquidation spikes can happen near local tops or bottoms, where overleveraged traders get wiped out before price stabilizes or reverses
  * **Risk management:** Liquidation data can warn you when the market is becoming overheated, which can help you avoid entering late or using too much leverage
  * **Squeeze detection:** Heavy short liquidations can signal a short squeeze, while heavy long liquidations can signal a long squeeze. In both cases, the price move is driven by excessive leverage rather than a "true" price move



#### How to protect from a margin call

There are a few things to keep in mind, all equally important:

  * **Use less leverage:** Some exchanges provide leverage up to 125x, which almost always leads to portfolio degradation. Even 10x is quite high for intraday trading
  * **Define your strategy:** Identify your risk/reward ratio, holding time, and risk tolerance
  * **Set a proper stop-loss:** Once it is placed, avoid moving or canceling it while hoping for bigger gains
  * **Avoid trading against the trend:** There may be rebounds, but the market can quickly resume the main trend direction



#### How to find liquidations data on TradingView

On [Supercharts](<https://www.tradingview.com/support/solutions/43000746464/>), go to the Indicators dialog → Fundamentals → Derivatives → Funding rate.

Since liquidations data is collected across many exchanges, you can choose how to display it:

  * **Aggregated:** Shows the asset's liquidations across all available exchanges
  * **Non-aggregated:** Shows the asset's liquidations on a single exchange



![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622770278/original/DOfbbhWY6lXkGYhwubLKxpEesZnI4RqSyw.png?1778831860)

> **Note:** The spot market only shows aggregated data. For non-aggregated data, select a futures contract.

Another way to access it is via the [Crypto Coins Screener](<https://www.tradingview.com/support/solutions/43000718742/>).

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622770277/original/XI7eGxC-bokFvgGPJnDMx2EtxxwLOUngHw.png?1778831860)

Since crypto exchanges typically operate 24/7, 24 hours in the screener means data from the past 24 hours, ending at the current minute. This data updates automatically.

In [Fundamental Graphs](<https://www.tradingview.com/support/solutions/43000763376/>), you can more easily compare fundamental and exchange data. Simply select the symbol and its available metrics.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622770281/original/ASL5SHWBxlwpSrXw0Q2L0EXQo9VoWf-Oqw.png?1778831860)

On a coin's symbol page, find the [Derivatives tab](<https://www.tradingview.com/symbols/BTCUSD/derivatives/?exchange=CRYPTO>). There, you'll see this and other key data for the coin.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43622770276/original/9-Vxi5Q9wDdDimOVQ26_XzhUE0aSGH8cYw.png?1778831860)

Symbol pages show aggregated data only.

#### Exchanges the metric covers

Liquidations data is available for crypto perpetual futures on the following exchanges:

  * Binance
  * Bybit
  * Deribit
  * HTX
  * OKX
  * BitMEX (not available for aggregated data)



> **Note:** Values may be shown in base or quoted currency, depending on the exchange and crypto derivative.

#### Liquidations in a nutshell

Liquidations data can help you better understand how leverage affects market behavior, from volatility spikes to crowded positioning and possible reversals. Used together with sound risk management, it can provide context for trading decisions and help navigate the market more carefully.

Also read:

  * [Understanding crypto open interest](<https://www.tradingview.com/support/solutions/43000762388/>)
  * [Introduction to fundamental analysis](<https://www.tradingview.com/support/solutions/43000759574/>)
  * [Funding rate: a guide to market sentiment](<https://www.tradingview.com/support/solutions/43000762390/>)
  * [TradingView indicators: simple steps to get started](<https://www.tradingview.com/support/solutions/43000543626/>)
  * [CEX Screener: discover crypto trading pairs, centralized](<https://www.tradingview.com/support/solutions/43000746110/>)



PreviousPrevious

Linear Regression

NextNext

Long / Short Ratio Accounts

Launch Supercharts

---

[← back to index](./README.md)
