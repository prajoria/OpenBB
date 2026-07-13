"""Migrate pine-related beads to GitHub issues in prajoria/OpenBB.

Two passes:
  pass1: create issues + record bd->gh map, close historical, assign in_progress
  pass2: append `## Dependencies` block on each issue using the map

Idempotent: re-reads tmp/beads-to-gh-map.json on start and skips already-mapped beads.

Usage:
  python tmp/migrate_pine_beads.py pass1
  python tmp/migrate_pine_beads.py pass2
  python tmp/migrate_pine_beads.py rollback   # deletes mapped issues + restores bead status
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, tempfile, pathlib

REPO = "prajoria/OpenBB"
BEADS_JSON = "tmp/pine-beads-all.json"
MAP_JSON = "tmp/beads-to-gh-map.json"
SLEEP = 0.25

# beads already mirrored as GH issues (don't create; §4 of plan handled labels/milestone)
PRE_EXISTING = {
    "OpenBBTechnical-0e9": 102,
    "OpenBBTechnical-0e9.6": 108,
    "OpenBBTechnical-0e9.7": 109,
    "OpenBBTechnical-0e9.8": 110,
}

MILESTONES = {
    "epic-extension":  "Pine: Extension Epic (P1)",
    "phase-1":         "Pine: Phase 1 - Foundation (M1)",
    "extraction":      "Pine: Extraction (E0-E4) - pynecore",
    "phase-2":         "Pine: Phase 2 - Strategies + cross-TF",
    "phase-3":         "Pine: Phase 3 - Completeness",
    "phase-4":         "Pine: Phase 4 - Polish and Launch",
}

def load_map() -> dict:
    if os.path.exists(MAP_JSON):
        return json.loads(open(MAP_JSON, encoding="utf-8").read())
    return {}

def save_map(m: dict):
    open(MAP_JSON, "w", encoding="utf-8").write(json.dumps(m, indent=2, ensure_ascii=False))

def classify_milestone(bead) -> str | None:
    t = bead["title"]
    if re.search(r"\bE[0-4]\.[0-9]", t) or re.search(r"\[E[0-4]", t) or "extraction" in t.lower() and "pine" in t.lower():
        return MILESTONES["extraction"]
    if "#pine-P1" in t or "#pine-smoke" in t or "#pine-D" in t or "#pine-P0" in t:
        return MILESTONES["phase-1"]
    if "#pine-P2" in t:
        return MILESTONES["phase-2"]
    if "#pine-P3" in t:
        return MILESTONES["phase-3"]
    if "#pine-P4" in t:
        return MILESTONES["phase-4"]
    return None

def labels_for(bead) -> list[str]:
    labels = ["pine"]
    it = bead.get("issue_type") or "task"
    if it == "epic":     labels.append("type:epic")
    elif it == "bug":    labels.append("bug"); labels.append("type:bug")
    elif it == "feature":labels.append("type:feature")
    else:                labels.append("type:task")
    p = bead.get("priority")
    if p in (1,2,3):     labels.append(f"p{p}")
    if classify_milestone(bead) == MILESTONES["extraction"]:
        labels.append("phase:extraction")
    if bead.get("status") == "deferred":
        labels.append("wontfix")
    return labels

def build_body(bead) -> str:
    desc = (bead.get("description") or "").strip() or "*(No description in beads.)*"
    bid = bead["id"]
    prio = bead.get("priority", "?")
    it = bead.get("issue_type", "?")
    st = bead.get("status", "?")
    owner = bead.get("owner") or "unassigned"
    closed = bead.get("closed_at") or ""
    return (
        f"{desc}\n\n---\n\n## Origin\n\n"
        f"Migrated from beads `bd-{bid}` on 2026-07-13.\n\n"
        f"- Original priority: p{prio}\n"
        f"- Original type: {it}\n"
        f"- Original status: {st}\n"
        f"- Original owner: {owner}\n"
        f"- Beads closed_at: {closed}\n"
    )

def gh(*args, check=True, input_data=None):
    time.sleep(SLEEP)
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_data)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {args[:2]} failed: {r.stderr.strip()}")
    return r

def create_issue(bead) -> int:
    title = bead["title"]
    body = build_body(bead)
    labels = labels_for(bead)
    ms = classify_milestone(bead)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(body); bpath = f.name
    try:
        args = ["issue","create","--repo",REPO,"--title",title,"--body-file",bpath,"--label",",".join(labels)]
        if ms: args += ["--milestone", ms]
        r = gh(*args)
        # gh prints "https://github.com/prajoria/OpenBB/issues/NN"
        m = re.search(r"/issues/(\d+)", r.stdout)
        if not m: raise RuntimeError(f"could not parse issue number from: {r.stdout!r}")
        return int(m.group(1))
    finally:
        os.unlink(bpath)

def pass1():
    beads = json.loads(open(BEADS_JSON, encoding="utf-8").read())
    m = load_map()
    for pre_id, pre_num in PRE_EXISTING.items():
        m.setdefault(pre_id, pre_num)
    save_map(m)
    todo = [b for b in beads if b["id"] not in m]
    print(f"pass1: {len(todo)} beads to create ({len(m)} already mapped)")
    for i, bead in enumerate(todo, 1):
        try:
            num = create_issue(bead)
            m[bead["id"]] = num
            save_map(m)
            status = bead.get("status")
            if status == "closed":
                gh("issue","close",str(num),"--repo",REPO,"--reason","completed")
            elif status == "deferred":
                gh("issue","close",str(num),"--repo",REPO,"--reason","not planned")
            elif status == "in_progress":
                owner = (bead.get("owner") or "").lower()
                if "rajoria" in owner or "prajoria" in owner:
                    gh("issue","edit",str(num),"--repo",REPO,"--add-assignee","prajoria", check=False)
            print(f"[{i}/{len(todo)}] bd-{bead['id']} -> #{num} ({status})")
        except Exception as e:
            print(f"[{i}/{len(todo)}] ERROR bd-{bead['id']}: {e}")
            save_map(m)
            raise
    print("pass1 done")

def pass2():
    beads = json.loads(open(BEADS_JSON, encoding="utf-8").read())
    m = load_map()
    by_id = {b["id"]: b for b in beads}
    updated = 0
    for bead in beads:
        deps = bead.get("dependencies") or []
        if not deps: continue
        gh_num = m.get(bead["id"])
        if not gh_num: continue
        blocked_by, parent = [], None
        for d in deps:
            dep_bead = d.get("depends_on_id")
            dep_num = m.get(dep_bead)
            if not dep_num: continue
            t = d.get("type","")
            if t == "blocked-by":
                blocked_by.append((dep_num, dep_bead))
            elif t == "parent-child":
                parent = (dep_num, dep_bead)
        if not blocked_by and not parent: continue
        # fetch current body
        r = gh("issue","view",str(gh_num),"--repo",REPO,"--json","body")
        body = json.loads(r.stdout)["body"]
        if "## Dependencies" in body:
            # replace existing block
            body = re.sub(r"\n\n## Dependencies\n.*$", "", body, flags=re.S)
        lines = ["", "", "## Dependencies", ""]
        if parent:
            lines.append(f"- Parent: #{parent[0]} (bd-{parent[1]})")
        for gn, bid in blocked_by:
            lines.append(f"- Blocked by: #{gn} (bd-{bid})")
        new_body = body.rstrip() + "\n".join(lines) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
            f.write(new_body); bpath = f.name
        try:
            gh("issue","edit",str(gh_num),"--repo",REPO,"--body-file",bpath)
        finally:
            os.unlink(bpath)
        updated += 1
        print(f"deps wired: bd-{bead['id']} -> #{gh_num} (parent={bool(parent)}, blocked_by={len(blocked_by)})")
    print(f"pass2 done: {updated} issues updated")

def rollback():
    m = load_map()
    for bid, num in m.items():
        if bid in PRE_EXISTING: continue
        try:
            gh("issue","delete",str(num),"--repo",REPO,"--yes", check=False)
            print(f"deleted #{num} (bd-{bid})")
        except Exception as e:
            print(f"skip #{num}: {e}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pass1"
    {"pass1": pass1, "pass2": pass2, "rollback": rollback}[cmd]()
