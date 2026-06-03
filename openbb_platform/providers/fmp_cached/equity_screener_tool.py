#!/usr/bin/env python3
"""
Equity Screener Data Tool - Production-grade Financial Data Fetcher

A professional tool for fetching, analyzing, and exporting equity screener data 
using the FMP cached provider with advanced analytics and screening capabilities.

Features:
- Multi-symbol data fetching with batch processing
- Advanced financial metrics and screening filters
- Real-time and historical data analysis
- Multiple export formats (CSV, JSON, Excel, Parquet)
- Professional logging and error handling
- Configurable data sources and caching strategies
- Built-in technical analysis and risk metrics

Author: OpenBB Platform Team
Version: 1.0.0
License: MIT
"""

import sys
import os
import argparse
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Union, Tuple
import pandas as pd
from pathlib import Path
import configparser
import warnings
warnings.filterwarnings('ignore')

# Add the FMP cached provider to path
sys.path.append('/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached')

try:
    from openbb_fmp_cached.utils.cache_manager import get_database_manager
    from openbb_fmp_cached.utils.database import execute_query
except ImportError as e:
    print(f"❌ Error importing FMP cached provider: {e}")
    print("Please ensure the FMP cached provider is properly installed")
    sys.exit(1)


class EquityScreenerTool:
    """Professional equity screener and financial data analysis tool."""
    
    def __init__(self, config_file: Optional[str] = None, log_level: str = "INFO", verbose: bool = True):
        """Initialize the equity screener tool."""
        self.verbose = verbose
        self.config = self._load_config(config_file)
        self.logger = self._setup_logging(log_level)
        self.db_manager = get_database_manager()
        self.session_stats = {
            'queries_executed': 0,
            'records_fetched': 0,
            'symbols_processed': 0,
            'errors_encountered': 0
        }
        self.logger.info("Equity Screener Tool v1.0.0 initialized")
    
    def _load_config(self, config_file: Optional[str]) -> Dict[str, Any]:
        """Load configuration from file or use production defaults."""
        default_config = {
            "database": {
                "timeout": 30,
                "retry_attempts": 3,
                "batch_size": 100
            },
            "export": {
                "default_format": "csv",
                "include_metadata": True,
                "precision": 4,
                "compression": None
            },
            "analysis": {
                "calculate_returns": True,
                "include_technical_indicators": True,
                "risk_metrics": True,
                "volatility_window": 30
            },
            "screening": {
                "min_market_cap": 1000000000,  # $1B
                "min_volume": 100000,
                "max_pe_ratio": 50,
                "min_roe": 0.05
            },
            "data_quality": {
                "min_records_required": 1,
                "max_null_percentage": 80,
                "validate_data_integrity": True
            },
            "performance": {
                "enable_caching": True,
                "parallel_processing": True,
                "max_workers": 4
            }
        }
        
        if config_file and Path(config_file).exists():
            try:
                with open(config_file, 'r') as f:
                    user_config = json.load(f)
                    # Deep merge configurations
                    for section, values in user_config.items():
                        if section in default_config:
                            default_config[section].update(values)
                        else:
                            default_config[section] = values
                    
                self._log("Configuration loaded from file", f"Using config: {config_file}")
            except Exception as e:
                self._log("Configuration error", f"Failed to load {config_file}: {e}", "WARNING")
        
        return default_config
    
    def _setup_logging(self, log_level: str) -> logging.Logger:
        """Set up professional logging with file rotation."""
        logger = logging.getLogger("EquityScreenerTool")
        logger.setLevel(getattr(logging, log_level.upper()))
        
        # Prevent duplicate handlers
        if logger.handlers:
            logger.handlers.clear()
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # Console handler (simplified for user-facing output)
        if self.verbose:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(simple_formatter)
            console_handler.setLevel(logging.INFO)
            logger.addHandler(console_handler)
        
        # File handler with rotation
        try:
            from logging.handlers import RotatingFileHandler
            log_file = Path("equity_screener_tool.log")
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10*1024*1024, backupCount=5  # 10MB files, keep 5
            )
            file_handler.setFormatter(detailed_formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Could not set up file logging: {e}")
        
        return logger
    
    def _log(self, action: str, message: str, level: str = "INFO"):
        """Unified logging method."""
        log_message = f"{action}: {message}"
        getattr(self.logger, level.lower())(log_message)
        
        if self.verbose and level in ["ERROR", "WARNING"]:
            print(f"{level}: {log_message}")
    
    def validate_symbol(self, symbol: str) -> bool:
        """Validate stock symbol format."""
        if not symbol or len(symbol) < 1 or len(symbol) > 10:
            return False
        
        # Basic symbol validation (letters, numbers, some special chars)
        import re
        return bool(re.match(r'^[A-Z0-9.-]+$', symbol.upper()))
    
    def parse_date_range(self, start_date: str, end_date: str) -> Tuple[date, date]:
        """Parse and validate date range."""
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
            
            if start_dt > end_dt:
                raise ValueError("Start date must be before end date")
            
            if start_dt > date.today():
                raise ValueError("Start date cannot be in the future")
                
            if end_dt > date.today():
                self._log("Date adjustment", "End date adjusted to today", "WARNING")
                end_dt = date.today()
            
            # Limit to reasonable range (10 years max)
            max_range = timedelta(days=365 * 10)
            if end_dt - start_dt > max_range:
                self._log("Date range", f"Large date range detected: {end_dt - start_dt}", "WARNING")
            
            return start_dt, end_dt
            
        except ValueError as e:
            raise ValueError(f"Invalid date format or range: {e}")
    
    def fetch_screener_data(self, symbols: Union[str, List[str]], start_date: str, end_date: str,
                           filters: Optional[Dict[str, Any]] = None) -> Optional[pd.DataFrame]:
        """Fetch equity screener data with advanced filtering."""
        try:
            # Normalize symbols input
            if isinstance(symbols, str):
                symbol_list = [s.strip().upper() for s in symbols.split(',')]
            else:
                symbol_list = [s.strip().upper() for s in symbols]
            
            # Validate symbols
            valid_symbols = []
            for symbol in symbol_list:
                if self.validate_symbol(symbol):
                    valid_symbols.append(symbol)
                else:
                    self._log("Symbol validation", f"Invalid symbol skipped: {symbol}", "WARNING")
            
            if not valid_symbols:
                raise ValueError("No valid symbols provided")
            
            # Parse date range
            start_dt, end_dt = self.parse_date_range(start_date, end_date)
            
            self._log("Data fetch", f"Fetching data for {len(valid_symbols)} symbols from {start_dt} to {end_dt}")
            
            # Build base query
            placeholders = ','.join(['%s'] * len(valid_symbols))
            base_query = f"""
                SELECT * FROM equity_screener 
                WHERE symbol IN ({placeholders})
                AND date BETWEEN %s AND %s 
                AND is_valid = TRUE
            """
            
            # Add filters if provided
            filter_conditions = []
            filter_params = []
            
            if filters:
                for field, criteria in filters.items():
                    if isinstance(criteria, dict):
                        # Handle range filters like {"min": 100, "max": 1000}
                        if 'min' in criteria:
                            filter_conditions.append(f"{field} >= %s")
                            filter_params.append(criteria['min'])
                        if 'max' in criteria:
                            filter_conditions.append(f"{field} <= %s")
                            filter_params.append(criteria['max'])
                    elif isinstance(criteria, (list, tuple)):
                        # Handle IN filters
                        placeholders_filter = ','.join(['%s'] * len(criteria))
                        filter_conditions.append(f"{field} IN ({placeholders_filter})")
                        filter_params.extend(criteria)
                    else:
                        # Handle equality filters
                        filter_conditions.append(f"{field} = %s")
                        filter_params.append(criteria)
            
            if filter_conditions:
                base_query += " AND " + " AND ".join(filter_conditions)
            
            base_query += " ORDER BY symbol, date DESC"
            
            # Execute query
            query_params = valid_symbols + [start_dt, end_dt] + filter_params
            
            self.session_stats['queries_executed'] += 1
            result = execute_query(base_query, tuple(query_params))
            
            if not result:
                self._log("No data", f"No data found for symbols {valid_symbols}")
                return None
            
            # Convert to DataFrame
            df = self.db_manager.to_dataframe(result)
            
            if df.empty:
                self._log("Empty dataset", "Query returned empty dataset")
                return None
            
            self.session_stats['records_fetched'] += len(df)
            self.session_stats['symbols_processed'] += len(df['symbol'].unique()) if 'symbol' in df.columns else 0
            
            self._log("Data retrieved", f"Retrieved {len(df)} records for {df['symbol'].nunique() if 'symbol' in df.columns else 'unknown'} symbols")
            
            return df
            
        except Exception as e:
            self.session_stats['errors_encountered'] += 1
            self._log("Fetch error", str(e), "ERROR")
            return None
    
    def apply_screening_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply default screening filters based on configuration."""
        if df.empty:
            return df
        
        try:
            original_count = len(df)
            screening_config = self.config.get('screening', {})
            
            # Market cap filter
            min_market_cap = screening_config.get('min_market_cap')
            if min_market_cap and 'market_cap' in df.columns:
                df = df[df['market_cap'] >= min_market_cap]
            
            # Volume filter
            min_volume = screening_config.get('min_volume')
            if min_volume and 'volume' in df.columns:
                df = df[df['volume'] >= min_volume]
            
            # PE ratio filter
            max_pe = screening_config.get('max_pe_ratio')
            if max_pe and 'pe_ratio' in df.columns:
                df = df[df['pe_ratio'] <= max_pe]
            
            # ROE filter
            min_roe = screening_config.get('min_roe')
            if min_roe and 'roe' in df.columns:
                df = df[df['roe'] >= min_roe]
            
            filtered_count = len(df)
            if filtered_count != original_count:
                self._log("Screening", f"Applied filters: {original_count} → {filtered_count} records")
            
            return df
            
        except Exception as e:
            self._log("Screening error", str(e), "ERROR")
            return df
    
    def enrich_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich data with calculated metrics and analysis."""
        if df.empty:
            return df
        
        try:
            self._log("Data enrichment", "Adding calculated metrics")
            
            # Price-based metrics
            if all(col in df.columns for col in ['high', 'low', 'close']):
                df['daily_range'] = df['high'] - df['low']
                df['daily_range_pct'] = (df['daily_range'] / df['close'] * 100).round(4)
                df['midpoint'] = (df['high'] + df['low']) / 2
            
            # Volume metrics
            if 'volume' in df.columns:
                df['volume_millions'] = (df['volume'] / 1_000_000).round(2)
                
                # Volume moving average (if we have multiple days)
                if len(df) > 1:
                    df['volume_ma_5'] = df.groupby('symbol')['volume'].rolling(5, min_periods=1).mean()
                    df['volume_ratio'] = df['volume'] / df['volume_ma_5']
            
            # Market cap in billions
            if 'market_cap' in df.columns:
                df['market_cap_billions'] = (df['market_cap'] / 1_000_000_000).round(2)
            
            # Price returns (if we have historical data)
            if 'close' in df.columns and len(df) > 1:
                df = df.sort_values(['symbol', 'date'])
                df['daily_return'] = df.groupby('symbol')['close'].pct_change()
                df['return_1d'] = df['daily_return'] * 100
                
                # Multi-day returns
                for days in [5, 10, 20]:
                    if len(df) >= days:
                        df[f'return_{days}d'] = (df.groupby('symbol')['close'].pct_change(days) * 100).round(4)
            
            # Volatility metrics
            if 'daily_return' in df.columns:
                volatility_window = self.config.get('analysis', {}).get('volatility_window', 20)
                df['volatility'] = df.groupby('symbol')['daily_return'].rolling(volatility_window, min_periods=5).std() * 100
            
            # Risk-adjusted metrics
            if all(col in df.columns for col in ['daily_return', 'volatility']):
                df['sharpe_ratio'] = df['daily_return'] / df['volatility']
            
            # Valuation flags
            if 'pe_ratio' in df.columns:
                df['pe_category'] = pd.cut(df['pe_ratio'], 
                                         bins=[0, 15, 25, 40, float('inf')],
                                         labels=['Low', 'Moderate', 'High', 'Very High'])
            
            # Momentum indicators
            if 'close' in df.columns and len(df) > 20:
                df['price_vs_ma20'] = df.groupby('symbol')['close'].apply(
                    lambda x: ((x - x.rolling(20, min_periods=1).mean()) / x.rolling(20, min_periods=1).mean() * 100).round(2)
                )
            
            # Data quality score
            df['data_quality_score'] = (df.count(axis=1) / len(df.columns) * 100).round(1)
            
            self._log("Enrichment complete", f"Added calculated metrics to {len(df)} records")
            return df
            
        except Exception as e:
            self._log("Enrichment error", str(e), "ERROR")
            return df
    
    def export_data(self, df: pd.DataFrame, filename: Optional[str] = None, 
                   format_type: str = "csv", include_metadata: bool = True) -> str:
        """Export data with professional formatting and metadata."""
        try:
            if df.empty:
                raise ValueError("No data to export")
            
            # Generate filename if not provided
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                symbols = df['symbol'].nunique() if 'symbol' in df.columns else 'multi'
                symbol_text = df['symbol'].iloc[0] if symbols == 1 else f"{symbols}_symbols"
                filename = f"equity_screener_{symbol_text}_{timestamp}.{format_type}"
            
            # Ensure proper file extension
            if not filename.endswith(f'.{format_type}'):
                filename = f"{filename}.{format_type}"
            
            # Add metadata if requested
            export_df = df.copy()
            if include_metadata:
                export_df['export_timestamp'] = datetime.now().isoformat()
                export_df['data_source'] = 'FMP_Cached_Provider'
                export_df['tool_version'] = '1.0.0'
            
            # Export based on format
            compression = self.config.get('export', {}).get('compression')
            
            if format_type.lower() == 'csv':
                export_df.to_csv(filename, index=False, compression=compression)
            elif format_type.lower() == 'json':
                export_df.to_json(filename, orient='records', date_format='iso', 
                                indent=2, compression=compression)
            elif format_type.lower() == 'xlsx':
                with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                    export_df.to_excel(writer, sheet_name='ScreenerData', index=False)
                    
                    # Add summary sheet
                    if 'symbol' in df.columns:
                        summary = df.groupby('symbol').agg({
                            'close': ['first', 'min', 'max', 'mean'] if 'close' in df.columns else 'count',
                            'volume': 'mean' if 'volume' in df.columns else 'count',
                            'market_cap': 'first' if 'market_cap' in df.columns else 'count'
                        }).round(4)
                        summary.to_excel(writer, sheet_name='Summary')
            elif format_type.lower() == 'parquet':
                export_df.to_parquet(filename, compression=compression or 'snappy')
            else:
                raise ValueError(f"Unsupported export format: {format_type}")
            
            file_size = os.path.getsize(filename) / 1024  # KB
            self._log("Export complete", f"Exported {len(export_df)} records to {filename} ({file_size:.1f} KB)")
            
            return filename
            
        except Exception as e:
            self._log("Export error", str(e), "ERROR")
            return ""
    
    def get_data_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate comprehensive data summary statistics."""
        if df.empty:
            return {"error": "No data available"}
        
        try:
            summary = {
                "basic_stats": {
                    "total_records": len(df),
                    "unique_symbols": df['symbol'].nunique() if 'symbol' in df.columns else 0,
                    "date_range": {
                        "start": df['date'].min().strftime('%Y-%m-%d') if 'date' in df.columns else None,
                        "end": df['date'].max().strftime('%Y-%m-%d') if 'date' in df.columns else None,
                        "days": (df['date'].max() - df['date'].min()).days if 'date' in df.columns else 0
                    },
                    "data_quality": {
                        "completeness": (df.count().sum() / (len(df) * len(df.columns)) * 100).round(2),
                        "null_percentage": (df.isnull().sum().sum() / (len(df) * len(df.columns)) * 100).round(2)
                    }
                }
            }
            
            # Price statistics
            if 'close' in df.columns:
                summary["price_stats"] = {
                    "latest_price_range": {
                        "min": float(df['close'].min()),
                        "max": float(df['close'].max()),
                        "mean": float(df['close'].mean().round(2)),
                        "median": float(df['close'].median())
                    }
                }
            
            # Volume statistics  
            if 'volume' in df.columns:
                summary["volume_stats"] = {
                    "average_volume": int(df['volume'].mean()),
                    "total_volume": int(df['volume'].sum()),
                    "max_volume": int(df['volume'].max())
                }
            
            # Market cap statistics
            if 'market_cap' in df.columns:
                summary["market_cap_stats"] = {
                    "total_market_cap": int(df['market_cap'].sum()),
                    "average_market_cap": int(df['market_cap'].mean()),
                    "largest_company": int(df['market_cap'].max())
                }
            
            # Sector/Industry breakdown
            if 'sector' in df.columns:
                summary["sector_breakdown"] = df['sector'].value_counts().to_dict()
            
            if 'industry' in df.columns:
                summary["industry_breakdown"] = df['industry'].value_counts().head(10).to_dict()
            
            return summary
            
        except Exception as e:
            self._log("Summary error", str(e), "ERROR")
            return {"error": str(e)}
    
    def display_summary(self, df: pd.DataFrame, symbols: Union[str, List[str]]):
        """Display professional data summary."""
        if df.empty:
            print("❌ No data available to display")
            return
        
        # Get comprehensive summary
        summary = self.get_data_summary(df)
        
        print("\n" + "="*80)
        print("📊 EQUITY SCREENER DATA ANALYSIS REPORT")
        print("="*80)
        
        # Basic information
        basic = summary.get('basic_stats', {})
        print(f"📋 Dataset Overview:")
        print(f"  • Total Records: {basic.get('total_records', 0):,}")
        print(f"  • Unique Symbols: {basic.get('unique_symbols', 0)}")
        
        date_range = basic.get('date_range', {})
        if date_range.get('start'):
            print(f"  • Date Range: {date_range['start']} to {date_range['end']} ({date_range['days']} days)")
        
        # Data quality
        quality = basic.get('data_quality', {})
        print(f"  • Data Completeness: {quality.get('completeness', 0):.1f}%")
        
        # Financial metrics
        if 'price_stats' in summary:
            price_stats = summary['price_stats']['latest_price_range']
            print(f"\n💰 Price Analysis:")
            print(f"  • Price Range: ${price_stats['min']:.2f} - ${price_stats['max']:.2f}")
            print(f"  • Average Price: ${price_stats['mean']:.2f}")
            print(f"  • Median Price: ${price_stats['median']:.2f}")
        
        if 'volume_stats' in summary:
            vol_stats = summary['volume_stats']
            print(f"\n📈 Volume Analysis:")
            print(f"  • Average Daily Volume: {vol_stats['average_volume']:,}")
            print(f"  • Peak Volume: {vol_stats['max_volume']:,}")
        
        if 'market_cap_stats' in summary:
            mc_stats = summary['market_cap_stats']
            print(f"\n🏢 Market Capitalization:")
            print(f"  • Combined Market Cap: ${mc_stats['total_market_cap']/1e9:.1f}B")
            print(f"  • Average Market Cap: ${mc_stats['average_market_cap']/1e9:.1f}B")
            print(f"  • Largest Company: ${mc_stats['largest_company']/1e9:.1f}B")
        
        # Sector breakdown
        if 'sector_breakdown' in summary and summary['sector_breakdown']:
            print(f"\n🎯 Sector Distribution:")
            for sector, count in list(summary['sector_breakdown'].items())[:5]:
                print(f"  • {sector}: {count} companies")
        
        # Recent data sample
        if 'close' in df.columns and 'volume' in df.columns:
            print(f"\n📄 Recent Data Sample:")
            display_cols = ['symbol', 'date', 'close', 'volume']
            if 'change_percent' in df.columns:
                display_cols.append('change_percent')
            
            sample_df = df[display_cols].head(5).copy()
            
            # Format for display
            if 'close' in sample_df.columns:
                sample_df['close'] = sample_df['close'].apply(lambda x: f"${x:.2f}")
            if 'volume' in sample_df.columns:
                sample_df['volume'] = sample_df['volume'].apply(lambda x: f"{x:,.0f}")
            if 'change_percent' in sample_df.columns:
                sample_df['change_percent'] = sample_df['change_percent'].apply(lambda x: f"{x:.2f}%")
            
            print(sample_df.to_string(index=False))
        
        # Session statistics
        print(f"\n🔧 Session Statistics:")
        print(f"  • Queries Executed: {self.session_stats['queries_executed']}")
        print(f"  • Records Processed: {self.session_stats['records_fetched']:,}")
        print(f"  • Symbols Analyzed: {self.session_stats['symbols_processed']}")
        if self.session_stats['errors_encountered'] > 0:
            print(f"  • Errors Encountered: {self.session_stats['errors_encountered']}")
        
        print("="*80 + "\n")
    
    def create_demo_data(self, symbol: str, days_back: int = 30) -> bool:
        """Create realistic demo data for testing and demonstration."""
        return self.create_sample_data(symbol, days_back, realistic=True)
    
    def create_sample_data(self, symbol: str, days_back: int = 30, realistic: bool = True) -> bool:
        """Create sample equity screener data."""
        try:
            self._log("Sample data", f"Creating {days_back} days of data for {symbol}")
            
            base_date = date.today() - timedelta(days=days_back)
            base_price = 150.0
            
            for i in range(days_back):
                current_date = base_date + timedelta(days=i)
                
                # Create realistic price movements
                if realistic:
                    # Simulate random walk with slight upward trend
                    import random
                    random.seed(i + hash(symbol))  # Consistent randomness per symbol
                    price_change = random.normalvariate(0.1, 1.5)  # Small upward bias with volatility
                    volume_base = random.randint(20000000, 80000000)
                    volume_variance = random.randint(-5000000, 15000000)
                else:
                    price_change = i * 0.5
                    volume_base = 45000000
                    volume_variance = i * 100000
                
                current_price = max(base_price + (i * 0.1) + price_change, 10.0)  # Prevent negative prices
                
                sample_data = {
                    'symbol': symbol,
                    'date': current_date,
                    'period': 'daily',
                    'currency': 'USD',
                    'exchange': 'NASDAQ' if symbol in ['AAPL', 'MSFT', 'GOOGL'] else 'NYSE',
                    
                    # Price data with realistic movements
                    'open': max(current_price + random.normalvariate(0, 0.5), 1.0) if realistic else current_price - 1.0,
                    'high': current_price + abs(random.normalvariate(1.0, 0.5)) if realistic else current_price + 2.0,
                    'low': max(current_price - abs(random.normalvariate(1.0, 0.5)), 1.0) if realistic else current_price - 2.0,
                    'close': current_price,
                    'volume': max(volume_base + volume_variance, 100000),
                    'vwap': current_price + random.normalvariate(0, 0.2) if realistic else current_price - 0.5,
                    'change': price_change if i > 0 else 0,
                    'change_percent': (price_change / base_price * 100) if i > 0 and base_price > 0 else 0,
                    'price': current_price,
                    
                    # Company info (varies by symbol)
                    'company_name': f'{symbol} Corporation',
                    'sector': 'Technology' if symbol in ['AAPL', 'MSFT', 'GOOGL'] else 'Healthcare',
                    'industry': 'Software' if symbol in ['MSFT', 'GOOGL'] else 'Consumer Electronics',
                    'country': 'United States',
                    'market_cap': max(int(current_price * 16_000_000_000), 1_000_000_000),  # Approximate market cap
                    'beta': 1.25 + (i * 0.001),
                    'employees': random.randint(50000, 200000) if realistic else 164000,
                    
                    # Financial metrics (should be relatively stable)
                    'revenue': random.randint(200_000_000_000, 400_000_000_000) if realistic else 365817000000,
                    'net_income': random.randint(50_000_000_000, 100_000_000_000) if realistic else 94680000000,
                    'eps': round(random.uniform(3.0, 8.0), 2) if realistic else 5.89,
                    'eps_diluted': round(random.uniform(3.0, 8.0), 2) if realistic else 5.89,
                    
                    # Ratios for screening (with some variation)
                    'pe_ratio': max(round(random.uniform(15.0, 35.0), 2), 1.0) if realistic else 26.21,
                    'pb_ratio': round(random.uniform(25.0, 50.0), 2) if realistic else 39.55,
                    'debt_to_equity': round(random.uniform(0.5, 2.5), 2) if realistic else 1.88,
                    'current_ratio': round(random.uniform(0.8, 2.0), 2) if realistic else 1.07,
                    'roe': round(random.uniform(0.1, 0.8), 3) if realistic else 0.617,
                    'roa': round(random.uniform(0.05, 0.4), 3) if realistic else 0.259
                }
                
                success = self.db_manager._store_record('equity_screener', sample_data)
                if not success:
                    self._log("Storage error", f"Failed to store data for {current_date}", "ERROR")
                    return False
            
            self._log("Sample data complete", f"Successfully created {days_back} days of data for {symbol}")
            return True
            
        except Exception as e:
            self._log("Sample data error", str(e), "ERROR")
            return False


def create_cli_parser() -> argparse.ArgumentParser:
    """Create comprehensive CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Professional Equity Screener Data Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch data for single symbol
  %(prog)s --symbol AAPL --start-date 2024-01-01 --end-date 2024-12-31
  
  # Fetch data for multiple symbols
  %(prog)s --symbols AAPL,TSLA,MSFT --start-date 2024-06-01 --end-date 2024-06-30
  
  # Apply screening filters
  %(prog)s --symbols AAPL,TSLA --filters '{"market_cap": {"min": 1000000000}, "pe_ratio": {"max": 30}}'
  
  # Export to different formats
  %(prog)s --symbol TSLA --start-date 2024-01-01 --end-date 2024-01-31 --export xlsx --filename tesla_data.xlsx
  
  # Create demo data
  %(prog)s --create-demo-data AAPL --days-back 60
  
  # Use configuration file
  %(prog)s --config screener_config.json --symbol MSFT --start-date 2024-01-01 --end-date 2024-12-31
        """
    )
    
    # Main operation arguments
    group_main = parser.add_argument_group('Data Fetching')
    group_main.add_argument(
        '--symbol', 
        help='Single stock symbol to analyze (e.g., AAPL)'
    )
    
    group_main.add_argument(
        '--symbols',
        help='Comma-separated list of symbols (e.g., AAPL,TSLA,MSFT)'
    )
    
    group_main.add_argument(
        '--start-date', '-sd',
        help='Start date in YYYY-MM-DD format'
    )
    
    group_main.add_argument(
        '--end-date', '-ed', 
        help='End date in YYYY-MM-DD format'
    )
    
    # Filtering and screening
    group_filter = parser.add_argument_group('Filtering & Screening')
    group_filter.add_argument(
        '--filters',
        help='JSON string with screening filters (e.g., \'{"market_cap": {"min": 1000000000}}\')'
    )
    
    group_filter.add_argument(
        '--apply-default-screens',
        action='store_true',
        help='Apply default screening filters from configuration'
    )
    
    # Export options
    group_export = parser.add_argument_group('Export Options')
    group_export.add_argument(
        '--export', '-e',
        choices=['csv', 'json', 'xlsx', 'parquet'],
        default='display',
        help='Export format (default: display only)'
    )
    
    group_export.add_argument(
        '--filename', '-f',
        help='Output filename (auto-generated if not specified)'
    )
    
    group_export.add_argument(
        '--no-metadata',
        action='store_true', 
        help='Exclude metadata from exports'
    )
    
    # Data creation and management
    group_data = parser.add_argument_group('Data Management')
    group_data.add_argument(
        '--create-demo-data',
        help='Create realistic demo data for specified symbol'
    )
    
    group_data.add_argument(
        '--days-back',
        type=int,
        default=30,
        help='Number of days of historical data to create (default: 30)'
    )
    
    # Configuration and logging
    group_config = parser.add_argument_group('Configuration')
    group_config.add_argument(
        '--config', '-c',
        help='Configuration file path (JSON format)'
    )
    
    group_config.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level (default: INFO)'
    )
    
    group_config.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress verbose output'
    )
    
    group_config.add_argument(
        '--version',
        action='version',
        version='Equity Screener Tool v1.0.0'
    )
    
    return parser


def main():
    """Main CLI interface for the equity screener tool."""
    parser = create_cli_parser()
    args = parser.parse_args()
    
    try:
        # Initialize tool
        tool = EquityScreenerTool(
            config_file=args.config,
            log_level=args.log_level,
            verbose=not args.quiet
        )
        
        # Handle demo data creation
        if args.create_demo_data:
            symbol = args.create_demo_data.upper()
            success = tool.create_demo_data(symbol, args.days_back)
            if success:
                print(f"✅ Demo data created for {symbol}")
                return 0
            else:
                print(f"❌ Failed to create demo data for {symbol}")
                return 1
        
        # Validate required arguments for data fetching
        symbols_input = args.symbols or args.symbol
        if not symbols_input or not args.start_date or not args.end_date:
            print("❌ Error: Symbol(s), start-date, and end-date are required for data fetching")
            print("Use --help for usage information or --create-demo-data to create sample data")
            return 1
        
        # Parse filters if provided
        filters = None
        if args.filters:
            try:
                filters = json.loads(args.filters)
            except json.JSONDecodeError as e:
                print(f"❌ Error: Invalid JSON in filters: {e}")
                return 1
        
        # Fetch data
        df = tool.fetch_screener_data(
            symbols=symbols_input,
            start_date=args.start_date,
            end_date=args.end_date,
            filters=filters
        )
        
        if df is None or df.empty:
            print("❌ No data found for the specified criteria")
            print("💡 Try creating demo data first with --create-demo-data SYMBOL")
            return 1
        
        # Apply default screening if requested
        if args.apply_default_screens:
            df = tool.apply_screening_filters(df)
            if df.empty:
                print("❌ No data remains after applying screening filters")
                return 1
        
        # Enrich data with calculated metrics
        df = tool.enrich_data(df)
        
        # Display summary
        tool.display_summary(df, symbols_input)
        
        # Export if requested
        if args.export != 'display':
            filename = tool.export_data(
                df=df,
                filename=args.filename,
                format_type=args.export,
                include_metadata=not args.no_metadata
            )
            
            if filename:
                print(f"📁 Data exported to: {filename}")
            else:
                print("❌ Export failed")
                return 1
        
        print("✅ Analysis completed successfully")
        return 0
        
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        if not args.quiet:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())