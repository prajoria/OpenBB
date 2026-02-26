import urllib.request, ssl, json

ctx = ssl._create_unverified_context()
url = "https://127.0.0.1:6902/api/v1/equity/price/historical?symbol=AAPL&provider=fmp"
print("Testing:", url)
try:
    r = urllib.request.urlopen(url, context=ctx)
    print("Status:", r.status)
    print("Body:", r.read().decode()[:1000])
except urllib.error.HTTPError as e:
    print("Status:", e.code)
    print("Body:", e.read().decode()[:2000])
except Exception as e:
    print("Error:", e)
