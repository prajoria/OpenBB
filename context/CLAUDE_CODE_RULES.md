# Claude Code Development Rules & Guidelines

> **Purpose:** Comprehensive development guidelines for Claude Code sessions working on this OpenBB financial platform fork.
> **Context Folder**: `context/` - Contains all session context and knowledge base
> **Updated**: March 6, 2026

---

## 🎯 **Core Development Principles**

### **1. Privacy-First Architecture**
- **Raw financial data** stays in local MySQL (`Portfolio_Positions`, `ESPP_Plan`)
- **Synthetic data** for external APIs via `portfolio_basket` normalization
- **Never expose** true positions, dollar amounts, or share counts in logs/APIs
- **Weight-preserving transformations** maintain analytical utility while protecting PII

### **2. Documentation-Driven Development**
- **Update context documents** before major architectural changes
- **Maintain living documentation** in `context/` folder
- **Comment complex business logic** with domain explanations
- **Create design documents** for new services or major features

### **3. Microservice Architecture Standards**
- **Port allocation**: `:6901` (OpenBB), `:6902` (Portfolio), `:6903` (FinanceToolkit)
- **Service independence**: Each service has own virtualenv, config, lifecycle
- **API contracts**: RESTful endpoints with OpenBB Pro widget integration
- **HTTPS everywhere**: Self-signed certs for local development

### **4. Data Quality & Consistency**
- **Idempotent operations**: Re-runnable scripts with snapshot-based deduplication
- **Temporal tracking**: All major tables include `snapshot_date` or `created_at`
- **Type safety**: Use Pydantic models, dataclasses, proper typing
- **Validation**: Input sanitization, range checks, format validation

---

## 🏗️ **Technical Architecture Rules**

### **Database Design Standards**

#### **Schema Patterns**
```sql
-- Always include temporal tracking
CREATE TABLE example_table (
    id INT AUTO_INCREMENT PRIMARY KEY,
    -- business columns here --
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created (created_at)
);

-- Snapshot-based tables (for point-in-time data)
CREATE TABLE snapshot_table (
    snapshot_date DATETIME NOT NULL,
    -- data columns --
    INDEX idx_snapshot (snapshot_date)
);
```

#### **Persistence Strategies**
- **Portfolio_Positions**: DELETE by `snapshot_date` + INSERT (idempotent full replacement)
- **ESPP_Plan**: INSERT ... ON DUPLICATE KEY UPDATE (upsert by natural key)
- **Account_Owner**: INSERT IGNORE (accumulate accounts across imports)
- **equity_historical**: Gap detection + incremental insert (no duplicates)

### **API Design Standards**

#### **Endpoint Patterns**
```python
@app.get("/api/v1/resource")
async def get_resource(
    symbol: str = Query(..., regex="^[A-Z0-9.-]+$"),
    start_date: Optional[date] = None,
    limit: int = Query(default=100, le=1000)
) -> List[ResourceModel]:
    """
    Clear docstring with parameters and expected response.
    Include business context when relevant.
    """
```

#### **Response Formats**
- **Widget endpoints**: JSON arrays compatible with OpenBB Pro
- **Error responses**: Structured error objects with helpful messages
- **Pagination**: Limit/offset with total count when appropriate
- **Caching headers**: Appropriate TTL for different data types

### **Error Handling Standards**

#### **Exception Hierarchy**
```python
# Application-specific exceptions
class PortfolioAppError(Exception):
    """Base exception for portfolio app errors"""

class DataNotFoundError(PortfolioAppError):
    """Requested data not available"""

class ValidationError(PortfolioAppError):
    """Input validation failed"""

class ExternalAPIError(PortfolioAppError):
    """External API call failed"""
```

#### **Fallback Strategies**
- **API failures**: Graceful degradation to cached data or alternative sources
- **Database unavailable**: Return meaningful error with retry guidance
- **Partial data**: Return available data with warnings about missing portions
- **Rate limits**: Exponential backoff with clear user messaging

---

## 🔐 **Security & Privacy Guidelines**

### **API Key Management**
```python
# Priority chain for API keys
def get_api_key(key_name: str) -> str:
    """
    1. Environment variable (runtime override)
    2. .env file (development)
    3. OpenBB config (~/.openbb_platform/)
    4. Request header (per-request override)
    """
```

### **Data Sanitization Rules**
- **Log sanitization**: Never log API keys, account numbers, or dollar amounts
- **API responses**: Only expose synthetic/normalized values externally
- **Error messages**: Avoid leaking sensitive data in exception details
- **Debug output**: Use placeholder values for sensitive fields

### **CORS & Network Security**
```python
ALLOWED_ORIGINS = [
    "https://pro.openbb.co",           # Production
    "https://127.0.0.1:1420",          # Tauri desktop
    "http://localhost:3000",           # Local dev
    # Never use wildcard "*" in production
]
```

---

## 📊 **Financial Domain Standards**

### **Symbol Normalization**
```python
# Handle ticker format variations
SYMBOL_MAPPINGS = {
    "BRKB": "BRK-B",    # Fidelity → FMP format
    "BRK.B": "BRK-B",   # Alternative format
}

def normalize_symbol(symbol: str) -> str:
    """Convert symbol to FMP-compatible format"""
    return SYMBOL_MAPPINGS.get(symbol.upper(), symbol.upper())
```

### **Tax Calculation Standards**
- **ESPP calculations**: Use exact formulas from `DOMAIN_KNOWLEDGE.md`
- **Cost basis methods**: Support FIFO, LIFO, HIFO, Specific Lot
- **Holding period**: Acquisition date + 1 day starts the holding period
- **Wash sale detection**: 30-day window before and after sale dates

### **Market Data Standards**
- **Holiday handling**: Use `market_holidays` table with computed fallbacks
- **Corporate actions**: Use adjusted close prices for historical analysis
- **Gap detection**: Skip holidays and weekends in missing data analysis
- **Date ranges**: Validate against trading calendar, not just calendar dates

---

## 🧪 **Testing Standards**

### **Test Categories**
```python
# Unit tests (fast, isolated)
def test_parse_currency():
    assert parse_currency("$1,234.56") == 1234.56
    assert parse_currency("($67.89)") == -67.89

# Integration tests (database required)
@pytest.mark.integration
def test_portfolio_data_pipeline():
    # Full HTML → MySQL → API workflow

# End-to-end tests (all services running)
@pytest.mark.e2e
def test_portfolio_widget_rendering():
    # OpenBB Pro widget integration
```

### **Test Data Management**
- **Sanitized fixtures**: Use synthetic data that preserves business logic
- **Database isolation**: Each test gets clean database state
- **API mocking**: Mock external services (FMP API) for deterministic tests
- **Performance tests**: Validate response times under realistic load

---

## 📝 **Code Quality Standards**

### **Documentation Requirements**
```python
class PortfolioService:
    """
    Portfolio data service with privacy-preserving analytics.

    This service provides access to portfolio positions while ensuring
    that raw position data (true shares, dollar amounts) never leaves
    the local MySQL database. External APIs receive only synthetic
    normalized data that preserves relative weights and returns.

    Privacy Strategy:
    - Raw positions: Portfolio_Positions table (local only)
    - Synthetic data: portfolio_basket table (API accessible)
    - Weight preservation: W_i = value_i / sum(value)
    """
```

### **Type Safety Standards**
```python
from typing import Optional, List, Dict, Union
from decimal import Decimal
from datetime import date, datetime
from pydantic import BaseModel, validator

class PositionModel(BaseModel):
    symbol: str
    quantity: Decimal
    cost_basis: Decimal
    current_value: Decimal
    snapshot_date: datetime

    @validator('symbol')
    def symbol_format(cls, v):
        return v.upper().strip()
```

### **Error Context Standards**
```python
try:
    result = risky_operation()
except ExternalAPIError as e:
    logger.error(
        "FMP API call failed",
        extra={
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "error_code": e.code,
            "retry_after": e.retry_after
        }
    )
    raise
```

---

## 🔄 **Workflow Standards**

### **Git Branch Strategy**
- **Main branch**: `openbb_learning` (our primary development branch)
- **Feature branches**: `feature/descriptive-name` from `openbb_learning`
- **Commit messages**: Follow conventional commits format
- **Upstream sync**: Periodically merge from `OpenBB-finance/OpenBB:main`

### **Commit Message Format**
```
type(scope): brief description

- Detailed change explanation
- Business context when relevant
- Breaking changes noted

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

### **Session Workflow**
1. **Load context**: Review recent changes and current objectives
2. **Plan phase**: Use plan mode for complex implementations
3. **Implementation**: Follow TDD where appropriate
4. **Documentation**: Update relevant context files
5. **Validation**: Test critical paths before commit
6. **Commit & push**: Descriptive messages with co-authorship

---

## 🎯 **Research Framework Standards**

### **7-Phase Analysis Implementation**
```python
# Phase gates with clear success criteria
PHASE_GATES = {
    "Phase 1": "Business understanding complete, no fatal risks",
    "Phase 2": "Weighted fundamentals score >= 3.5/5.0",
    "Phase 3": ">= 4/6 bullish technical conditions",
    "Phase 4": "Margin of safety calculation complete",
    "Phase 5": "Position fits portfolio risk budget",
    "Phase 6": "Relative score >= 3.5 vs peers/ETF",
    "Phase 7": "Final decision with monitoring triggers"
}
```

### **KPI Standardization**
- **Business Quality**: Concentration, ownership, revisions, geographic exposure
- **Fundamentals**: Growth (revenue/EPS/FCF), profitability (margins/ROIC), balance sheet
- **Technical**: Trend (SMA/ADX), momentum (RSI/MACD), volatility (ATR/Bollinger)
- **Valuation**: P/E, EV/EBITDA, DCF, Piotroski, Altman Z-Score
- **Risk**: Sharpe/Sortino/Alpha, VaR/CVaR, Max Drawdown, Beta
- **Relative**: Peer ranking, ETF outperformance, rolling relative strength

### **Reproducible Workflow Standards**
```python
# Standard environment setup for analysis notebooks
import os
import sys
from pathlib import Path

# Project root discovery
PROJECT_ROOT = Path.cwd()
while not (PROJECT_ROOT / "openbb_platform").exists():
    PROJECT_ROOT = PROJECT_ROOT.parent

# Add to sys.path for imports
sys.path.insert(0, str(PROJECT_ROOT))

# Standard imports
from openbb import obb
from financetoolkit import Toolkit
import pandas as pd
import numpy as np
```

---

## 🚀 **Performance Standards**

### **Response Time Targets**
- **Widget endpoints**: < 500ms (95th percentile, cached data)
- **Cold data fetch**: < 10s (95th percentile, 5 tickers, 5 years)
- **Database queries**: < 100ms (95th percentile, single table)
- **Portfolio app startup**: < 30s (including MySQL connection)

### **Caching Strategy**
```python
# Multi-layer caching approach
class CacheManager:
    """
    Layer 1: In-memory LRU cache (session objects)
    Layer 2: Database cache (FMP responses)
    Layer 3: Response cache (serialized JSON)
    """

    def get_cached_data(self, key: str) -> Optional[Any]:
        # Check layers in order, populate upstream on hit
        pass
```

### **Resource Management**
- **Memory usage**: Monitor DataFrame sizes, implement pagination for large datasets
- **Database connections**: Connection pooling, proper cleanup in finally blocks
- **API rate limits**: Token bucket algorithm, respect provider limits
- **Concurrent requests**: Reasonable limits, backpressure mechanisms

---

## 📋 **Operational Standards**

### **Monitoring & Observability**
```python
import logging
import structlog

# Structured logging with context
logger = structlog.get_logger(__name__)

logger.info(
    "Portfolio data updated",
    symbol_count=len(symbols),
    account_count=len(accounts),
    snapshot_date=snapshot_date.isoformat(),
    duration_ms=duration
)
```

### **Health Checks**
```python
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "database": await check_database_connection(),
        "external_apis": await check_external_apis(),
        "cache_status": get_cache_statistics(),
        "version": __version__
    }
```

### **Configuration Management**
```python
# Environment-specific configuration
class Settings(BaseModel):
    database_url: str = Field(..., env="DATABASE_URL")
    fmp_api_key: str = Field(..., env="FMP_API_KEY")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    cache_ttl_seconds: int = Field(3600, env="CACHE_TTL")

    class Config:
        env_file = ".env"
```

---

## ⚠️ **Known Issues & Workarounds**

### **Platform-Specific Issues**
- **Windows aiohttp bug**: Use sync `requests` library, avoid aiohttp on Windows Python 3.12
- **Encoding issues**: Call `sys.stdout.reconfigure(encoding="utf-8")` for Unicode output
- **Path separators**: Use `pathlib.Path` instead of string concatenation

### **Data Quality Issues**
- **BRKB symbol mapping**: Portfolio stores `BRKB`, FMP expects `BRK-B`
- **Holiday edge cases**: Some special closures not in computed holidays
- **Currency parsing**: Handle various formats: `$1,234.56`, `($67.89)`, `--`

### **Performance Bottlenecks**
- **Toolkit instantiation**: 5-15s for new instances, cache aggressively
- **Large DataFrame serialization**: Implement streaming/pagination
- **MySQL query optimization**: Add appropriate indexes for common queries

---

## 🔄 **Future Roadmap Priorities**

### **Immediate (Q1 2026)**
1. Complete FinanceToolkit service implementation (`:6903`)
2. Implement comprehensive test suite
3. Add monitoring and alerting infrastructure
4. Create automated backup strategies

### **Medium-term (Q2 2026)**
1. Advanced portfolio optimization algorithms
2. Tax-optimized rebalancing with wash sale detection
3. Risk metrics and performance attribution
4. Real-time data integration

### **Long-term (Q3-Q4 2026)**
1. Multi-user platform with role-based access
2. Machine learning prediction models
3. Regulatory compliance features
4. Institutional-grade risk management

---

**These rules ensure consistent, high-quality development while maintaining the privacy-first, production-ready architecture that makes this platform unique in the financial engineering space.**

*Document maintained by development team | Updated each major release*