# openbb-extension-pine cookbook

Five worked examples, each runnable end-to-end from the current `openbb-pine` M1 install. Every example has been verified live against the actual runtime.

Prerequisites: `pip install openbb-extension-pine`, and (optional for provider examples) an FMP key in `~/.openbb_platform/user_settings.json`. Run `openbb-pine doctor` to sanity-check.

| # | Recipe | FMP required? |
|---|---|---|
| [01](01-bollinger-bands-widget.md) | Bollinger Bands on BYO OHLCV | No |
| [02](02-rsi-oversold-alert.md) | RSI oversold-alert extraction | No |
| [03](03-v5-script-unedited.md) | Pine v5 script running unmodified | No |
| [04](04-multi-indicator-composition.md) | Custom multi-indicator function | No |
| [05](05-openapi-via-curl.md) | Programmatic REST via curl (non-Python) | Yes (or run local BYO-endpoint) |

Powered by PyneSys (https://pynesys.io)
