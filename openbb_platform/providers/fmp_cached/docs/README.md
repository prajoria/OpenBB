# FMP Cached Provider for OpenBB

This provider extends the FMP (Financial Modeling Prep) provider with MySQL caching capabilities to improve performance and reduce API calls.

## Features

- **Cache-first architecture**: Checks cache before making API calls
- **MySQL storage**: Persistent caching with proper table structure
- **Configurable TTL**: Time-to-live settings for different data types
- **Full FMP compatibility**: Drop-in replacement for the FMP provider
- **Automatic cache management**: Handles cache expiration and cleanup

## Configuration

Add MySQL configuration to your `~/.openbb_platform/user_settings.json`:

```json
{
    "credentials": {
        "fmp_api_key": "your_fmp_api_key_here",
        "mysql_host": "localhost",
        "mysql_port": 3306,
        "mysql_user": "openbb_user",
        "mysql_password": "your_password",
        "mysql_database": "openbb_cache"
    }
}
```

## Usage

Use exactly like the FMP provider, but with `provider="fmp_cached"`:

```python
from openbb import obb

# This will first check cache, then call FMP API if needed
data = obb.equity.price.historical("AAPL", provider="fmp_cached")
```

## Cache TTL Settings

Default cache expiration times:
- Historical prices: 1 hour for intraday, 24 hours for daily
- Fundamentals: 24 hours
- Real-time quotes: 1 minute
- Company info: 7 days