"""Test equity/price/historical with chart=true to reproduce 500 error."""
import urllib.request
import ssl
import json

ctx = ssl._create_unverified_context()

# Without chart param (works)
url1 = "https://127.0.0.1:6902/api/v1/equity/price/historical?symbol=AAPL&provider=fmp&start_date=2025-01-01&end_date=2026-02-01&interval=1d"
# With chart=true (500 error)
url2 = url1 + "&chart=true&theme=dark"

for label, url in [("Without chart", url1), ("With chart=true", url2)]:
    try:
        r = urllib.request.urlopen(url, context=ctx)
        print(f"{label}: {r.status} OK")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"{label}: {e.code} ERROR")
        print(f"  Detail: {body}")
