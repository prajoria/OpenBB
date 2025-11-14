#!/usr/bin/env python3
"""Test script to verify OpenBB Platform installation."""

from openbb import obb

print("OpenBB Platform installed successfully!")
print(f"OpenBB version: {obb.__version__ if hasattr(obb, '__version__') else 'N/A'}")

# Example: Get historical stock data
print("\n=== Testing with a simple example ===")
print("Fetching historical data for AAPL...")

try:
    # This will use yfinance provider which doesn't require API keys
    output = obb.equity.price.historical("AAPL", provider="yfinance")
    df = output.to_dataframe()
    
    print(f"\nData fetched successfully!")
    print(f"Rows: {len(df)}")
    print(f"\nFirst few rows:")
    print(df.head())
    print(f"\nLast few rows:")
    print(df.tail())
    
except Exception as e:
    print(f"Error: {e}")
    print("\nNote: Some providers may require API keys to be configured.")
    print("You can set them in ~/.openbb_platform/user_settings.json")

print("\n=== Setup Complete ===")
print("\nTo use OpenBB Platform:")
print("1. Activate the virtual environment: source venv/bin/activate")
print("2. Import in Python: from openbb import obb")
print("3. Start API server: uvicorn openbb_core.api.rest_api:app --reload")
print("\nFor more information, visit: https://docs.openbb.co")
