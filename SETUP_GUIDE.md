# OpenBB Platform Setup Guide

## ✅ Installation Complete!

The OpenBB Platform has been successfully installed in a virtual environment.

## Quick Start

### 1. Activate the Virtual Environment

```bash
source venv/bin/activate
```

### 2. Using OpenBB in Python

```python
from openbb import obb

# Example: Get historical stock data
output = obb.equity.price.historical("AAPL", provider="yfinance")
df = output.to_dataframe()
print(df.head())
```

### 3. Start the REST API Server

To run the OpenBB Platform as a REST API:

```bash
# From the project root
uvicorn openbb_core.api.rest_api:app --host 0.0.0.0 --port 8000 --reload
```

Then visit: http://localhost:8000/docs for the interactive API documentation.

## Project Structure

```
OpenBB/
├── venv/                       # Virtual environment (created)
├── openbb_platform/            # Main platform code
│   ├── core/                   # Core functionality
│   ├── extensions/             # Extensions (equity, crypto, etc.)
│   ├── providers/              # Data providers
│   └── dev_install.py          # Development installation script
├── cli/                        # Command-line interface
├── examples/                   # Example notebooks
└── test_openbb.py             # Test script (created)
```

## Configuration

### API Keys

To use data providers that require API keys, create/edit:

```bash
~/.openbb_platform/user_settings.json
```

Example configuration:

```json
{
  "credentials": {
    "fmp_api_key": "YOUR_KEY_HERE",
    "polygon_api_key": "YOUR_KEY_HERE",
    "benzinga_api_key": "YOUR_KEY_HERE",
    "fred_api_key": "YOUR_KEY_HERE"
  }
}
```

### Available Providers

Installed providers include:
- **yfinance** - Yahoo Finance (no API key required)
- **fmp** - Financial Modeling Prep
- **polygon** - Polygon.io
- **fred** - Federal Reserve Economic Data
- **benzinga** - Benzinga
- **intrinio** - Intrinio
- And many more...

## Development Commands

### Run Tests

```bash
# Unit tests only
pytest openbb_platform -m "not integration"

# Integration tests only
pytest openbb_platform -m integration

# All tests
pytest openbb_platform
```

### Build the Platform

If you make changes to extensions, rebuild the platform:

```bash
python -c "import openbb; openbb.build()"
```

### Install Additional Extensions

```bash
# Install a specific provider
pip install openbb-alpha-vantage

# Install charting extension
pip install openbb-charting

# Install all extras
pip install openbb[all]
```

## Common Tasks

### Check Installation

```bash
python test_openbb.py
```

### Interactive Python Session

```bash
python
>>> from openbb import obb
>>> help(obb)
```

### Start Development Server

```bash
cd openbb_platform
uvicorn openbb_core.api.rest_api:app --reload
```

## Troubleshooting

### Import Errors

Make sure the virtual environment is activated:
```bash
source venv/bin/activate
```

### Network Issues

If you see network errors when fetching data:
- Check your internet connection
- Some providers may be temporarily unavailable
- Try using a different provider

### Missing Dependencies

Reinstall the platform:
```bash
cd openbb_platform
python dev_install.py -e
```

## Next Steps

1. **Explore Examples**: Check the `examples/` directory for Jupyter notebooks
2. **Read Documentation**: Visit https://docs.openbb.co
3. **API Reference**: https://docs.openbb.co/python/reference
4. **Join Community**: https://openbb.co/discord

## Useful Commands Summary

```bash
# Activate environment
source venv/bin/activate

# Deactivate environment
deactivate

# Test installation
python test_openbb.py

# Start API server
uvicorn openbb_core.api.rest_api:app --reload

# Run tests
pytest openbb_platform

# Rebuild platform
python -c "import openbb; openbb.build()"
```

## Contributing

To contribute to the OpenBB Platform, see:
- `openbb_platform/CONTRIBUTING.md`
- Developer Guidelines in the documentation

## Support

- Documentation: https://docs.openbb.co
- GitHub Issues: https://github.com/OpenBB-finance/OpenBB/issues
- Discord: https://openbb.co/discord
- Email: support@openbb.co
