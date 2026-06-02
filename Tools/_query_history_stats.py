"""Quick query: equity_historical stats for portfolio position symbols."""
import sys, os
sys.path.insert(0, 'openbb_platform/providers/fmp_cached')
sys.path.insert(0, 'openbb_platform/providers/fmp')
sys.path.insert(0, 'openbb_platform/core')
sys.path.insert(0, 'openbb_platform/platform')
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pymysql

SKIP = {'Cash', 'NSAV', 'MVVYF', 'EADSF', 'NXDR', 'NHX202764', 'NHX203309'}

conn = pymysql.connect(
    host='localhost', port=3306, user='fmp_user', password='fmp_password',
    database='openbb_fmp_cache_test', cursorclass=pymysql.cursors.DictCursor,
)
cur = conn.cursor()

# Portfolio symbols
cur.execute('SELECT DISTINCT symbol FROM Portfolio_Positions ORDER BY symbol')
all_syms = [r['symbol'] for r in cur.fetchall()]
tickers = [s for s in all_syms if not s[0].isdigit() and s not in SKIP]

# History stats
ph = ','.join(['%s'] * len(tickers))
cur.execute(
    f"SELECT symbol, COUNT(*) as cnt, MIN(date) as first_date, MAX(date) as last_date "
    f"FROM equity_historical WHERE symbol IN ({ph}) "
    f"GROUP BY symbol ORDER BY symbol",
    tickers,
)
rows = cur.fetchall()
have = {r['symbol'] for r in rows}
missing = sorted(set(tickers) - have)

hdr = f"{'Symbol':<10} {'Rows':>6}  {'First':>12}  {'Last':>12}"
sep = f"{'------':<10} {'----':>6}  {'----------':>12}  {'----------':>12}"
print(hdr)
print(sep)
total = 0
for r in rows:
    print(f"{r['symbol']:<10} {r['cnt']:>6}  {str(r['first_date']):>12}  {str(r['last_date']):>12}")
    total += r['cnt']

print(f"\n  Portfolio tickers: {len(tickers)}")
print(f"  With history:     {len(rows)}")
print(f"  Missing history:  {len(missing)}  {missing if missing else ''}")
print(f"  Total rows:       {total:,}")
conn.close()
