# Equity Screener Tool

A professional-grade equity screener and financial data analysis tool built on the OpenBB Platform with FMP cached provider integration.

## Features

- **Multi-Symbol Analysis**: Fetch and analyze data for single or multiple stocks simultaneously
- **Advanced Screening**: Apply custom filters based on financial metrics, ratios, and market data
- **Real-Time & Historical Data**: Access both current and historical financial data
- **Professional Analytics**: Built-in technical indicators, risk metrics, and performance calculations  
- **Multiple Export Formats**: CSV, JSON, Excel, and Parquet export capabilities
- **Robust Error Handling**: Professional logging, validation, and error recovery
- **Configurable**: Extensive configuration options via JSON config files
- **Production Ready**: Designed for enterprise use with proper logging and monitoring

## Installation & Setup

1. Ensure the FMP cached provider is properly installed and configured
2. Verify database connectivity
3. Install required Python packages (pandas, openpyxl for Excel export)

```bash
# Make the tool executable
chmod +x equity_screener_tool.py

# Test the installation
python equity_screener_tool.py --version
```

## Quick Start

### 1. Create Demo Data
```bash
# Create 30 days of sample data for AAPL
python equity_screener_tool.py --create-demo-data AAPL --days-back 30

# Create 60 days of data for multiple symbols
python equity_screener_tool.py --create-demo-data TSLA --days-back 60
python equity_screener_tool.py --create-demo-data MSFT --days-back 60
```

### 2. Basic Data Fetching
```bash
# Fetch data for a single symbol
python equity_screener_tool.py --symbol AAPL --start-date 2024-01-01 --end-date 2024-12-31

# Fetch data for multiple symbols
python equity_screener_tool.py --symbols AAPL,TSLA,MSFT --start-date 2024-06-01 --end-date 2024-06-30
```

### 3. Export Data
```bash
# Export to CSV
python equity_screener_tool.py --symbol AAPL --start-date 2024-01-01 --end-date 2024-01-31 --export csv

# Export to Excel with custom filename
python equity_screener_tool.py --symbols AAPL,TSLA --start-date 2024-01-01 --end-date 2024-01-31 --export xlsx --filename "portfolio_analysis.xlsx"

# Export to JSON without metadata
python equity_screener_tool.py --symbol MSFT --start-date 2024-01-01 --end-date 2024-01-31 --export json --no-metadata
```

## Advanced Usage

### Screening and Filtering

Apply custom filters to screen stocks based on financial metrics:

```bash
# Screen for large-cap stocks with reasonable P/E ratios
python equity_screener_tool.py --symbols AAPL,TSLA,MSFT,GOOGL,AMZN \
  --start-date 2024-01-01 --end-date 2024-12-31 \
  --filters '{"market_cap": {"min": 100000000000}, "pe_ratio": {"max": 25}}'

# Screen for high-volume, profitable companies
python equity_screener_tool.py --symbols AAPL,TSLA,MSFT \
  --start-date 2024-01-01 --end-date 2024-12-31 \
  --filters '{"volume": {"min": 1000000}, "roe": {"min": 0.15}}'

# Apply default screening filters from config
python equity_screener_tool.py --symbols AAPL,TSLA,MSFT \
  --start-date 2024-01-01 --end-date 2024-12-31 \
  --apply-default-screens
```

### Configuration File Usage

Create a custom configuration file and use it:

```bash
# Use custom configuration
python equity_screener_tool.py --config my_config.json \
  --symbol AAPL --start-date 2024-01-01 --end-date 2024-12-31
```

### Batch Processing

Process multiple analyses in sequence:

```bash
# Process multiple symbols with different date ranges
python equity_screener_tool.py --symbols AAPL --start-date 2024-01-01 --end-date 2024-03-31 --export csv --filename "AAPL_Q1.csv"
python equity_screener_tool.py --symbols TSLA --start-date 2024-01-01 --end-date 2024-03-31 --export csv --filename "TSLA_Q1.csv"
python equity_screener_tool.py --symbols MSFT --start-date 2024-01-01 --end-date 2024-03-31 --export csv --filename "MSFT_Q1.csv"
```

## Configuration Options

The tool supports extensive configuration via JSON files. See `screener_config.json` for a complete example.

### Key Configuration Sections:

- **Database**: Connection settings, timeouts, retry logic
- **Export**: Default formats, compression, metadata inclusion
- **Analysis**: Technical indicators, risk metrics, calculation windows
- **Screening**: Default filter criteria for stock screening
- **Performance**: Caching, parallel processing, optimization settings

### Example Configuration:

```json
{
  "screening": {
    "min_market_cap": 1000000000,
    "min_volume": 100000,
    "max_pe_ratio": 30,
    "min_roe": 0.10,
    "exclude_sectors": ["Utilities", "Real Estate"]
  },
  "analysis": {
    "volatility_window": 20,
    "include_technical_indicators": true,
    "calculate_returns": true
  }
}
```

## Output Format

The tool provides comprehensive analysis output including:

### Data Summary
- Dataset overview (records, symbols, date range)
- Data quality metrics
- Price analysis (range, averages)
- Volume analysis
- Market capitalization statistics
- Sector/industry breakdowns

### Calculated Metrics
- Daily price ranges and percentages
- Volume ratios and moving averages
- Multi-period returns (1d, 5d, 10d, 20d)
- Volatility metrics
- Risk-adjusted returns (Sharpe ratio)
- Technical indicators
- Valuation categories

### Sample Output:
```
================================================================================
📊 EQUITY SCREENER DATA ANALYSIS REPORT
================================================================================
📋 Dataset Overview:
  • Total Records: 1,230
  • Unique Symbols: 3
  • Date Range: 2024-01-01 to 2024-12-31 (365 days)
  • Data Completeness: 87.5%

💰 Price Analysis:
  • Price Range: $145.32 - $198.75
  • Average Price: $172.18
  • Median Price: $171.50

📈 Volume Analysis:
  • Average Daily Volume: 45,678,901
  • Peak Volume: 125,432,109

🏢 Market Capitalization:
  • Combined Market Cap: $8.7T
  • Average Market Cap: $2.9T
  • Largest Company: $3.2T
```

## Error Handling

The tool includes comprehensive error handling:

- **Data Validation**: Symbol format validation, date range checks
- **Database Errors**: Connection retries, graceful degradation
- **Export Errors**: Format validation, file permission checks
- **Configuration Errors**: Fallback to defaults, validation warnings

## Logging

All operations are logged with different levels:

- **INFO**: Normal operations, data fetching, exports
- **WARNING**: Non-critical issues, data quality concerns
- **ERROR**: Failed operations, critical errors
- **DEBUG**: Detailed execution information

Logs are written to `equity_screener_tool.log` with automatic rotation.

## Performance Considerations

- **Batch Size**: Configure optimal batch sizes for large datasets
- **Caching**: Enable caching for repeated queries
- **Parallel Processing**: Use multiple workers for large symbol lists
- **Memory Management**: Automatic cleanup for large datasets

## Troubleshooting

### Common Issues:

1. **"No data found"**: 
   - Verify symbols exist in database
   - Check date ranges
   - Create demo data first: `--create-demo-data SYMBOL`

2. **Database connection errors**:
   - Check FMP cached provider setup
   - Verify database connectivity
   - Review configuration settings

3. **Export failures**:
   - Check file permissions
   - Verify disk space
   - Validate export format

### Debug Mode:
```bash
# Run with detailed logging
python equity_screener_tool.py --log-level DEBUG --symbol AAPL --start-date 2024-01-01 --end-date 2024-01-31
```

## API Integration

The tool can be easily integrated into other applications:

```python
from equity_screener_tool import EquityScreenerTool

# Initialize tool
screener = EquityScreenerTool(config_file="config.json")

# Fetch data
df = screener.fetch_screener_data(
    symbols=["AAPL", "TSLA"],
    start_date="2024-01-01",
    end_date="2024-12-31"
)

# Apply analysis
df = screener.enrich_data(df)

# Export results
screener.export_data(df, format_type="xlsx")
```

## Contributing

This tool is part of the OpenBB Platform ecosystem. For contributions, improvements, or bug reports, please follow the OpenBB contribution guidelines.

## License

This tool is licensed under the same terms as the OpenBB Platform.

---

For more information and advanced usage examples, see the OpenBB Platform documentation.