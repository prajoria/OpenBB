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

## 🔍 **Data Validation & Integrity Standards**

### **Financial Data Validation Rules**
```python
def validate_financial_data(df: pd.DataFrame, data_type: str) -> bool:
    """
    Comprehensive validation for financial datasets.
    """
    # Required columns check
    required_fields = {
        "equity_historical": ["symbol", "date", "close", "volume"],
        "portfolio_positions": ["symbol", "quantity", "cost_basis", "current_value"],
        "espp_plan": ["purchase_date", "quantity", "purchase_price", "discount_pct"]
    }

    # Range validation
    if data_type == "equity_historical":
        assert df["close"].between(0.01, 10000).all(), "Close prices out of range"
        assert df["volume"].ge(0).all(), "Negative volume detected"

    # Date validation
    if "date" in df.columns:
        assert df["date"].dt.year.between(1900, 2030).all(), "Invalid date range"

    return True
```

### **Database Integrity Checks**
```python
# Required validation queries after data insertion
INTEGRITY_CHECKS = {
    "Portfolio_Positions": """
        SELECT COUNT(*) as orphaned_positions
        FROM Portfolio_Positions pp
        LEFT JOIN Account_Owner ao ON pp.account = ao.account_name
        WHERE ao.account_name IS NULL
    """,

    "equity_historical": """
        SELECT symbol, COUNT(*) as row_count,
               MIN(date) as earliest, MAX(date) as latest
        FROM equity_historical
        GROUP BY symbol
        HAVING COUNT(*) < 5 OR DATEDIFF(MAX(date), MIN(date)) < 30
    """,

    "portfolio_basket": """
        SELECT snapshot_date,
               ABS(SUM(portfolio_weight_pct) - 100) as weight_error
        FROM portfolio_basket
        GROUP BY snapshot_date
        HAVING ABS(SUM(portfolio_weight_pct) - 100) > 0.1
    """
}
```

### **Input Sanitization Standards**
```python
def sanitize_sql_inputs(query_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize all SQL query parameters to prevent injection.
    """
    sanitized = {}
    for key, value in query_params.items():
        if isinstance(value, str):
            # Remove SQL keywords and dangerous characters
            sanitized[key] = re.sub(r'[;\'\"\\]', '', value)[:255]
        elif isinstance(value, (int, float)):
            sanitized[key] = max(-999999999, min(999999999, value))
        else:
            sanitized[key] = str(value)[:255]
    return sanitized
```

---

## 🚨 **Security & Access Control Standards**

### **API Authentication Rules**
```python
# Required security headers for all endpoints
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'"
}

# API key validation pattern
def validate_api_key(api_key: str, endpoint: str) -> bool:
    """
    Multi-layer API key validation with rate limiting.
    """
    # Key format validation
    if not re.match(r'^[a-zA-Z0-9]{32,128}$', api_key):
        return False

    # Rate limiting check
    if is_rate_limited(api_key, endpoint):
        raise HTTPException(429, "Rate limit exceeded")

    # Key existence and permissions
    return validate_key_permissions(api_key, endpoint)
```

### **Data Access Control Rules**
```python
# Strict table access permissions
TABLE_ACCESS_RULES = {
    "Portfolio_Positions": {
        "allowed_contexts": ["local_script", "admin_tool"],
        "forbidden_contexts": ["api_endpoint", "widget", "external_service"],
        "reason": "Contains PII - raw positions and dollar amounts"
    },

    "portfolio_basket": {
        "allowed_contexts": ["api_endpoint", "widget", "external_service"],
        "data_rules": ["synthetic_only", "no_pii", "weight_normalized"],
        "validation_required": True
    },

    "ESPP_Plan": {
        "allowed_contexts": ["local_script", "tax_calculation"],
        "forbidden_contexts": ["api_endpoint", "external_service"],
        "reason": "Contains personal tax information"
    }
}
```

### **Audit Trail Requirements**
```python
# Required audit logging for sensitive operations
@audit_log(level="CRITICAL", table="Portfolio_Positions")
def modify_portfolio_data(operation: str, affected_rows: int):
    """
    All portfolio data modifications must be logged.
    """
    log_entry = {
        "timestamp": datetime.utcnow(),
        "operation": operation,
        "affected_rows": affected_rows,
        "user_context": get_current_user_context(),
        "source_ip": get_client_ip(),
        "success": True
    }
    audit_logger.critical(json.dumps(log_entry))
```

---

## 📊 **Financial Calculation Safety Standards**

### **Precision & Rounding Rules**
```python
from decimal import Decimal, ROUND_HALF_UP

# Required precision for financial calculations
FINANCIAL_PRECISION = {
    "currency_amounts": 2,      # $123.45
    "share_quantities": 6,      # 123.456789 shares
    "percentages": 4,           # 12.3456%
    "ratios": 6,               # 1.234567
    "weights": 4                # 0.1234 (12.34%)
}

def safe_financial_calculation(amount: Decimal, operation: str) -> Decimal:
    """
    All financial calculations must use Decimal with proper rounding.
    """
    if operation in ["currency", "gain_loss"]:
        return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    elif operation == "percentage":
        return amount.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    return amount
```

### **Tax Calculation Validation Rules**
```python
def validate_espp_calculations(espp_data: Dict[str, Any]) -> bool:
    """
    Validate ESPP tax calculations against IRS requirements.
    """
    # Bargain element validation
    bargain_element = (espp_data["fmv_purchase"] - espp_data["purchase_price"]) * espp_data["quantity"]
    assert abs(bargain_element - espp_data["bargain_element"]) < 0.01, "Bargain element miscalculated"

    # Discount percentage validation
    expected_discount = ((espp_data["fmv_start"] - espp_data["purchase_price"]) / espp_data["fmv_start"]) * 100
    assert abs(expected_discount - espp_data["discount_pct"]) < 0.01, "Discount percentage incorrect"

    # Qualified disposition date validation
    qual_date = max(
        espp_data["offering_start"] + relativedelta(years=2),
        espp_data["purchase_date"] + relativedelta(years=1)
    )
    assert qual_date == espp_data["qualified_disposition_date"], "Qualified disposition date incorrect"

    return True
```

### **Portfolio Math Validation**
```python
def validate_portfolio_math(positions: List[Dict]) -> bool:
    """
    Ensure portfolio-level calculations are mathematically consistent.
    """
    total_value = sum(pos["current_value"] for pos in positions)
    total_cost = sum(pos["cost_basis"] for pos in positions)
    total_gain_loss = sum(pos["gain_loss"] for pos in positions)

    # Verify gain/loss calculation
    assert abs((total_value - total_cost) - total_gain_loss) < 0.01, "Portfolio gain/loss mismatch"

    # Verify weight calculations
    for pos in positions:
        expected_weight = (pos["current_value"] / total_value) * 100
        assert abs(expected_weight - pos["weight_pct"]) < 0.001, f"Weight calculation error for {pos['symbol']}"

    # Verify weights sum to 100%
    total_weights = sum(pos["weight_pct"] for pos in positions)
    assert abs(total_weights - 100.0) < 0.01, "Portfolio weights don't sum to 100%"

    return True
```

---

## 🎯 **API Design & Response Safety Standards**

### **Response Format Standardization**
```python
# Standard API response wrapper
class APIResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Privacy validation for all responses
    @validator('data')
    def validate_no_pii_in_response(cls, v):
        if isinstance(v, (dict, list)):
            forbidden_fields = ["account_number", "ssn", "true_shares", "actual_dollars"]
            if any(field in str(v).lower() for field in forbidden_fields):
                raise ValueError("PII detected in API response")
        return v
```

### **Rate Limiting Safety Rules**
```python
# Multi-tier rate limiting
RATE_LIMITS = {
    "portfolio_endpoints": {
        "requests_per_minute": 60,
        "requests_per_hour": 1000,
        "burst_allowance": 10
    },
    "market_data_endpoints": {
        "requests_per_minute": 300,
        "requests_per_hour": 5000,
        "burst_allowance": 50
    },
    "admin_endpoints": {
        "requests_per_minute": 10,
        "requests_per_hour": 100,
        "burst_allowance": 2
    }
}

@rate_limit("portfolio_endpoints")
async def get_portfolio_data(request: Request):
    # Implementation with automatic rate limiting
    pass
```

### **Request Validation Standards**
```python
# Comprehensive request validation
class PortfolioRequestValidator:
    @staticmethod
    def validate_symbol_list(symbols: List[str]) -> List[str]:
        """Validate and sanitize symbol inputs."""
        validated = []
        for symbol in symbols[:50]:  # Max 50 symbols per request
            clean_symbol = re.sub(r'[^A-Z0-9.-]', '', symbol.upper())
            if len(clean_symbol) >= 1 and len(clean_symbol) <= 10:
                validated.append(clean_symbol)
        return validated

    @staticmethod
    def validate_date_range(start_date: str, end_date: str) -> Tuple[date, date]:
        """Validate date ranges with business logic."""
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Maximum 10 years of data
        assert (end - start).days <= 3650, "Date range exceeds 10 years"
        assert start >= date(1990, 1, 1), "Start date too far in past"
        assert end <= date.today(), "End date cannot be in future"

        return start, end
```

---

## 🔧 **Infrastructure & Monitoring Safety Standards**

### **Database Connection Safety**
```python
# Connection pooling with safety limits
DATABASE_CONFIG = {
    "max_connections": 20,
    "min_connections": 5,
    "connection_timeout": 30,
    "statement_timeout": 300,
    "idle_timeout": 3600,
    "retry_attempts": 3,
    "retry_delay": 1.0
}

class SafeDatabaseManager:
    @retry(max_attempts=3, delay=1.0)
    async def execute_query(self, query: str, params: Dict) -> Any:
        """Execute query with automatic retry and timeout."""
        sanitized_params = sanitize_sql_inputs(params)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    result = await asyncio.wait_for(
                        conn.fetch(query, **sanitized_params),
                        timeout=DATABASE_CONFIG["statement_timeout"]
                    )
                    return result
                except asyncio.TimeoutError:
                    logger.error("Query timeout", extra={"query": query[:100]})
                    raise
```

### **Memory & Resource Monitoring**
```python
# Resource monitoring thresholds
RESOURCE_LIMITS = {
    "max_memory_mb": 2048,          # Per process
    "max_dataframe_rows": 1000000,   # Per DataFrame
    "max_concurrent_requests": 50,   # Per endpoint
    "max_file_size_mb": 100,        # Upload limit
    "max_query_result_rows": 100000  # Database query limit
}

@monitor_resource_usage
def process_large_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Monitor memory usage during DataFrame processing."""
    if len(df) > RESOURCE_LIMITS["max_dataframe_rows"]:
        raise ValueError(f"DataFrame too large: {len(df)} rows")

    memory_usage = df.memory_usage(deep=True).sum() / 1024**2  # MB
    if memory_usage > RESOURCE_LIMITS["max_memory_mb"] / 2:
        logger.warning(f"High memory usage: {memory_usage:.1f}MB")

    return df
```

### **Application Health Monitoring**
```python
# Comprehensive health check system
class HealthMonitor:
    @staticmethod
    async def check_system_health() -> Dict[str, Any]:
        """Comprehensive system health validation."""
        health_status = {
            "timestamp": datetime.utcnow(),
            "status": "healthy",
            "checks": {}
        }

        # Database connectivity
        try:
            await check_database_connection()
            health_status["checks"]["database"] = "healthy"
        except Exception as e:
            health_status["checks"]["database"] = f"unhealthy: {str(e)}"
            health_status["status"] = "degraded"

        # External API availability
        try:
            await check_fmp_api_health()
            health_status["checks"]["fmp_api"] = "healthy"
        except Exception as e:
            health_status["checks"]["fmp_api"] = f"unhealthy: {str(e)}"

        # Memory usage
        memory_usage = psutil.Process().memory_info().rss / 1024**2
        health_status["checks"]["memory_mb"] = memory_usage
        if memory_usage > RESOURCE_LIMITS["max_memory_mb"]:
            health_status["status"] = "degraded"

        # Data freshness
        latest_data_age = await check_latest_data_age()
        health_status["checks"]["data_freshness_hours"] = latest_data_age
        if latest_data_age > 24:
            health_status["status"] = "degraded"

        return health_status
```

---

## 🚀 **Deployment & Environment Safety Standards**

### **Environment Configuration Validation**
```python
# Required environment validation on startup
REQUIRED_ENV_VARS = {
    "DATABASE_URL": {"pattern": r"mysql://.*", "sensitive": True},
    "FMP_API_KEY": {"pattern": r"^[a-zA-Z0-9]{32,}$", "sensitive": True},
    "ENVIRONMENT": {"values": ["development", "staging", "production"], "sensitive": False},
    "LOG_LEVEL": {"values": ["DEBUG", "INFO", "WARNING", "ERROR"], "sensitive": False},
    "ALLOWED_ORIGINS": {"pattern": r"https?://.*", "sensitive": False}
}

def validate_environment() -> bool:
    """Validate all required environment variables on startup."""
    missing_vars = []
    invalid_vars = []

    for var_name, config in REQUIRED_ENV_VARS.items():
        value = os.getenv(var_name)

        if value is None:
            missing_vars.append(var_name)
            continue

        # Pattern validation
        if "pattern" in config and not re.match(config["pattern"], value):
            invalid_vars.append(var_name)

        # Value validation
        if "values" in config and value not in config["values"]:
            invalid_vars.append(var_name)

    if missing_vars or invalid_vars:
        error_msg = f"Environment validation failed. Missing: {missing_vars}, Invalid: {invalid_vars}"
        logger.critical(error_msg)
        raise EnvironmentError(error_msg)

    return True
```

### **Secrets Management Rules**
```python
# Secure secrets handling patterns
class SecretsManager:
    @staticmethod
    def get_database_credentials() -> Dict[str, str]:
        """Retrieve database credentials with fallback chain."""
        # Priority: 1. Environment, 2. OpenBB config, 3. Local .env
        db_url = (
            os.getenv("DATABASE_URL") or
            get_openbb_config_value("database_url") or
            load_env_file_value("DATABASE_URL")
        )

        if not db_url:
            raise ValueError("No database credentials found in any source")

        # Never log the actual credential
        logger.info("Database credentials loaded", extra={
            "source": "environment" if os.getenv("DATABASE_URL") else "config"
        })

        return parse_database_url(db_url)

    @staticmethod
    def rotate_api_keys() -> bool:
        """API key rotation validation and logging."""
        # Validate new keys work before rotation
        # Log rotation events for audit trail
        # Never expose keys in logs
        pass
```

### **Backup & Recovery Safety Standards**
```python
# Required backup validation
BACKUP_REQUIREMENTS = {
    "portfolio_positions": {
        "frequency": "daily",
        "retention_days": 90,
        "validation_required": True,
        "encryption_required": True
    },
    "espp_plan": {
        "frequency": "weekly",
        "retention_days": 365,
        "validation_required": True,
        "encryption_required": True
    },
    "equity_historical": {
        "frequency": "weekly",
        "retention_days": 30,
        "validation_required": False,
        "encryption_required": False
    }
}

def validate_backup_integrity(backup_path: str, table_name: str) -> bool:
    """Validate backup file integrity and completeness."""
    # File size validation
    backup_size = os.path.getsize(backup_path)
    if backup_size == 0:
        raise ValueError(f"Empty backup file: {backup_path}")

    # Row count validation
    if BACKUP_REQUIREMENTS[table_name]["validation_required"]:
        backup_rows = count_rows_in_backup(backup_path)
        current_rows = count_rows_in_table(table_name)

        if abs(backup_rows - current_rows) > current_rows * 0.1:  # 10% tolerance
            raise ValueError(f"Backup row count mismatch: {backup_rows} vs {current_rows}")

    return True
```

### **Disaster Recovery Procedures**
```python
# Disaster recovery validation checklist
DISASTER_RECOVERY_CHECKLIST = [
    "database_connectivity_restored",
    "api_keys_validated",
    "data_integrity_verified",
    "backup_restoration_tested",
    "monitoring_systems_active",
    "performance_benchmarks_met",
    "security_scanning_completed"
]

def validate_disaster_recovery() -> Dict[str, bool]:
    """Validate all disaster recovery requirements are met."""
    recovery_status = {}

    for check in DISASTER_RECOVERY_CHECKLIST:
        try:
            if check == "database_connectivity_restored":
                result = test_database_connection()
            elif check == "api_keys_validated":
                result = validate_all_api_keys()
            elif check == "data_integrity_verified":
                result = run_data_integrity_checks()
            # Add more checks...

            recovery_status[check] = result
        except Exception as e:
            logger.error(f"Recovery check failed: {check}", extra={"error": str(e)})
            recovery_status[check] = False

    return recovery_status
```

---

## 📈 **Performance Optimization Safety Standards**

### **Query Performance Safety Rules**
```python
# Required query optimization patterns
QUERY_PERFORMANCE_LIMITS = {
    "max_execution_time_ms": 5000,      # 5 seconds
    "max_rows_scanned": 1000000,        # 1M rows
    "max_memory_usage_mb": 512,         # 512MB
    "max_concurrent_queries": 10        # Per connection
}

@query_monitor
def execute_optimized_query(query: str, params: Dict) -> pd.DataFrame:
    """Execute query with performance monitoring and limits."""
    start_time = time.time()

    # Add LIMIT clause if missing for safety
    if "LIMIT" not in query.upper() and "SELECT" in query.upper():
        query += " LIMIT 100000"

    # Execute with monitoring
    result = execute_query(query, params)

    # Performance validation
    execution_time_ms = (time.time() - start_time) * 1000
    if execution_time_ms > QUERY_PERFORMANCE_LIMITS["max_execution_time_ms"]:
        logger.warning(f"Slow query detected: {execution_time_ms:.0f}ms",
                      extra={"query": query[:100]})

    return result
```

### **Cache Performance Safety**
```python
# Multi-layer cache performance monitoring
class CachePerformanceMonitor:
    def __init__(self):
        self.hit_rates = {}
        self.response_times = {}

    def track_cache_performance(self, cache_layer: str, hit: bool, response_time_ms: float):
        """Track cache performance metrics."""
        if cache_layer not in self.hit_rates:
            self.hit_rates[cache_layer] = {"hits": 0, "misses": 0}
            self.response_times[cache_layer] = []

        if hit:
            self.hit_rates[cache_layer]["hits"] += 1
        else:
            self.hit_rates[cache_layer]["misses"] += 1

        self.response_times[cache_layer].append(response_time_ms)

        # Alert on poor cache performance
        total_requests = self.hit_rates[cache_layer]["hits"] + self.hit_rates[cache_layer]["misses"]
        if total_requests > 100:  # Minimum sample size
            hit_rate = self.hit_rates[cache_layer]["hits"] / total_requests
            if hit_rate < 0.7:  # 70% minimum hit rate
                logger.warning(f"Low cache hit rate: {hit_rate:.1%} for {cache_layer}")
```

### **Memory Management Safety**
```python
# DataFrame memory safety patterns
def safe_dataframe_operations(df: pd.DataFrame, operation: str) -> pd.DataFrame:
    """Perform DataFrame operations with memory monitoring."""
    initial_memory = df.memory_usage(deep=True).sum()

    # Memory-efficient operations
    if operation == "groupby_large":
        # Use chunking for large groupby operations
        chunk_size = min(10000, len(df) // 10)
        results = []
        for chunk in pd.read_csv(df, chunksize=chunk_size):
            results.append(chunk.groupby("symbol").agg({"value": "sum"}))
        return pd.concat(results).groupby(level=0).sum()

    elif operation == "merge_large":
        # Use efficient merge strategies
        return df.merge(other_df, how="inner", sort=False)

    # Monitor memory growth
    final_memory = df.memory_usage(deep=True).sum()
    memory_growth = final_memory - initial_memory

    if memory_growth > 100 * 1024**2:  # 100MB growth
        logger.warning(f"High memory growth in {operation}: {memory_growth/1024**2:.1f}MB")

    return df
```

---

## 🔐 **Advanced Security Safety Standards**

### **Input Validation & XSS Prevention**
```python
# Comprehensive input sanitization
class SecurityValidator:
    @staticmethod
    def sanitize_user_input(user_input: str, input_type: str) -> str:
        """Sanitize user input based on expected type."""
        if input_type == "symbol":
            # Stock symbols: alphanumeric, dots, dashes only
            return re.sub(r'[^A-Z0-9.-]', '', user_input.upper())[:10]

        elif input_type == "account_name":
            # Account names: alphanumeric, spaces, basic punctuation
            sanitized = re.sub(r'[<>"\'/\\&]', '', user_input)
            return sanitized.strip()[:50]

        elif input_type == "date_string":
            # Dates: strict ISO format only
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', user_input):
                raise ValueError("Invalid date format")
            return user_input

        elif input_type == "numeric":
            # Numbers: remove non-numeric except decimal point
            sanitized = re.sub(r'[^0-9.-]', '', user_input)
            try:
                float(sanitized)
                return sanitized
            except ValueError:
                raise ValueError("Invalid numeric input")

        return ""

    @staticmethod
    def validate_file_upload(file_content: bytes, allowed_extensions: List[str]) -> bool:
        """Validate uploaded file safety."""
        # File size limit
        if len(file_content) > 10 * 1024**2:  # 10MB
            raise ValueError("File too large")

        # File type validation (magic bytes)
        file_type = magic.from_buffer(file_content, mime=True)
        allowed_types = {
            ".csv": "text/csv",
            ".tsv": "text/tab-separated-values",
            ".html": "text/html"
        }

        # Extension validation
        # Content validation
        # Malware scanning hook
        return True
```

### **API Authentication & Authorization**
```python
# Multi-factor authentication for sensitive operations
class AuthenticationManager:
    @staticmethod
    async def validate_request_auth(request: Request, required_scope: str) -> bool:
        """Validate request authentication and authorization."""
        # Extract authentication token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(401, "Missing or invalid authorization header")

        token = auth_header[7:]  # Remove "Bearer "

        # Token validation
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("sub")
            scopes = payload.get("scopes", [])

            # Scope validation
            if required_scope not in scopes:
                raise HTTPException(403, f"Insufficient permissions for {required_scope}")

            # Rate limiting per user
            if await is_user_rate_limited(user_id):
                raise HTTPException(429, "User rate limit exceeded")

            return True

        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid token")

    @staticmethod
    def audit_sensitive_operation(operation: str, user_id: str, affected_data: str):
        """Audit trail for sensitive operations."""
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "operation": operation,
            "user_id": user_id,
            "affected_data": affected_data,
            "ip_address": get_client_ip(),
            "user_agent": get_user_agent()
        }

        # Secure audit logging
        audit_logger.info(json.dumps(audit_entry))

        # Real-time alerting for critical operations
        if operation in ["delete_portfolio", "export_pii", "modify_tax_data"]:
            send_security_alert(audit_entry)
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