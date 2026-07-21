#!/usr/bin/env python3
"""Set a Project #4 (Portfolio Intelligence Engine) issue's Status field.

Usage:
  python scripts/pi_claim.py <issue_number> [status]

Where `status` is one of: todo, in-progress, done (default: in-progress).

Why this exists:
  Project #4's "In Progress" column stays empty because agents skip the
  6-parameter GraphQL mutation and comment on the issue instead. Result:
  no one can see at a glance what's claimed. This script makes the
  mutation a one-liner so there's no excuse.

Reads:
  scripts/pi_project_items.json  — issue# → item_id map (checked-in)

Requires:
  gh CLI, authenticated to prajoria/OpenBB with project scope.

Constants below were cached from the project schema on 2026-07-21:
  - Project ID:            PVT_kwHOAOc7384BdSTg
  - Status field ID:       PVTSSF_lAHOAOc7384BdSTgzhX058Y
  - Option: Todo:          f75ad846
  - Option: In Progress:   47fc9ee4
  - Option: Done:          98236657
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ITEMS_JSON = REPO_ROOT / "scripts" / "pi_project_items.json"

PROJECT_ID = "PVT_kwHOAOc7384BdSTg"
STATUS_FIELD_ID = "PVTSSF_lAHOAOc7384BdSTgzhX058Y"
STATUS_OPTIONS = {
    "todo": "f75ad846",
    "in-progress": "47fc9ee4",
    "done": "98236657",
}


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(__doc__)
        return 2

    issue = sys.argv[1].lstrip("#")
    status = (sys.argv[2] if len(sys.argv) == 3 else "in-progress").lower()

    if status not in STATUS_OPTIONS:
        print(f"error: status must be one of {list(STATUS_OPTIONS)}; got {status!r}")
        return 2

    if not ITEMS_JSON.exists():
        print(f"error: {ITEMS_JSON} not found. Fetch project items first.")
        return 1

    mapping = json.loads(ITEMS_JSON.read_text(encoding="utf-8"))
    entry = mapping.get(issue) or mapping.get(str(int(issue)))
    if not entry:
        print(f"error: issue #{issue} not in {ITEMS_JSON}. Was it added to Project #4?")
        return 1

    item_id = entry["item_id"] if isinstance(entry, dict) else entry
    option_id = STATUS_OPTIONS[status]

    query = f"""
    mutation {{
      updateProjectV2ItemFieldValue(input: {{
        projectId: "{PROJECT_ID}",
        itemId: "{item_id}",
        fieldId: "{STATUS_FIELD_ID}",
        value: {{ singleSelectOptionId: "{option_id}" }}
      }}) {{ projectV2Item {{ id }} }}
    }}
    """.strip()

    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"error: gh api call failed:\n{result.stderr}")
        return 1

    print(f"#{issue} -> Status={status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
