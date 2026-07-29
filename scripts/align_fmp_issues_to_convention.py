"""Align the FMP full-coverage issues to the repo's Epic/Feature/Task convention
(as used by epic #491 "[portfolio] [EPIC] ...").

Changes (idempotent):
  * Epic #844: set project #4 Type=Epic; retitle to
      "[fmp] [EPIC] FMP Cached Full API Coverage (openbb-fmp-cached)"
  * Waves #1028..: retitle to "[fmp] [WAVE n] <theme>"; add priority label
  * Endpoint tasks: retitle to "[fmp] [Wn][Category] <Endpoint> (<path>)"; add priority label

Reads scripts/fmp_full_coverage_items.json and scripts/fmp_full_coverage_endpoints.json.
Only edits an issue when its current title differs from the target (avoids edit noise).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "scripts" / "fmp_full_coverage_items.json"
DATA = ROOT / "scripts" / "fmp_full_coverage_endpoints.json"

REPO = "prajoria/OpenBB"
PROJECT_ID = "PVT_kwHOAOc7384BdSTg"
FIELD_TYPE = "PVTSSF_lAHOAOc7384BdSTgzhX06C4"
TYPE_EPIC = "6a4a1e4d"
EPIC_NUMBER = 844
EPIC_TITLE = "[fmp] [EPIC] FMP Cached Full API Coverage (openbb-fmp-cached)"

WAVE_THEME = {
    0: "Inventory + harness (audit, templates, migration)",
    1: "Fundamentals completion (Arc C: statements/DCF/metrics)",
    2: "Quotes & snapshots (Arc D)",
    3: "Time-series completion (Arc B)",
    4: "Reference / directory (Arc A)",
    5: "Event feeds: filings & governance (Arc E)",
    6: "Event feeds: news, calendars, transcripts, fundraisers, ESG (Arc E)",
    7: "Analyst & market-performance remainder",
    8: "Bulk (Arc F) + Partners/COT/TipRanks (Arc G)",
    9: "Hardening & docs",
}
WAVE_PRIORITY = {0: "P0", 1: "P1", 2: "P1", 3: "P2", 4: "P2",
                 5: "P2", 6: "P3", 7: "P3", 8: "P3", 9: "P3"}


def sh(cmd: list[str], *, check: bool = True) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}\nERR:{r.stderr}\nOUT:{r.stdout}")
    return r.stdout


def gql(query: str, **variables: str) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    data = json.loads(sh(args))
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


def fetch_meta(node_ids: list[str]) -> dict[int, tuple[str, set[str]]]:
    """Batch-fetch {number: (title, {labels})} for issue node ids (100 per call)."""
    out: dict[int, tuple[str, set[str]]] = {}
    q = ("query($ids:[ID!]!){nodes(ids:$ids){... on Issue{number title "
         "labels(first:20){nodes{name}}}}}")
    for i in range(0, len(node_ids), 100):
        chunk = node_ids[i:i + 100]
        args = ["gh", "api", "graphql", "-f", f"query={q}"]
        for nid in chunk:
            args += ["-f", f"ids[]={nid}"]
        data = json.loads(sh(args))
        for n in data["data"]["nodes"]:
            if n:
                labels = {lb["name"] for lb in n["labels"]["nodes"]}
                out[n["number"]] = (n["title"], labels)
    return out


def apply(number: int, title: str | None, add_label: str | None) -> bool:
    """Edit issue; returns True if a change was requested."""
    if not title and not add_label:
        return False
    args = ["gh", "issue", "edit", str(number), "--repo", REPO]
    if title:
        args += ["--title", title]
    if add_label:
        args += ["--add-label", add_label]
    sh(args)
    return True


def epic_item_id() -> str:
    q = ('query{repository(owner:"prajoria",name:"OpenBB"){issue(number:%d)'
         '{projectItems(first:10){nodes{id project{number}}}}}}' % EPIC_NUMBER)
    data = gql(q)
    for n in data["repository"]["issue"]["projectItems"]["nodes"]:
        if n["project"]["number"] == 4:
            return n["id"]
    raise RuntimeError("epic #844 not on project #4")


def set_type_epic(item_id: str) -> None:
    q = ("mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue("
         "input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}})"
         "{projectV2Item{id}}}")
    gql(q, p=PROJECT_ID, i=item_id, f=FIELD_TYPE, o=TYPE_EPIC)


def main() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    records = json.loads(DATA.read_text(encoding="utf-8"))
    ep_by_key = {f"{r['category']}::{r['stable_path']}": r for r in records}

    # collect node ids for title prefetch
    node_ids = [state["epic"]["node_id"]]
    for w in state["waves"].values():
        node_ids.append(w["node_id"])
    for e in state["endpoints"].values():
        node_ids.append(e["node_id"])
    print(f"prefetching {len(node_ids)} titles/labels ...")
    meta = fetch_meta(node_ids)

    def needs(num: int, target_title: str, pr: str | None):
        cur_title, cur_labels = meta.get(num, ("", set()))
        new_title = target_title if cur_title != target_title else None
        add = None
        if pr and f"priority:{pr}" not in cur_labels:
            add = f"priority:{pr}"
        return new_title, add

    # ---- epic ----
    print("== epic #844 ==")
    item = epic_item_id()
    set_type_epic(item)
    print("  set Type=Epic on project #4")
    t, _ = needs(EPIC_NUMBER, EPIC_TITLE, None)
    if apply(EPIC_NUMBER, t, None):
        print(f"  retitled -> {EPIC_TITLE}")
    else:
        print("  title already aligned")

    # ---- waves ----
    print("== waves ==")
    for wkey, w in sorted(state["waves"].items(), key=lambda kv: int(kv[0])):
        wn = int(wkey)
        num = w["number"]
        target = f"[fmp] [WAVE {wn}] {WAVE_THEME[wn]}"
        pr = WAVE_PRIORITY[wn]
        t, add = needs(num, target, pr)
        if apply(num, t, add):
            print(f"  #{num} -> {target}  (+priority:{pr})")
            time.sleep(0.4)
        else:
            print(f"  #{num} already aligned")

    # ---- endpoint tasks ----
    print("== endpoint tasks ==")
    n = 0
    changed = 0
    for ekey, e in state["endpoints"].items():
        rec = ep_by_key.get(ekey)
        if not rec:
            print(f"  ! no record for {ekey}; skipping")
            continue
        num = e["number"]
        wn = rec["wave"]
        target = f"[fmp] [W{wn}][{rec['category']}] {rec['endpoint']} ({rec['stable_path']})"
        pr = WAVE_PRIORITY[wn]
        t, add = needs(num, target, pr)
        if apply(num, t, add):
            changed += 1
            time.sleep(0.35)
        n += 1
        if n % 20 == 0:
            print(f"  ... {n} scanned, {changed} edited")
    print(f"done. tasks scanned: {n}, edited: {changed}")


if __name__ == "__main__":
    main()
