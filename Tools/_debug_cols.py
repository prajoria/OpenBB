"""Debug: show center container col-ids for collapsed rows."""
from bs4 import BeautifulSoup

with open(r"I:\masterswork\FinanceData\Portfolio Positions.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

center = soup.find("div", class_="ag-center-cols-container")

# Show a few collapsed rows with their col-id values
for test_idx in ["62", "63", "64", "68", "69", "78", "82"]:
    row = None
    for r in center.find_all("div", class_="posweb-row-position", recursive=False):
        if r.get("row-index") == test_idx:
            row = r
            break
    if not row:
        print(f"Row {test_idx}: NOT FOUND")
        continue
    cells = row.find_all("div", class_="ag-cell")
    print(f"\nRow {test_idx}:")
    for c in cells:
        col_id = c.get("col-id", "?")
        text = c.get_text(strip=True)[:80]
        if text:
            print(f"  {col_id:>12}: {text}")
