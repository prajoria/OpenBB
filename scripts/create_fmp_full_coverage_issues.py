"""Create the FMP full-coverage issue hierarchy on prajoria/OpenBB and link it to
GitHub Project #4 (Portfolio Intelligence Engine).

Hierarchy:
    Epic #844 "[EPIC] FMP Cache"  (existing root; body gets a generated plan section)
      └─ Wave sub-epics  W0..W9   (type:feature, native sub-issues of #844)
           └─ Endpoint tasks       (type:task, one per FMP stable endpoint, native
                                    sub-issues of their wave, both providers as a
                                    two-provider checklist)

Every issue is added to Project #4 with Type (Epic/Feature/Task) and Status=Todo.

Idempotent: progress recorded in scripts/fmp_full_coverage_items.json; re-runs skip
anything already created/linked. Safe to resume after a rate-limit interruption.

Usage:
    python scripts/create_fmp_full_coverage_issues.py --labels-only
    python scripts/create_fmp_full_coverage_issues.py --waves-only
    python scripts/create_fmp_full_coverage_issues.py --limit 3        # first 3 endpoints
    python scripts/create_fmp_full_coverage_issues.py                  # everything
    python scripts/create_fmp_full_coverage_issues.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "scripts" / "fmp_full_coverage_endpoints.json"
STATE = ROOT / "scripts" / "fmp_full_coverage_items.json"

REPO = "prajoria/OpenBB"
PROJECT_ID = "PVT_kwHOAOc7384BdSTg"  # project #4
EPIC_NUMBER = 844

FIELD_TYPE = "PVTSSF_lAHOAOc7384BdSTgzhX06C4"
FIELD_STATUS = "PVTSSF_lAHOAOc7384BdSTgzhX058Y"
TYPE_OPTION = {"Epic": "6a4a1e4d", "Feature": "9e7e5af3", "Task": "16a0f716"}
STATUS_TODO = "f75ad846"

WAVE_TITLES = {
    0: "Wave 0 - Inventory + harness (audit, templates, migration)",
    1: "Wave 1 - Fundamentals completion (Arc C: statements/DCF/metrics)",
    2: "Wave 2 - Quotes & snapshots (Arc D)",
    3: "Wave 3 - Time-series completion (Arc B)",
    4: "Wave 4 - Reference / directory (Arc A)",
    5: "Wave 5 - Event feeds: filings & governance (Arc E)",
    6: "Wave 6 - Event feeds: news, calendars, transcripts, fundraisers, ESG (Arc E)",
    7: "Wave 7 - Analyst & market-performance remainder",
    8: "Wave 8 - Bulk (Arc F) + Partners/COT/TipRanks (Arc G)",
    9: "Wave 9 - Hardening & docs",
}
WAVE_THEME = {
    0: "Extend the coverage audit to all 276 endpoints across **both** providers, "
       "establish the `openbb_fmp` live-fetcher template, plan-limit normalization, "
       "the schema-version migration, and the fixture-replay test template. Gate for all waves.",
    1: "Complete fundamentals: TTM/as-reported/growth statements, financial scores, "
       "owner-earnings, enterprise values, key-metrics-ttm, ratios-ttm, and DCF ×4.",
    2: "One short-TTL snapshot template applied across equities/index/commodity/crypto/forex "
       "quotes, batch quotes, aftermarket, price-change, and market-cap.",
    3: "Gap-detection time-series: EOD variants, intraday intervals per asset class, "
       "technical indicators, historical market-cap and sector/industry performance.",
    4: "Cheap, high-reuse reference data: search, directory, symbol lists, classification "
       "lists, market hours/holidays — powers screeners and warmers.",
    5: "Append-only event feeds for SEC filings, insider trades, senate/house disclosures, "
       "13F remainder, mergers, delistings, symbol changes.",
    6: "Append-only event feeds for news, remaining calendars, earnings transcripts, "
       "crowdfunding/fundraising, and ESG.",
    7: "Analyst grades/price-target/ratings history and market-performance gainers/losers/"
       "actives plus sector/industry snapshots.",
    8: "Lowest-priority, premium-gated, warmer-oriented: bulk downloads, Commitment of "
       "Traders, and TipRanks partner endpoints.",
    9: "Full integration sweep, warmers, README + architecture doc updates, plan-limit "
       "matrix, and mypy/ruff cleanup of new modules.",
}

# Labels to ensure exist: (name, color, description)
LABELS = [
    ("fmp-cache", "1d76db", "FMP caching / persistence program"),
    ("area:fmp_cached", "0e8a16", "fmp_cached provider"),
    ("area:providers", "0e8a16", "OpenBB providers"),
    ("type:epic", "6f42c1", "Epic"),
    ("type:feature", "5319e7", "Feature / sub-epic"),
    ("type:task", "c5def5", "Task"),
]
for _w in range(10):
    LABELS.append((f"fmp-wave-{_w}", "bfd4f2", f"FMP coverage roadmap wave {_w}"))
for _a in "ABCDEFGH":
    LABELS.append((f"fmp-arc-{_a}", "d4c5f9", f"Persistence archetype {_a}"))
for _c, _d in [("N", "net-new (no live fetcher)"), ("F", "upstream-fallback today"),
               ("D", "dedicated persistence today"), ("DF", "mixed dedicated/fallback")]:
    LABELS.append((f"fmp-cov-{_c}", "fef2c0", f"Coverage: {_d}"))

ARC_NAME = {
    "A": "Reference/static (long TTL)", "B": "Time-series (gap detection)",
    "C": "Periodic point-in-time (fiscal period key)", "D": "Snapshot/quote (short TTL)",
    "E": "Event feed (append-only upsert)", "F": "Bulk download",
    "G": "Partner/COT/TipRanks", "H": "Streaming (out of scope)",
}

BEGIN = "<!-- fmp-full-coverage:begin -->"
END = "<!-- fmp-full-coverage:end -->"


# ---------------- shell / gh helpers ----------------
def sh(cmd: list[str], *, check: bool = True, input_: str | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {cmd}\nOUT:{r.stdout}\nERR:{r.stderr}")
    return r.stdout


def gql(query: str, **variables: str) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    out = sh(args)
    data = json.loads(out)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"waves": {}, "endpoints": {}, "epic": {}}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------- gh operations ----------------
def ensure_labels(dry: bool) -> None:
    existing = set()
    out = sh(["gh", "label", "list", "--repo", REPO, "--limit", "400", "--json", "name"])
    for row in json.loads(out):
        existing.add(row["name"])
    for name, color, desc in LABELS:
        if name in existing:
            continue
        print(f"  + label {name}")
        if dry:
            continue
        sh(["gh", "label", "create", name, "--repo", REPO, "--color", color,
            "--description", desc, "--force"])


def issue_node_id(number: int) -> str:
    out = sh(["gh", "issue", "view", str(number), "--repo", REPO, "--json", "id"])
    return json.loads(out)["id"]


def create_issue(title: str, body: str, labels: list[str], dry: bool) -> tuple[int, str]:
    if dry:
        print(f"  [dry] create issue: {title}")
        return (0, "")
    args = ["gh", "issue", "create", "--repo", REPO, "--title", title, "--body", body]
    for lb in labels:
        args += ["--label", lb]
    url = sh(args).strip().splitlines()[-1]
    number = int(url.rstrip("/").split("/")[-1])
    node = issue_node_id(number)
    return number, node


def add_sub_issue(parent_node: str, child_node: str) -> None:
    q = ("mutation($p:ID!,$c:ID!){addSubIssue(input:{issueId:$p,subIssueId:$c})"
         "{issue{number}}}")
    try:
        gql(q, p=parent_node, c=child_node)
    except RuntimeError as e:
        if "already" in str(e).lower():
            return
        raise


def add_to_project(node: str) -> str:
    q = ("mutation($proj:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$proj,"
         "contentId:$c}){item{id}}}")
    return gql(q, proj=PROJECT_ID, c=node)["addProjectV2ItemById"]["item"]["id"]


def set_select(item_id: str, field_id: str, option_id: str) -> None:
    q = ("mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue("
         "input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}})"
         "{projectV2Item{id}}}")
    gql(q, p=PROJECT_ID, i=item_id, f=field_id, o=option_id)


def project_type_and_status(item_id: str, type_name: str) -> None:
    set_select(item_id, FIELD_TYPE, TYPE_OPTION[type_name])
    set_select(item_id, FIELD_STATUS, STATUS_TODO)


# ---------------- body builders ----------------
def wave_body(w: int, eps: list[dict]) -> str:
    lines = [
        f"Part of #{EPIC_NUMBER} — FMP stable API full coverage "
        "(openbb_fmp live + fmp_cached persistence).",
        "",
        f"**Theme:** {WAVE_THEME[w]}",
        "",
        f"**Endpoints in this wave: {len(eps)}**",
        "",
        "Child issues (one per endpoint) are linked as sub-issues. "
        "Each delivers the two-provider unit of work:",
        "",
        "1. `openbb_fmp` live fetcher (raw HTTP + Query/Data models, plan-limit normalization)",
        "2. `fmp_cached` persistence wrapper subclassing the live fetcher (`aextract_data` read/write)",
        "3. `create_<name>_table()` DDL + registration in both providers",
        "4. structural + fixture-replay tests, mypy/ruff clean, architecture-doc row",
        "",
        "| Category | Endpoint | stable path | Cov | Arc |",
        "|---|---|---|---|---|",
    ]
    for e in sorted(eps, key=lambda r: (r["category"], r["endpoint"])):
        lines.append(
            f"| {e['category']} | {e['endpoint']} | `{e['stable_path']}` | {e['cov']} | {e['arc']} |"
        )
    return "\n".join(lines)


def endpoint_body(e: dict, wave_number: int) -> str:
    arc = e["arc"]
    return "\n".join([
        f"**Category:** {e['category']} · **Group:** {e['group']}",
        f"**FMP stable path:** `{e['path']}`",
        f"**Coverage today:** {e['cov']}  ·  **Archetype:** {arc} — {ARC_NAME.get(arc, '')}",
        f"**Wave:** {wave_number}",
        "",
        "Two-provider unit of work (paired PR):",
        "",
        "**`openbb_fmp` (live layer)**",
        "- [ ] Add live fetcher: raw HTTP call + `QueryParams` / `Data` models + transforms",
        "- [ ] Register the fetcher in `openbb_fmp`",
        "- [ ] Plan-limit normalization (402/403/empty → empty result, no raise)",
        "",
        "**`fmp_cached` (persistence layer)**",
        f"- [ ] Add `create_{e['stable_path'].replace('-', '_').replace('/', '_')}_table()` DDL to `cache_schema.py`",
        "- [ ] Fetcher subclasses the live fetcher; override `aextract_data` (read-through + write)",
        f"- [ ] Freshness strategy per archetype {arc} ({ARC_NAME.get(arc, '')})",
        "- [ ] Register in `fmp_cached/__init__.py`",
        "",
        "**Tests / DoD**",
        "- [ ] Structural test: DDL parses; fetcher registered in **both** providers",
        "- [ ] Fixture-replay test: MISS→store→HIT, plus plan-limit tolerance",
        "- [ ] mypy + ruff clean; architecture-doc row added",
        "",
        f"Design: `docs/superpowers/specs/2026-07-21-fmp-cached-full-api-coverage-design.md`",
        f"Parent: #{EPIC_NUMBER}",
    ])


def endpoint_title(e: dict) -> str:
    return f"[fmp][{e['category']}] {e['endpoint']} (`{e['stable_path']}`)"


def endpoint_labels(e: dict) -> list[str]:
    cov = e["cov"].replace("/", "").replace("DF", "DF").replace("FD", "DF")
    cov_label = f"fmp-cov-{'DF' if cov in ('DF',) else cov[:1]}"
    return [
        "fmp-cache", "area:fmp_cached", "area:providers", "type:task",
        f"fmp-wave-{e['wave']}", f"fmp-arc-{e['arc']}", cov_label,
    ]


# ---------------- epic body ----------------
def update_epic(records: list[dict], state: dict, dry: bool) -> None:
    out = sh(["gh", "issue", "view", str(EPIC_NUMBER), "--repo", REPO, "--json", "body"])
    body = json.loads(out)["body"] or ""
    from collections import Counter
    wc = Counter(r["wave"] for r in records)
    section = [BEGIN,
               "",
               "## FMP stable API — full coverage plan (auto-generated)",
               "",
               "Two providers enhanced in tandem, endpoint by endpoint:",
               "- **`openbb_fmp`** — live HTTP layer (fetcher per endpoint)",
               "- **`fmp_cached`** — MySQL persistence wrapper subclassing the live fetcher",
               "",
               f"**Total endpoints:** {len(records)} across 29 categories. "
               "Design doc: `docs/superpowers/specs/2026-07-21-fmp-cached-full-api-coverage-design.md`.",
               "",
               "### Waves (sub-epics)", ""]
    for w in range(10):
        ref = state["waves"].get(str(w), {})
        num = ref.get("number")
        cnt = wc.get(w, 0)
        link = f"#{num}" if num else "(pending)"
        section.append(f"- {link} — {WAVE_TITLES[w]} — {cnt} endpoint(s)")
    section += ["", END]
    new_block = "\n".join(section)

    if BEGIN in body and END in body:
        pre = body.split(BEGIN)[0].rstrip()
        post = body.split(END, 1)[1].lstrip()
        body = f"{pre}\n\n{new_block}\n\n{post}".strip()
    else:
        body = f"{body.rstrip()}\n\n{new_block}\n".strip()

    if dry:
        print("  [dry] would update epic #844 body")
        return
    sh(["gh", "issue", "edit", str(EPIC_NUMBER), "--repo", REPO, "--body", body])
    print("  updated epic #844 body")


# ---------------- main flow ----------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--labels-only", action="store_true")
    ap.add_argument("--waves-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only first N endpoints")
    ap.add_argument("--sleep", type=float, default=0.7)
    args = ap.parse_args()
    dry = args.dry_run

    records = json.loads(DATA.read_text(encoding="utf-8"))
    state = load_state()

    print("== ensuring labels ==")
    ensure_labels(dry)

    if args.labels_only:
        save_state(state)
        print("labels done.")
        return

    # epic node id
    epic_node = state["epic"].get("node_id") or (issue_node_id(EPIC_NUMBER) if not dry else "")
    if epic_node:
        state["epic"]["node_id"] = epic_node
        state["epic"]["number"] = EPIC_NUMBER

    # ---- waves ----
    waves_present = sorted({r["wave"] for r in records} | {0, 9})
    print("== creating wave sub-epics ==")
    for w in waves_present:
        key = str(w)
        if key in state["waves"] and state["waves"][key].get("number"):
            continue
        eps = [r for r in records if r["wave"] == w]
        title = f"[fmp][W{w}] {WAVE_TITLES[w]}"
        labels = ["fmp-cache", "area:fmp_cached", "type:feature", f"fmp-wave-{w}"]
        num, node = create_issue(title, wave_body(w, eps), labels, dry)
        if dry:
            continue
        add_sub_issue(epic_node, node)
        item = add_to_project(node)
        project_type_and_status(item, "Feature")
        state["waves"][key] = {"number": num, "node_id": node, "item_id": item}
        save_state(state)
        print(f"  wave {w}: #{num} ({len(eps)} endpoints)")
        time.sleep(args.sleep)

    if not dry:
        update_epic(records, state, dry)

    if args.waves_only:
        save_state(state)
        print("waves done.")
        return

    # ---- endpoints ----
    print("== creating endpoint tasks ==")
    todo = records if args.limit <= 0 else records[: args.limit]
    created = 0
    for e in todo:
        sp = e["stable_path"]
        ek = f"{e['category']}::{sp}"  # unique key (paths can repeat across categories)
        if ek in state["endpoints"] and state["endpoints"][ek].get("number"):
            continue
        wkey = str(e["wave"])
        wave_node = state["waves"].get(wkey, {}).get("node_id")
        num, node = create_issue(endpoint_title(e), endpoint_body(e, e["wave"]),
                                  endpoint_labels(e), dry)
        if dry:
            continue
        if wave_node:
            add_sub_issue(wave_node, node)
        item = add_to_project(node)
        project_type_and_status(item, "Task")
        state["endpoints"][ek] = {"number": num, "node_id": node, "item_id": item}
        created += 1
        if created % 10 == 0:
            save_state(state)
            print(f"  ... {created} endpoint issues created")
        time.sleep(args.sleep)
    save_state(state)
    print(f"done. endpoint issues created this run: {created}; "
          f"total tracked: {len(state['endpoints'])}")


if __name__ == "__main__":
    main()
