# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OpenBB is an open-source financial data platform that provides the "connect once, consume everywhere" infrastructure for integrating financial data sources. The project consists of multiple components:

- **OpenBB Platform** (Python): Core data integration platform with 50+ data providers
- **OpenBB CLI**: Command-line interface for the platform
- **Desktop App**: Tauri-based desktop application with React frontend
- **API Server**: FastAPI REST API server for external integrations

## Architecture

### Core Structure
- `openbb_platform/core/`: Core platform functionality and OBB object
- `openbb_platform/extensions/`: Domain-specific extensions (equity, crypto, economy, etc.)
- `openbb_platform/providers/`: Data provider integrations (yfinance, FRED, FMP, etc.)
- `cli/`: Command-line interface implementation
- `desktop/`: Tauri + React desktop application

### Key Concepts
- **Extensions**: Domain-specific modules (equity, crypto, economy) that group related functionality
- **Providers**: Data source integrations that implement standardized interfaces
- **OBB Object**: Central `obb` object that provides access to all platform features
- **Standardized Data Models**: Common data structures across all providers

## Development Commands

### Environment Setup
```bash
# Activate virtual environment (if using venv/)
source venv/bin/activate

# Install for development (editable installs)
cd openbb_platform && python dev_install.py -e
```

### Using Helper Script
```bash
./openbb.sh test         # Test installation
./openbb.sh api          # Start REST API server (port 8000)
./openbb.sh shell        # Python shell with OpenBB imported
./openbb.sh build        # Rebuild platform after changes
./openbb.sh install      # Run development installation
./openbb.sh pytest       # Run unit tests (excludes integration)
```

### Testing
```bash
# Run unit tests (excludes integration tests)
pytest openbb_platform -m "not integration"

# Test specific component
pytest openbb_platform/providers/yfinance/tests/

# Run integration tests (requires API keys)
pytest openbb_platform -m "integration"

# Test installation
python test_openbb.py
```

### API Server
```bash
# Start FastAPI server
cd openbb_platform
uvicorn openbb_core.api.rest_api:app --host 0.0.0.0 --port 8000 --reload

# Server will be available at http://127.0.0.1:8000
# API docs at http://127.0.0.1:8000/docs
```

### Desktop App
```bash
cd desktop/

# Install dependencies
npm install

# Development server
npm run dev          # Runs on port 1470

# Build application
npm run build

# Run Tauri desktop app
npm run tauri dev

# Lint frontend code
npm run lint
```

### CLI
```bash
cd cli/

# Install CLI in development mode
pip install -e .

# Run CLI
openbb-cli
```

## Platform Development

### Adding New Provider
1. Create new directory in `openbb_platform/providers/`
2. Implement provider following existing patterns (see `yfinance` provider)
3. Add to `pyproject.toml` dependencies
4. Run `python dev_install.py -e` to install

### Adding New Extension
1. Create new directory in `openbb_platform/extensions/`
2. Implement extension following existing patterns (see `equity` extension)
3. Add to `pyproject.toml` dependencies
4. Run `python dev_install.py -e` to install

### After Code Changes
```bash
# Rebuild platform to reflect changes
python -c "import openbb; openbb.build()"
```

## Code Quality

### Pre-commit Hooks
The repository uses extensive pre-commit hooks:
- **Black**: Code formatting
- **Ruff**: Linting and style checks
- **MyPy**: Type checking
- **PyLint**: Additional linting
- **PyDocStyle**: Docstring style checking
- **CodeSpell**: Spell checking
- **Detect-secrets**: Security scanning

### Running Quality Checks
```bash
# Install pre-commit hooks
pre-commit install

# Run all hooks manually
pre-commit run --all-files

# Run specific hook
pre-commit run black
pre-commit run ruff
```

## Configuration

### API Keys
Configure data provider API keys in `~/.openbb_platform/user_settings.json`:
```json
{
  "credentials": {
    "fmp_api_key": "YOUR_KEY",
    "polygon_api_key": "YOUR_KEY",
    "fred_api_key": "YOUR_KEY"
  }
}
```

### Python Environment
- **Supported**: Python 3.10 - 3.13
- **Package Manager**: Poetry (for dependency management)
- **Virtual Environment**: Recommended (venv/ directory)

## Important Notes

### File Structure
- Generated files in `openbb_platform/core/openbb/package/` should not be committed (except `__init__.py`)
- Use development installation (`dev_install.py`) for local development
- Use regular pip install for production deployments

### Testing Strategy
- Unit tests exclude integration marker by default
- Integration tests require external API access and keys
- Platform rebuild required after structural changes

### Desktop Development
- Frontend: React + TypeScript + Tailwind CSS
- Backend: Rust with Tauri framework
- Build system: Vite for frontend, Cargo for Rust backend