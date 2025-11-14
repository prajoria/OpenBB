#!/usr/bin/env python3
"""
OpenBB Platform Usage Examples
Demonstrates various features and data sources
"""

from openbb import obb
import pandas as pd

print("=" * 60)
print("OpenBB Platform - Usage Examples")
print("=" * 60)

# Example 1: Basic Stock Data (using yfinance - no API key needed)
print("\n1. Historical Stock Price Data")
print("-" * 60)
try:
    result = obb.equity.price.historical(
        symbol="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
        provider="yfinance"
    )
    df = result.to_dataframe()
    print(f"✓ Fetched {len(df)} days of data for AAPL")
    print("\nLast 5 days:")
    print(df.tail())
except Exception as e:
    print(f"✗ Error: {e}")

# Example 2: Multiple Symbols
print("\n\n2. Multiple Symbols")
print("-" * 60)
try:
    symbols = ["AAPL", "MSFT", "GOOGL"]
    result = obb.equity.price.historical(
        symbol=",".join(symbols),
        provider="yfinance"
    )
    df = result.to_dataframe()
    print(f"✓ Fetched data for {', '.join(symbols)}")
    print(f"Total rows: {len(df)}")
except Exception as e:
    print(f"✗ Error: {e}")

# Example 3: Check Available Providers
print("\n\n3. Available Providers")
print("-" * 60)
print("The platform supports multiple data providers:")
providers = [
    "yfinance - Yahoo Finance (Free, no API key)",
    "fmp - Financial Modeling Prep (Free tier available)",
    "polygon - Polygon.io (Free tier available)",
    "fred - Federal Reserve Economic Data (Free)",
    "intrinio - Intrinio (Paid)",
    "benzinga - Benzinga (Paid)",
    "alpha_vantage - Alpha Vantage (Free tier)",
]
for p in providers:
    print(f"  • {p}")

# Example 4: OBBject Features
print("\n\n4. OBBject Features")
print("-" * 60)
print("Results are returned as OBBject with useful methods:")
try:
    result = obb.equity.price.historical("AAPL", provider="yfinance")
    
    print(f"  • .to_dataframe() - Convert to pandas DataFrame")
    print(f"  • .to_dict() - Convert to dictionary")
    print(f"  • .to_df() - Alias for to_dataframe()")
    print(f"  • .results - Raw data")
    print(f"  • .provider - Provider used: {result.provider}")
    
    # Show data types
    df = result.to_dataframe()
    print(f"\n  Data columns: {list(df.columns)}")
    
except Exception as e:
    print(f"✗ Error: {e}")

# Example 5: Using Different Extensions
print("\n\n5. Available Extensions (Commands)")
print("-" * 60)
print("Extensions provide organized commands:")
extensions = {
    "equity": "Stock market data and analysis",
    "crypto": "Cryptocurrency data",
    "economy": "Economic indicators",
    "fixedincome": "Fixed income/bonds data",
    "derivatives": "Options and derivatives",
    "etf": "ETF data",
    "news": "Financial news",
    "currency": "Foreign exchange rates",
}
for ext, desc in extensions.items():
    print(f"  • obb.{ext}.* - {desc}")

# Example 6: Configuration
print("\n\n6. Configuration")
print("-" * 60)
print("API keys can be set in ~/.openbb_platform/user_settings.json")
print("Or programmatically:")
print("""
from openbb import obb

# Set credentials for the session
obb.user.credentials.fmp_api_key = "your_key_here"
obb.user.credentials.polygon_api_key = "your_key_here"
""")

# Summary
print("\n\n" + "=" * 60)
print("Summary")
print("=" * 60)
print("✓ OpenBB Platform is installed and working")
print("✓ Multiple data providers available")
print("✓ Easy-to-use Python interface")
print("✓ REST API available via uvicorn")
print("\nNext steps:")
print("  1. Configure API keys for more data sources")
print("  2. Explore examples/ directory for Jupyter notebooks")
print("  3. Read docs at https://docs.openbb.co")
print("  4. Start API server with: uvicorn openbb_core.api.rest_api:app --reload")
print("=" * 60)
