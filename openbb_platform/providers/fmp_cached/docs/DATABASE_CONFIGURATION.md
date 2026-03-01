# FMP Cached Provider - Database Configuration

## Environment Variables

The FMP Cached Provider supports several environment variables to control its behavior:

### FMP_CACHE_AUTO_CREATE_DB

Controls whether the database and tables are automatically created.

**Values:**
- `true` - Automatically create database and tables if they don't exist
- `false` (default) - Skip database/table creation, use existing database

**Usage:**

```bash
# Enable automatic creation (default behavior)
export FMP_CACHE_AUTO_CREATE_DB=true

# Disable automatic creation (use existing database)
export FMP_CACHE_AUTO_CREATE_DB=false
```

**In Python/Notebook:**

```python
import os

# Enable automatic database creation
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'true'

# Disable automatic database creation
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
```

**Programmatic Control:**

You can also control this behavior programmatically when calling `init_database()`:

```python
from openbb_fmp_cached.utils.database import init_database

# Force auto-create regardless of environment variable
init_database(auto_create=True)

# Skip auto-create regardless of environment variable
init_database(auto_create=False)

# Use environment variable setting (default)
init_database()  # or init_database(auto_create=None)
```

### FMP_CACHE_TEST_MODE

Controls whether to use test database and table prefixes.

**Values:**
- `true` - Use test database (`openbb_fmp_cache_test`) and prefix tables with `test_`
- `false` (default) - Use production database (`openbb_fmp_cache`)

**Usage:**

```bash
export FMP_CACHE_TEST_MODE=true
```

**In Python/Notebook:**

```python
import os
os.environ['FMP_CACHE_TEST_MODE'] = 'false'
```

## Use Cases

### Development/Testing Environment

When developing or testing, you typically want automatic database creation enabled:

```python
import os
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'true'
os.environ['FMP_CACHE_TEST_MODE'] = 'true'
```

### Production Environment

In production, you may want to use a pre-created database with proper permissions:

```python
import os
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
os.environ['FMP_CACHE_TEST_MODE'] = 'false'
```

### Jupyter Notebooks

For notebooks, set at the beginning of your notebook:

```python
import os

# Use existing production database
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
os.environ['FMP_CACHE_TEST_MODE'] = 'false'

from financetoolkit import Toolkit

# Your code here...
```

### CI/CD Pipeline

In automated testing:

```bash
#!/bin/bash
export FMP_CACHE_AUTO_CREATE_DB=true
export FMP_CACHE_TEST_MODE=true
pytest tests/
```

## Database Setup

### Option 1: Automatic Creation (Default)

The provider will automatically:
1. Create the database if it doesn't exist
2. Create all required tables
3. Set up indexes for optimal performance

No manual setup required - just ensure MySQL is running and credentials are configured.

### Option 2: Manual Creation (Production)

For production environments, you may want to manually create the database:

```sql
-- Create database
CREATE DATABASE IF NOT EXISTS openbb_fmp_cache
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Create user with appropriate permissions
CREATE USER IF NOT EXISTS 'fmp_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON openbb_fmp_cache.* TO 'fmp_user'@'localhost';
FLUSH PRIVILEGES;
```

Then disable automatic creation:

```python
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
```

The tables will still be created automatically on first use, but you can also run the schema setup script manually if preferred.

## Troubleshooting

### Database Already Exists Error

If you get errors about the database already existing, set:

```python
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
```

### Permission Denied

If you get permission errors when auto-creating:

1. Ensure your MySQL user has `CREATE DATABASE` privilege, or
2. Manually create the database and set `FMP_CACHE_AUTO_CREATE_DB=false`

### Table Not Found

If you get "table not found" errors with `FMP_CACHE_AUTO_CREATE_DB=false`:

1. Ensure tables exist in the database
2. Run database initialization manually:
   ```python
   from openbb_fmp_cached.utils.database import init_database
   init_database(auto_create=True)
   ```
3. Or set `FMP_CACHE_AUTO_CREATE_DB=true` temporarily

## Best Practices

1. **Development**: Use `FMP_CACHE_AUTO_CREATE_DB=true` with `FMP_CACHE_TEST_MODE=true`
2. **Production**: Use `FMP_CACHE_AUTO_CREATE_DB=false` with manually created database
3. **Testing**: Always use `FMP_CACHE_TEST_MODE=true` to avoid affecting production data
4. **Notebooks**: Set environment variables at the top of your notebook for clarity
