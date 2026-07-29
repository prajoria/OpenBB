"""Build the canonical FMP full-coverage endpoint dataset for issue creation.

Reads:
  - scripts/fmp_endpoints.tsv            (276 rows: Category | Group | Endpoint | Path)
  - docs/superpowers/specs/2026-07-21-fmp-cached-full-api-coverage-design.md  (Section 8 tables: | Endpoint | stable path | Cov | Arc |)

Writes:
  - scripts/fmp_full_coverage_endpoints.json

Each record: {category, group, endpoint, path, stable_path, cov, arc, wave}
Cov/Arc are joined best-effort on the stable-path token; wave is assigned by a
deterministic archetype+category rule approximating the roadmap in plan Section 9.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TSV = ROOT / "scripts" / "fmp_endpoints.tsv"
PLAN = ROOT / "docs" / "superpowers" / "specs" / "2026-07-21-fmp-cached-full-api-coverage-design.md"
OUT = ROOT / "scripts" / "fmp_full_coverage_endpoints.json"


def stable_token(path: str) -> str:
    """Extract the stable path token from a raw path like 'stable/search-symbol?query=AAPL'."""
    p = path.strip()
    p = re.sub(r"^stable/", "", p)
    p = p.split("?", 1)[0]
    return p.strip().strip("/")


def parse_section8(md: str) -> dict[str, tuple[str, str]]:
    """Return {stable_path_token: (cov, arc)} parsed from Section 8 tables."""
    out: dict[str, tuple[str, str]] = {}
    row_re = re.compile(r"^\|\s*(.+?)\s*\|\s*`?(.+?)`?\s*\|\s*([DFN/]+)\s*\|\s*([A-H])\s*\|\s*$")
    for line in md.splitlines():
        m = row_re.match(line)
        if not m:
            continue
        endpoint, path_cell, cov, arc = m.groups()
        if endpoint.lower() == "endpoint":
            continue
        # path cell may contain '{...}' or subpaths; take first token before space/comma/brace
        raw = path_cell.strip().strip("`")
        # collapse things like 'historical-chart/{1min,5min,...}' -> base 'historical-chart'
        base = raw.split("/{", 1)[0].split(" ", 1)[0]
        tok = stable_token(base)
        out.setdefault(tok, (cov, arc))
        # also index the sub-path variant e.g. historical-price-eod/light
        out.setdefault(stable_token(raw.split(" ", 1)[0]), (cov, arc))
    return out


def assign_wave(category: str, arc: str) -> int:
    c = category
    if c in ("Statements", "DiscountedCashFlow"):
        return 1
    if arc == "F":
        return 8
    if arc == "G":
        return 8
    if c in ("Analyst", "MarketPerformance"):
        # fundamentals-flavoured analyst estimates go to Wave 1
        if arc == "C":
            return 1
        return 7
    if c in ("SecFilings", "InsiderTrades", "Form13F", "Senate"):
        return 5
    if c in ("News", "Calendar", "Fundraisers", "ESG", "EarningsTranscript"):
        return 6
    if arc == "C":
        return 1
    if arc == "D":
        return 2
    if arc == "B":
        return 3
    if arc == "A":
        return 4
    if arc == "E":
        return 5
    return 7


def main() -> None:
    md = PLAN.read_text(encoding="utf-8")
    cov_arc = parse_section8(md)

    records = []
    matched = 0
    for line in TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        category, group, endpoint, path = parts[0], parts[1], parts[2], parts[3]
        tok = stable_token(path)
        cov, arc = cov_arc.get(tok, ("", ""))
        if not arc:
            # try base token (strip trailing segment)
            base = tok.split("/", 1)[0]
            cov, arc = cov_arc.get(base, ("", ""))
        if arc:
            matched += 1
        # default archetype fallback by category when unmatched
        if not arc:
            arc = {
                "Bulk": "F", "Partners": "G", "CommitmentOfTraders": "G",
                "News": "E", "SecFilings": "E", "InsiderTrades": "E", "Senate": "E",
                "Search": "A", "Directory": "A", "MarketHours": "A",
                "Quote": "D", "Chart": "B", "TechnicalIndicators": "B",
                "Statements": "C", "DiscountedCashFlow": "C",
            }.get(category, "A")
        if not cov:
            cov = "N"
        wave = assign_wave(category, arc)
        records.append({
            "category": category,
            "group": group,
            "endpoint": endpoint,
            "path": path,
            "stable_path": tok,
            "cov": cov,
            "arc": arc,
            "wave": wave,
        })

    OUT.write_text(json.dumps(records, indent=2), encoding="utf-8")

    print(f"records: {len(records)}  cov/arc matched from Section 8: {matched}")
    from collections import Counter
    wc = Counter(r["wave"] for r in records)
    print("per-wave:", dict(sorted(wc.items())))
    ac = Counter(r["arc"] for r in records)
    print("per-arc :", dict(sorted(ac.items())))
    cc = Counter(r["cov"] for r in records)
    print("per-cov :", dict(sorted(cc.items())))
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
