# 🚀 OpenBB Platform - Quick Start

## ✅ Setup Complete!

Your OpenBB Platform development environment is ready to use!

## 📁 What Was Installed

- ✓ Python 3.12.3 virtual environment (`venv/`)
- ✓ Poetry package manager
- ✓ OpenBB Platform core and all extensions
- ✓ All data providers (50+ providers)
- ✓ Development tools and dependencies

## 🎯 Quick Commands

### Activate Environment
```bash
source venv/bin/activate
```

### Helper Script
```bash
./openbb.sh test      # Test installation
./openbb.sh api       # Start REST API
./openbb.sh shell     # Python shell with OpenBB
./openbb.sh pytest    # Run tests
```

### Manual Commands
```bash
# Test OpenBB
python test_openbb.py

# Start API server
uvicorn openbb_core.api.rest_api:app --host 0.0.0.0 --port 8000 --reload

# Python interactive
python
>>> from openbb import obb
>>> help(obb)
```

## 💡 Simple Python Example

```python
from openbb import obb

# Get stock data (no API key needed)
result = obb.equity.price.historical("AAPL", provider="yfinance")
df = result.to_dataframe()
print(df.head())
```

## 🔑 Configure API Keys (Optional)

Create `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "fmp_api_key": "YOUR_KEY",
    "polygon_api_key": "YOUR_KEY",
    "fred_api_key": "YOUR_KEY"
  }
}
```

## 📚 Resources

- **Setup Guide**: `SETUP_GUIDE.md` (detailed instructions)
- **Examples**: `examples_usage.py` (usage examples)
- **Documentation**: https://docs.openbb.co
- **API Docs**: http://localhost:8000/docs (after starting server)

## 🛠 Development

```bash
# Rebuild platform after changes
python -c "import openbb; openbb.build()"

# Run tests
pytest openbb_platform -m "not integration"

# Reinstall all packages
cd openbb_platform && python dev_install.py -e
```

## 📝 Files Created

- `SETUP_GUIDE.md` - Comprehensive setup guide
- `QUICK_START.md` - This file
- `test_openbb.py` - Installation test script
- `examples_usage.py` - Usage examples
- `openbb.sh` - Helper script
- `venv/` - Virtual environment directory

## 🎉 You're Ready!

Start exploring the OpenBB Platform. Happy coding! 🚀
