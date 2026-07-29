"""Populate the Portfolio Intelligence Engine project with 87 GH issues.

For each of the 87 GH issues (from pi_bead_to_gh_map.json):

1. Add the issue to project #4 (get back a project-item ID)
2. Set the Phase field (M0/P0/P1/P2/P3/M4) from the issue's labels
3. Set the Lane field (A-Data/B-Analytics/...) from labels
4. Set the Type field (Epic/Feature/Task/Bug) from labels
5. Set Start/End dates from the phase timeline in the Execution Plan
   (M0=Wk 0-1, P0=Wk 1-3, P1=Wk 4-8, P2=Wk 9-13, P3=Wk 14-16)
   using PROGRAM_START (2026-07-13, today) as Wk 0.

Idempotent: writes scripts/pi_project_items.json mapping issue# -> item_id,
skips issues already added.

Uses `gh api graphql` for the writes since `gh project item-add` doesn't
expose the item ID cleanly, and field-value writes require the item ID.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# ---------- constants ----------
OWNER = "prajoria"
REPO = "prajoria/OpenBB"
PROJECT_ID = "PVT_kwHOAOc7384BdSTg"  # project #4

FIELD = {
    "Phase": "PVTSSF_lAHOAOc7384BdSTgzhX06B8",
    "Lane": "PVTSSF_lAHOAOc7384BdSTgzhX06C0",
    "Type": "PVTSSF_lAHOAOc7384BdSTgzhX06C4",
    "Start": "PVTF_lAHOAOc7384BdSTgzhX06C8",
    "End": "PVTF_lAHOAOc7384BdSTgzhX06DA",
}

PHASE_OPTION = {
    "M0": "369a1421",
    "P0": "9d94cce8",
    "P1": "040321ec",
    "P2": "62b45453",
    "P3": "3cb0e2f8",
    "M4": "1ccac243",
}

LANE_OPTION = {
    "A-Data": "76fa01d6",
    "B-Analytics": "942abc23",
    "C-App+Paper": "0a094b38",
    "D-Widgets+QA": "8f2251e7",
    "PM": "9d82918b",
    "QA": "3614f452",
}

TYPE_OPTION = {
    "Epic": "6a4a1e4d",
    "Feature": "9e7e5af3",
    "Task": "16a0f716",
    "Bug": "672eea10",
}

# Label -> project Lane option
LANE_FROM_LABEL = {
    "lane-a": "A-Data",
    "lane-b": "B-Analytics",
    "lane-c": "C-App+Paper",
    "lane-d": "D-Widgets+QA",
    "lane-pm": "PM",
    "lane-qa": "QA",
}

# Label -> project Type option
TYPE_FROM_LABEL = {
    "type-epic": "Epic",
    "type-feature": "Feature",
    "type-task": "Task",
    "type-bug": "Bug",
}

# Program start = today (2026-07-13). Phases from Execution Plan §20:
PROGRAM_START = date(2026, 7, 13)


def phase_dates(phase: str) -> tuple[str, str] | None:
    """Return (start_iso, end_iso) for a phase from the Execution Plan.

    M0 = Wk 0-1, P0 = Wk 1-3, P1 = Wk 4-8, P2 = Wk 9-13,
    P3 = Wk 14-16, M4 = end of Wk 16.
    Weeks are 7-day blocks from PROGRAM_START.
    """
    ranges = {
        "M0": (0, 1),
        "P0": (1, 3),
        "P1": (4, 8),
        "P2": (9, 13),
        "P3": (14, 16),
        "M4": (15, 16),
    }
    if phase not in ranges:
        return None
    ws, we = ranges[phase]
    return (
        (PROGRAM_START + timedelta(weeks=ws)).isoformat(),
        (PROGRAM_START + timedelta(weeks=we)).isoformat(),
    )


# ---------- helpers ----------
def sh(cmd: list[str], *, check: bool = True, input_: str | None = None) -> str:
    """Run cmd, return stdout as str."""
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=input_,
        encoding="utf-8",
        errors="replace",
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}\nstdout: {r.stdout}\nstderr: {r.stderr}")
    return r.stdout


def gql(query: str, **vars_) -> dict:
    """Run a GraphQL query via gh api graphql -F var=value ... and return data."""
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in vars_.items():
        args += ["-f", f"{k}={v}"]
    out = sh(args)
    data = json.loads(out)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}\nquery: {query[:200]}")
    return data["data"]


def add_item_to_project(issue_node_id: str) -> str:
    """Add issue to project, return the project-item ID."""
    q = """
    mutation($project: ID!, $content: ID!) {
      addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
        item { id }
      }
    }
    """
    # gh api graphql -f syntax requires values as strings; wrap as -F won't work for IDs
    args = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={q}",
        "-f",
        f"project={PROJECT_ID}",
        "-f",
        f"content={issue_node_id}",
    ]
    out = sh(args)
    data = json.loads(out)
    if "errors" in data:
        raise RuntimeError(f"add-item errors: {data['errors']}")
    return data["data"]["addProjectV2ItemById"]["item"]["id"]


def set_single_select(item_id: str, field_id: str, option_id: str) -> None:
    """Set a single-select field on a project item."""
    q = """
    mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $project,
        itemId: $item,
        fieldId: $field,
        value: { singleSelectOptionId: $option }
      }) { projectV2Item { id } }
    }
    """
    args = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={q}",
        "-f",
        f"project={PROJECT_ID}",
        "-f",
        f"item={item_id}",
        "-f",
        f"field={field_id}",
        "-f",
        f"option={option_id}",
    ]
    out = sh(args)
    data = json.loads(out)
    if "errors" in data:
        raise RuntimeError(f"set-single-select errors: {data['errors']}")


def set_date(item_id: str, field_id: str, date_iso: str) -> None:
    """Set a date field on a project item."""
    q = """
    mutation($project: ID!, $item: ID!, $field: ID!, $date: Date!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $project,
        itemId: $item,
        fieldId: $field,
        value: { date: $date }
      }) { projectV2Item { id } }
    }
    """
    args = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={q}",
        "-f",
        f"project={PROJECT_ID}",
        "-f",
        f"item={item_id}",
        "-f",
        f"field={field_id}",
        "-f",
        f"date={date_iso}",
    ]
    out = sh(args)
    data = json.loads(out)
    if "errors" in data:
        raise RuntimeError(f"set-date errors: {data['errors']}")


# ---------- issue -> phase/lane/type resolution ----------
def resolve_facets(labels: list[str]) -> tuple[str | None, str | None, str | None]:
    """Return (phase, lane, type_) option names from label list."""
    phase = lane = type_ = None
    for lbl in labels:
        if lbl.startswith("phase-"):
            key = lbl.split("-", 1)[1].upper()
            if key in PHASE_OPTION:
                phase = key
        elif lbl in LANE_FROM_LABEL:
            lane = LANE_FROM_LABEL[lbl]
        elif lbl in TYPE_FROM_LABEL:
            type_ = TYPE_FROM_LABEL[lbl]
    return phase, lane, type_


# ---------- main ----------
def main() -> int:
    map_path = Path(__file__).parent / "pi_bead_to_gh_map.json"
    items_path = Path(__file__).parent / "pi_project_items.json"

    bead_map = json.loads(map_path.read_text(encoding="utf-8"))
    existing_items: dict[str, dict] = (
        json.loads(items_path.read_text(encoding="utf-8"))
        if items_path.exists()
        else {}
    )

    # Load every issue's labels in one batch
    print("Fetching labels for all 87 issues…")
    issues_json = sh(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            REPO,
            "--label",
            "portfolio-intel",
            "--state",
            "all",
            "--limit",
            "200",
            "--json",
            "number,labels",
        ]
    )
    label_map = {
        str(iss["number"]): [l["name"] for l in iss["labels"]]
        for iss in json.loads(issues_json)
    }

    # Iterate bead map in a stable order (epic first, then phases, then tasks)
    sorted_beads = sorted(
        bead_map.items(),
        key=lambda kv: (kv[0].count("."), kv[0]),
    )

    for i, (bid, info) in enumerate(sorted_beads, 1):
        issue_num = info["issue_num"]
        node_id = info["node_id"]
        key = str(issue_num)

        if key in existing_items:
            print(f"[{i}/87] SKIP #{issue_num} ({bid}) — already in project")
            continue

        labels = label_map.get(key, [])
        phase, lane, type_ = resolve_facets(labels)

        print(
            f"[{i}/87] ADD #{issue_num} ({bid}) "
            f"phase={phase} lane={lane} type={type_}"
        )

        try:
            item_id = add_item_to_project(node_id)
            existing_items[key] = {
                "item_id": item_id,
                "bead_id": bid,
                "phase": phase,
                "lane": lane,
                "type": type_,
            }
            items_path.write_text(
                json.dumps(existing_items, indent=2, sort_keys=True), encoding="utf-8"
            )

            time.sleep(0.15)

            # Populate fields
            if type_:
                set_single_select(item_id, FIELD["Type"], TYPE_OPTION[type_])
                time.sleep(0.15)
            if phase:
                set_single_select(item_id, FIELD["Phase"], PHASE_OPTION[phase])
                time.sleep(0.15)

                dates = phase_dates(phase)
                if dates:
                    set_date(item_id, FIELD["Start"], dates[0])
                    time.sleep(0.15)
                    set_date(item_id, FIELD["End"], dates[1])
                    time.sleep(0.15)

            if lane:
                set_single_select(item_id, FIELD["Lane"], LANE_OPTION[lane])
                time.sleep(0.15)

        except RuntimeError as e:
            print(f"  FAILED: {e}")

    print(f"\nDone. {len(existing_items)}/87 items in project.")
    print(f"Map at {items_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
