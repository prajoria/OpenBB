# OpenBB FMP Cached Provider

FMP Cached extension for OpenBB with MySQL caching support.

## Overview

This provider extends the standard FMP (Financial Modeling Prep) provider
with MySQL-based caching capabilities to improve performance and reduce
API calls.

## Features

- MySQL database caching for FMP data
- Async database operations with aiomysql
- SQLAlchemy ORM support
- Compatible with OpenBB Platform v4.6.0+

## Requirements

- Python 3.10+
- **MySQL 8.0+ database server** (see setup below)
- OpenBB Core and FMP provider
- aiomysql, sqlalchemy dependencies (installed via `dev_install.py -e`)

## MySQL setup (first-time developer)

The tests + runtime require a live MySQL server. Without one, every
`fmp_cached` test fails with `ConnectionRefusedError [WinError 10061]`
or `pymysql.err.OperationalError: (2003, "Can't connect...")`.

### 1. Install MySQL

**Windows** (via winget):

```powershell
winget install Oracle.MySQL
# Default install path: C:\Program Files\MySQL\MySQL Server 8.4\
# Default data dir:     C:\ProgramData\MySQL\MySQL Server 8.4\
```

**macOS**: `brew install mysql`
**Linux**: `apt install mysql-server` / `yum install mysql-server`

### 2. Ensure MySQL is running

**Windows** — check if the service is registered:

```powershell
Get-Service -Name "MySQL*"
# If empty, the service was never registered. Register it (needs admin):
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe" --install MySQL84 `
    --defaults-file="C:\ProgramData\MySQL\MySQL Server 8.4\my.ini"
Start-Service MySQL84
```

For a **one-shot session start** without registering a service (no admin
needed), run mysqld directly in the background:

```powershell
Start-Process -NoNewWindow -FilePath "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe" `
    -ArgumentList '--defaults-file="C:\ProgramData\MySQL\MySQL Server 8.4\my.ini"', '--console'
```

**macOS/Linux**: `sudo systemctl start mysql` or `brew services start mysql`

### 3. Verify the connection

```bash
.venv_win/Scripts/python.exe -c "
import pymysql
c = pymysql.connect(host='localhost', port=3306, user='fmp_user', password='<your-password>', connect_timeout=3)
print(f'MySQL connected: {c.get_server_info()}')
"
```

Expected output: `MySQL connected: 8.4.9` (or similar).

### 4. Configure credentials

Two config sources — both must agree. The provider reads `user_settings.json`
first and falls back to `.env`:

**`~/.openbb_platform/user_settings.json`:**

```json
{
  "credentials": {
    "mysql_host": "localhost",
    "mysql_port": 3306,
    "mysql_user": "fmp_user",
    "mysql_password": "<password>",
    "mysql_database": "openbb_fmp_cache_test",
    "fmp_api_key": "<your fmp api key>",
    "fmp_cached_api_key": "<your fmp cached api key>"
  }
}
```

**`<repo-root>/.env`** (optional, mirror of the above for scripts that
use `python-dotenv`):

```dotenv
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=fmp_user
MYSQL_PASSWORD=<password>
MYSQL_DATABASE=openbb_fmp_cache
MYSQL_TEST_DATABASE=openbb_fmp_cache_test
```

Both files are `.gitignore`d — never commit them.

### 5. Create databases + schema

```bash
# Creates openbb_fmp_cache + openbb_fmp_cache_test databases
# and populates the 83 cache tables
PYTHONIOENCODING=utf-8 .venv_win/Scripts/python.exe \
    openbb_platform/providers/fmp_cached/setup_database.py

# NOTE: the setup script has a known bug (create_cache_tables awaits a
# sync function, throwing 'object bool can't be used in await'). If you
# hit that error, run the sync equivalent directly:
.venv_win/Scripts/python.exe -c "
import sys; sys.path.insert(0, 'openbb_platform/providers/fmp_cached')
from openbb_fmp_cached.utils.database import init_database
from openbb_fmp_cached.utils.cache_schema import create_all_flattened_tables
init_database()
result = create_all_flattened_tables()
print(f'created/verified {len(result)} tables')
"
```

### 6. Verify tests can run

```bash
.venv_win/Scripts/python.exe -m pytest \
    openbb_platform/providers/fmp_cached/tests \
    -m "not integration" --no-header -q --tb=no
```

You should see `<N> passed, <N> failed` output — NOT a wall of
`ConnectionRefusedError`. If everything's connection-refused, MySQL
isn't running (go back to step 2).

## Installation

This provider is installed as part of the OpenBB development environment
setup. From the repo root:

```bash
python openbb_platform/dev_install.py -e
```

## Configuration

Configure your MySQL connection and FMP API keys in the OpenBB user
settings — see the "MySQL setup" section above.

## Troubleshooting

**All fmp_cached tests fail with `ConnectionRefusedError [WinError 10061]`**
→ MySQL isn't running. Go to step 2 of the MySQL setup section above.

**`Table 'openbb_fmp_cache_test.ttl_cache' doesn't exist`**
→ Schema isn't synced. Run step 5 (`init_database + create_all_flattened_tables`).

**`Access denied for user 'fmp_user'@'localhost'`**
→ Credentials in `user_settings.json` / `.env` don't match the MySQL user
you created. Recreate the user or update the config to match.

**`create_cache_tables` fails with `object bool can't be used in await`**
→ Known bug in `setup_database.py`. Use the sync workaround in step 5.
Tracked as a follow-up to #771.
