#!/usr/bin/env python3
"""
Equity Screener Data Fetcher using OpenBB Platform with FMP Cached Provider

This script fetches equity screener data for a given symbol and date range using
the OpenBB Platform with the FMP cached provider. It demonstrates the full
integration of the cached database system with OpenBB's data pipeline.

Usage:
    python fetch_equity_screener.py --symbol AAPL --start-date 2024-01-01 --end-date 2024-12-31
    python fetch_equity_screener.py -s TSLA -sd 2024-06-01 -ed 2024-06-30 --output csv
    python fetch_equity_screener.py --help
"""

import argparse
import sys
import os
from datetime import datetime, date
from typing import Optional, Dict, Any, List
import pandas as pd
import json

# Add OpenBB platform to path
sys.path.insert(0, '/home/daaji/masterswork/git/OpenBB/openbb_platform')
sys.path.insert(0, '/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached')

# OpenBB Platform imports
try:
    from openbb import obb
    from openbb_core.provider.registry import Registry
    from openbb_core.app.model.obbject import OBBject
except ImportError as e:
    print(f"❌ Error importing OpenBB Platform: {e}")
    print("Please ensure OpenBB Platform is properly installed and accessible")
    sys.exit(1)

# FMP Cached Provider imports
try:
    from openbb_fmp_cached.utils.cache_manager import get_database_manager
    from openbb_fmp_cached.utils.database import execute_query
except ImportError as e:
    print(f"❌ Error importing FMP Cached Provider: {e}")
    print("Please ensure the FMP cached provider is properly set up")
    sys.exit(1)


class EquityScreenerFetcher:
    """Fetches and manages equity screener data using OpenBB Platform."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.db_manager = get_database_manager()
        self.log("🚀 Initializing Equity Screener Fetcher")
        
        # Configure OpenBB to use FMP cached provider
        self._configure_openbb()
        
    def log(self, message: str, level: str = "INFO"):
        """Log messages with timestamp if verbose mode is enabled."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {level}: {message}")
    
    def _configure_openbb(self):
        """Configure OpenBB Platform to use FMP cached provider."""
        try:
            # Check if FMP cached provider is available
            available_providers = Registry.providers
            if 'fmp_cached' not in available_providers:
                self.log("⚠️  FMP cached provider not found in registry", "WARNING")
                self.log("Available providers: " + ", ".join(available_providers.keys()))
            else:
                self.log("✅ FMP cached provider found and configured")
                
        except Exception as e:
            self.log(f"❌ Error configuring OpenBB: {e}", "ERROR")
    
    def validate_date_range(self, start_date: str, end_date: str) -> tuple[date, date]:
        """Validate and parse date range."""
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
            
            if start_dt > end_dt:
                raise ValueError("Start date must be before end date")
                
            if end_dt > date.today():
                self.log("⚠️  End date is in the future, adjusting to today", "WARNING")
                end_dt = date.today()
                
            return start_dt, end_dt
            
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD. Error: {e}")
    
    def fetch_with_openbb(self, symbol: str, start_date: date, end_date: date) -> Optional[pd.DataFrame]:
        """Fetch equity screener data using OpenBB Platform."""
        try:
            self.log(f"📡 Fetching data via OpenBB Platform for {symbol}")
            
            # Use OpenBB's equity screener endpoint
            # Note: This will depend on the actual OpenBB API structure
            try:
                # Try to use equity screener if available
                result = obb.equity.screener(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    provider="fmp_cached"
                )
                
                if isinstance(result, OBBject) and result.results is not None:
                    df = pd.DataFrame(result.results)
                    self.log(f"✅ Retrieved {len(df)} records via OpenBB")
                    return df
                    
            except Exception as obb_error:
                self.log(f"⚠️  OpenBB screener not available: {obb_error}", "WARNING")
                
                # Fallback: Try general equity data endpoints
                try:
                    # Get historical price data
                    price_data = obb.equity.price.historical(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        provider="fmp_cached"
                    )
                    
                    if isinstance(price_data, OBBject) and price_data.results:
                        df = pd.DataFrame(price_data.results)
                        self.log(f"✅ Retrieved {len(df)} price records via OpenBB")
                        
                        # Enhance with fundamental data if available
                        try:
                            profile_data = obb.equity.profile(symbol=symbol, provider="fmp_cached")
                            if isinstance(profile_data, OBBject) and profile_data.results:
                                profile_df = pd.DataFrame([profile_data.results])
                                # Add profile data to each row
                                for col in profile_df.columns:
                                    if col not in df.columns:
                                        df[col] = profile_df[col].iloc[0]
                        except Exception as profile_error:
                            self.log(f"⚠️  Could not fetch profile data: {profile_error}", "WARNING")
                        
                        return df
                        
                except Exception as historical_error:
                    self.log(f"❌ Failed to fetch historical data: {historical_error}", "ERROR")
                    
            return None
            
        except Exception as e:
            self.log(f"❌ Error fetching data via OpenBB: {e}", "ERROR")
            return None
    
    def fetch_from_cache(self, symbol: str, start_date: date, end_date: date) -> Optional[pd.DataFrame]:
        """Fetch data directly from the cached database."""
        try:
            self.log(f"🗃️  Checking cached data for {symbol}")
            
            # Query the equity_screener table directly
            query = """
                SELECT * FROM equity_screener 
                WHERE symbol = %s 
                AND date BETWEEN %s AND %s 
                AND is_valid = TRUE
                ORDER BY date DESC
            """
            
            result = execute_query(query, (symbol, start_date, end_date))
            
            if result:
                # Convert to DataFrame using the cache manager
                df = self.db_manager.to_dataframe(result)
                self.log(f"✅ Found {len(df)} cached records")
                return df
            else:
                self.log("📭 No cached data found")
                return None
                
        except Exception as e:
            self.log(f"❌ Error fetching from cache: {e}", "ERROR")
            return None
    
    def enrich_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Enrich the data with additional computed metrics."""
        try:
            if df.empty:
                return df
                
            self.log("🔧 Enriching data with computed metrics")
            
            # Add computed fields
            if 'high' in df.columns and 'low' in df.columns:
                df['daily_range'] = df['high'] - df['low']
                df['daily_range_pct'] = (df['daily_range'] / df['close'] * 100).round(2)
            
            if 'volume' in df.columns:
                df['volume_millions'] = (df['volume'] / 1_000_000).round(2)
            
            if 'market_cap' in df.columns:
                df['market_cap_billions'] = (df['market_cap'] / 1_000_000_000).round(2)
            
            # Add symbol for reference if not present
            if 'symbol' not in df.columns:
                df['symbol'] = symbol
                
            # Sort by date if available
            if 'date' in df.columns:
                df = df.sort_values('date', ascending=False)
            
            self.log(f"✅ Data enriched with {len(df.columns)} total columns")
            return df
            
        except Exception as e:
            self.log(f"❌ Error enriching data: {e}", "ERROR")
            return df
    
    def save_data(self, df: pd.DataFrame, symbol: str, output_format: str = "csv", 
                  output_file: Optional[str] = None) -> str:
        """Save the fetched data to a file."""
        try:
            if df.empty:
                self.log("⚠️  No data to save", "WARNING")
                return ""
            
            # Generate filename if not provided
            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"{symbol}_screener_data_{timestamp}.{output_format}"
            
            # Save based on format
            if output_format.lower() == "csv":
                df.to_csv(output_file, index=False)
            elif output_format.lower() == "json":
                df.to_json(output_file, orient="records", date_format="iso", indent=2)
            elif output_format.lower() == "xlsx":
                df.to_excel(output_file, index=False)
            else:
                raise ValueError(f"Unsupported output format: {output_format}")
            
            self.log(f"💾 Data saved to: {output_file}")
            return output_file
            
        except Exception as e:
            self.log(f"❌ Error saving data: {e}", "ERROR")
            return ""
    
    def display_summary(self, df: pd.DataFrame, symbol: str, start_date: date, end_date: date):
        """Display a summary of the fetched data."""
        print("\n" + "="*60)
        print(f"📊 EQUITY SCREENER DATA SUMMARY - {symbol}")
        print("="*60)
        
        if df.empty:
            print("❌ No data available for the specified criteria")
            return
        
        print(f"📅 Date Range: {start_date} to {end_date}")
        print(f"📈 Records Found: {len(df)}")
        print(f"📋 Data Columns: {len(df.columns)}")
        
        # Key metrics if available
        if 'close' in df.columns:
            latest_price = df['close'].iloc[0] if len(df) > 0 else None
            price_range = f"{df['close'].min():.2f} - {df['close'].max():.2f}"
            print(f"💰 Latest Price: ${latest_price:.2f}" if latest_price else "💰 Latest Price: N/A")
            print(f"📊 Price Range: ${price_range}")
        
        if 'volume' in df.columns:
            avg_volume = df['volume'].mean()
            print(f"📈 Avg Volume: {avg_volume:,.0f}")
        
        if 'market_cap' in df.columns and not df['market_cap'].isna().all():
            market_cap = df['market_cap'].iloc[0] / 1_000_000_000
            print(f"🏢 Market Cap: ${market_cap:.2f}B")
        
        # Show data types
        print(f"\n📋 Column Overview:")
        for col in df.columns[:10]:  # Show first 10 columns
            non_null = df[col].count()
            print(f"  - {col}: {non_null}/{len(df)} non-null values")
        
        if len(df.columns) > 10:
            print(f"  ... and {len(df.columns) - 10} more columns")
        
        # Show sample data
        print(f"\n📄 Sample Data (first 3 rows):")
        key_columns = ['date', 'symbol', 'close', 'volume', 'market_cap']
        display_columns = [col for col in key_columns if col in df.columns]
        if display_columns:
            print(df[display_columns].head(3).to_string(index=False))
        
        print("="*60)
    
    def fetch_equity_screener_data(self, symbol: str, start_date: str, end_date: str,
                                   output_format: str = "display", output_file: Optional[str] = None,
                                   use_cache_first: bool = True) -> Optional[pd.DataFrame]:
        """Main method to fetch equity screener data."""
        try:
            # Validate inputs
            start_dt, end_dt = self.validate_date_range(start_date, end_date)
            symbol = symbol.upper()
            
            self.log(f"🎯 Fetching equity screener data for {symbol} from {start_dt} to {end_dt}")
            
            # Try to fetch data
            df = None
            
            # First, try cache if requested
            if use_cache_first:
                df = self.fetch_from_cache(symbol, start_dt, end_dt)
            
            # If no cached data, try OpenBB
            if df is None or df.empty:
                self.log("📡 Fetching fresh data via OpenBB Platform")
                df = self.fetch_with_openbb(symbol, start_dt, end_dt)
            
            # If still no data, create a simple query
            if df is None or df.empty:
                self.log("⚠️  No data found via standard methods, checking all available data", "WARNING")
                # Try to get any available data for this symbol
                try:
                    query = "SELECT * FROM equity_screener WHERE symbol = %s AND is_valid = TRUE LIMIT 10"
                    result = execute_query(query, (symbol,))
                    if result:
                        df = self.db_manager.to_dataframe(result)
                        self.log(f"📋 Found {len(df)} historical records for {symbol}")
                except Exception as e:
                    self.log(f"❌ No data available: {e}", "ERROR")
            
            if df is None or df.empty:
                self.log(f"❌ No equity screener data found for {symbol}", "ERROR")
                return None
            
            # Enrich the data
            df = self.enrich_data(df, symbol)
            
            # Display summary
            self.display_summary(df, symbol, start_dt, end_dt)
            
            # Save data if requested
            if output_format != "display":
                saved_file = self.save_data(df, symbol, output_format, output_file)
                if saved_file:
                    self.log(f"📁 Data exported to: {saved_file}")
            
            return df
            
        except Exception as e:
            self.log(f"❌ Error in main fetch process: {e}", "ERROR")
            import traceback
            if self.verbose:
                traceback.print_exc()
            return None


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description="Fetch equity screener data using OpenBB Platform with FMP cached provider",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --symbol AAPL --start-date 2024-01-01 --end-date 2024-12-31
  %(prog)s -s TSLA -sd 2024-06-01 -ed 2024-06-30 --output csv
  %(prog)s -s MSFT -sd 2024-01-01 -ed 2024-01-31 --output json --file msft_data.json
        """
    )
    
    # Required arguments
    parser.add_argument(
        '-s', '--symbol', 
        required=True,
        help='Stock symbol to fetch data for (e.g., AAPL, TSLA)'
    )
    
    parser.add_argument(
        '-sd', '--start-date',
        required=True,
        help='Start date in YYYY-MM-DD format'
    )
    
    parser.add_argument(
        '-ed', '--end-date',
        required=True,
        help='End date in YYYY-MM-DD format'
    )
    
    # Optional arguments
    parser.add_argument(
        '-o', '--output',
        choices=['display', 'csv', 'json', 'xlsx'],
        default='display',
        help='Output format (default: display)'
    )
    
    parser.add_argument(
        '-f', '--file',
        help='Output filename (auto-generated if not specified)'
    )
    
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Skip cache and fetch fresh data'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=True,
        help='Enable verbose output (default: True)'
    )
    
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Disable verbose output'
    )
    
    args = parser.parse_args()
    
    # Handle verbose/quiet flags
    verbose = args.verbose and not args.quiet
    
    try:
        # Create fetcher instance
        fetcher = EquityScreenerFetcher(verbose=verbose)
        
        # Fetch data
        df = fetcher.fetch_equity_screener_data(
            symbol=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date,
            output_format=args.output,
            output_file=args.file,
            use_cache_first=not args.no_cache
        )
        
        if df is not None and not df.empty:
            if verbose:
                print(f"\n✅ Successfully fetched {len(df)} records for {args.symbol}")
            sys.exit(0)
        else:
            if verbose:
                print(f"\n❌ No data found for {args.symbol}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()