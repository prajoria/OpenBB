"""Populate project #5 with the 155 migrated pine issues.

Reads:
  - scripts/pine_script_project.json (project + field + option IDs)
  - tmp/beads-to-gh-map.json (bd-id -> gh-issue-number)
  - tmp/pine-beads-all.json (source of truth for beads metadata)

Writes:
  - scripts/pine_project_items.json (mapping gh-issue -> project item id, sub-issue parent)
  - Adds project items, sets Type/Priority/Area/Start/End
  - Creates 4 phase intermediate epics under root #729
  - Links every issue as sub-issue of the appropriate phase epic

Idempotent: skips items already added; picks up mid-run.

Usage:
  python scripts/populate_pine_project.py phase1   # add items + fields
  python scripts/populate_pine_project.py phase2   # create phase epics + wire sub-issues
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, tempfile

REPO = "prajoria/OpenBB"
ROOT_EPIC = 729
ROOT_EPIC_NODE = "I_kwDOQVcbSs8AAAABIpkIXw"
STATE = json.loads(open("scripts/pine_script_project.json", encoding="utf-8").read())
PROJECT_ID = STATE["project_id"]
FIELDS = STATE["fields"]
OPTS = STATE["options"]
MAP = json.loads(open("tmp/beads-to-gh-map.json", encoding="utf-8").read())
BEADS = {b["id"]: b for b in json.loads(open("tmp/pine-beads-all.json", encoding="utf-8").read())}
ITEMS_JSON = "scripts/pine_project_items.json"
SLEEP = 0.20
PRE_EXISTING_EPICS = {"OpenBBTechnical-0e9":102,"OpenBBTechnical-0e9.6":108,"OpenBBTechnical-0e9.7":109,"OpenBBTechnical-0e9.8":110}

def load_items():
    if os.path.exists(ITEMS_JSON):
        return json.loads(open(ITEMS_JSON, encoding="utf-8").read())
    return {"items":{}, "phase_epics":{}, "sub_issues_linked":[]}

def save_items(d):
    open(ITEMS_JSON,"w",encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False))

def gh(*args, check=True, input_data=None):
    time.sleep(SLEEP)
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_data)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {args[:2]} failed: {r.stderr.strip()}")
    return r

def classify_area(title:str) -> str|None:
    t = title.lower()
    if re.search(r"\btest|conformance|fixture|golden|\.t[1-5]|smoke test|no-side-effect ci", t): return "Tests"
    if re.search(r"widget|workspace|w1|example|smoke|cookbook", t): return "Examples"
    if re.search(r"stdlib|\bta\.|\bmath\.|s-ta|s-math|builtins|color\.|plot\.style|position-history|opentrades|closedtrades", t): return "StdLib"
    if re.search(r"\bdoc|readme|guide|prd|design|mcp|about\(", t): return "Docs"
    if re.search(r"signatures|c3a|c3b|type ?check|inner-type|typed|literal\[", t): return "Types"
    if re.search(r"runtime|executor|r1|r2|r3|dispatch|secondaryseries|iter_ohlcv|_data_provider_stub|stream|fetch\(|script_runner|scriptrunner", t): return "Runtime"
    if re.search(r"parser|grammar|codegen|c2\b|c3\b|c4|c5|c6|c7|@script\.|decorator|ast|freeze|feature|features", t): return "Parser"
    return "Tooling"

def issue_node_id(num:int)->str:
    # Use REST (core quota, not GraphQL) — 5000/hr, plenty
    r = gh("api",f"repos/{REPO}/issues/{num}","--jq",".node_id")
    return r.stdout.strip()

def add_item(node_id:str)->str:
    r = gh("api","graphql","-f",
        "query=mutation($p:ID!,$c:ID!){ addProjectV2ItemById(input:{projectId:$p,contentId:$c}){ item{id} } }",
        "-f",f"p={PROJECT_ID}","-f",f"c={node_id}","--jq",".data.addProjectV2ItemById.item.id")
    return r.stdout.strip()

def set_single_select(item_id:str, field_name:str, option_name:str):
    fid = FIELDS[field_name]; oid = OPTS[field_name][option_name]
    gh("api","graphql","-f",
        "query=mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){ projectV2Item{id} } }",
        "-f",f"p={PROJECT_ID}","-f",f"i={item_id}","-f",f"f={fid}","-f",f"o={oid}", check=False)

def set_date(item_id:str, field_name:str, date_iso:str):
    fid = FIELDS[field_name]
    gh("api","graphql","-f",
        "query=mutation($p:ID!,$i:ID!,$f:ID!,$d:Date!){ updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{date:$d}}){ projectV2Item{id} } }",
        "-f",f"p={PROJECT_ID}","-f",f"i={item_id}","-f",f"f={fid}","-f",f"d={date_iso}", check=False)

def phase_for(bead)->str:
    t = bead["title"]
    if re.search(r"\bE[0-4]\.[0-9]", t) or re.search(r"\[E[0-4]", t) or ("extraction" in t.lower() and "pine" in t.lower()):
        return "extraction"
    if "#pine-P1" in t or "#pine-smoke" in t or "#pine-D" in t or "#pine-P0" in t: return "phase1"
    if "#pine-P2" in t: return "phase2"
    if "#pine-P3" in t: return "phase3"
    if "#pine-P4" in t: return "phase4"
    return "unphased"

def phase1():
    st = load_items()
    todo = [(bid,num) for bid,num in MAP.items() if str(num) not in st["items"]]
    print(f"phase1: {len(todo)} issues to process ({len(st['items'])} already done)")
    for i,(bid,num) in enumerate(todo,1):
        try:
            bead = BEADS.get(bid)
            if not bead:
                print(f"[{i}/{len(todo)}] SKIP no bead for {bid} #{num}"); continue
            node = issue_node_id(num)
            item_id = add_item(node)
            st["items"][str(num)] = {"bead":bid,"item_id":item_id,"phase":phase_for(bead)}
            save_items(st)
            # Type
            it = bead.get("issue_type","task")
            type_val = {"epic":"Epic","bug":"Bug","feature":"Feature","task":"Task"}.get(it,"Task")
            set_single_select(item_id,"Type",type_val)
            # Priority
            p = bead.get("priority")
            if p in (1,2,3):
                set_single_select(item_id,"Priority",f"P{p}")
            # Area (blank for epics)
            if it != "epic":
                area = classify_area(bead["title"])
                if area: set_single_select(item_id,"Area",area)
            # Dates
            status = bead.get("status")
            if status == "closed":
                closed = bead.get("closed_at")
                if closed:
                    d = closed[:10]
                    set_date(item_id,"End",d)
                    # Start = created_at if present, else same day
                    created = bead.get("created_at","")
                    if created: set_date(item_id,"Start",created[:10])
            elif status in ("open","in_progress"):
                created = bead.get("created_at","")
                if created: set_date(item_id,"Start",created[:10])
            print(f"[{i}/{len(todo)}] #{num} bd-{bid} type={type_val} area={classify_area(bead['title']) if it!='epic' else '(epic)'} phase={st['items'][str(num)]['phase']}")
        except Exception as e:
            print(f"[{i}/{len(todo)}] ERROR #{num} bd-{bid}: {e}")
            save_items(st); raise
    print("phase1 done")

# ---- phase 2: sub-issue linking ----

PHASE_EPIC_TITLES = {
    "phase1":    "[EPIC] Pine Phase 1 - Foundation (M1)",
    "extraction":"[EPIC] Pine Extraction (E0-E4) - pynecore",
    "phase2":    "[EPIC] Pine Phase 2 - Strategies + cross-TF",
    "phase3":    "[EPIC] Pine Phase 3 - Completeness",
    "phase4":    "[EPIC] Pine Phase 4 - Polish and Launch",
    "unphased":  "[EPIC] Pine - Unphased backlog",
}
PHASE_EPIC_MILESTONE = {
    "phase1":    "Pine: Phase 1 - Foundation (M1)",
    "extraction":"Pine: Extraction (E0-E4) - pynecore",
    "phase2":    "Pine: Phase 2 - Strategies + cross-TF",
    "phase3":    "Pine: Phase 3 - Completeness",
    "phase4":    "Pine: Phase 4 - Polish and Launch",
    "unphased":  None,
}

def create_phase_epic(key:str, parent_num:int)->tuple[int,str]:
    """Create an intermediate epic, add it as sub-issue of parent_num, return (num,node_id)."""
    title = PHASE_EPIC_TITLES[key]
    body = f"Umbrella epic grouping all Pine Script `{key}` issues. Auto-created for GitHub sub-issue-cap purposes (100/parent).\n\nParent: #{parent_num}"
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",suffix=".md",delete=False) as f:
        f.write(body); bpath=f.name
    try:
        args=["issue","create","--repo",REPO,"--title",title,"--body-file",bpath,
              "--label","pine-script,type-epic,pine,type:epic"]
        ms=PHASE_EPIC_MILESTONE[key]
        if ms: args += ["--milestone", ms]
        r = gh(*args)
        m = re.search(r"/issues/(\d+)", r.stdout)
        num = int(m.group(1))
    finally:
        os.unlink(bpath)
    node = issue_node_id(num)
    return num, node

def link_sub_issue(parent_num:int, parent_node:str, child_num:int, child_node:str):
    # GitHub sub-issue API
    r = gh("api","-X","POST",f"repos/{REPO}/issues/{parent_num}/sub_issues",
           "-f",f"sub_issue_id={child_node.split('_')[-1] if False else ''}", check=False)
    # Actually the API requires the *database* id, not node_id. Use --field with a numeric.
    # Easier: use graphql addSubIssue
    q = "mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p,subIssueId:$c}){ issue{ number } } }"
    gh("api","graphql","-f",f"query={q}","-f",f"p={parent_node}","-f",f"c={child_node}", check=False)

def phase2():
    st = load_items()
    # 1) create phase epics if missing
    for key in ["phase1","extraction","phase2","phase3","phase4","unphased"]:
        if key in st["phase_epics"]: continue
        num, node = create_phase_epic(key, ROOT_EPIC)
        st["phase_epics"][key] = {"number":num,"node_id":node}
        save_items(st)
        # add to project #5
        item_id = add_item(node)
        st["items"][str(num)] = {"bead":None,"item_id":item_id,"phase":key,"intermediate_epic":True}
        set_single_select(item_id,"Type","Epic")
        set_single_select(item_id,"Priority","P1")
        save_items(st)
        # link as sub-issue of root
        link_sub_issue(ROOT_EPIC, ROOT_EPIC_NODE, num, node)
        print(f"created phase epic {key}: #{num}")
    # 2) link every migrated child under its phase epic
    linked = set(st["sub_issues_linked"])
    for num_s, info in st["items"].items():
        num = int(num_s)
        if info.get("intermediate_epic"): continue
        phase = info["phase"]
        parent = st["phase_epics"][phase]
        key = f"{parent['number']}->{num}"
        if key in linked: continue
        # get child node
        child_node = issue_node_id(num)
        link_sub_issue(parent["number"], parent["node_id"], num, child_node)
        linked.add(key); st["sub_issues_linked"] = sorted(linked)
        if len(linked) % 25 == 0: save_items(st)
        print(f"linked #{num} -> #{parent['number']} ({phase})")
    save_items(st)
    print(f"phase2 done: {len(linked)} sub-issue links")

if __name__=="__main__":
    cmd = sys.argv[1] if len(sys.argv)>1 else "phase1"
    {"phase1":phase1,"phase2":phase2}[cmd]()
