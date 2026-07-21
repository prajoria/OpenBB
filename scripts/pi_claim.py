#!/usr/bin/env python3
"""Claim, heartbeat, release, and reclaim Project #4 issues.

Usage:
  python scripts/pi_claim.py <issue> in-progress   # claim (initial)
  python scripts/pi_claim.py <issue> heartbeat     # ping (every <=10 min)
  python scripts/pi_claim.py <issue> release       # drop claim (back to Todo)
  python scripts/pi_claim.py <issue> reclaim       # take an abandoned claim
  python scripts/pi_claim.py <issue> done          # explicit Done (rare)
  python scripts/pi_claim.py <issue> todo          # reset
  python scripts/pi_claim.py --list-stale          # In Progress items w/ last hb > 2h
  python scripts/pi_claim.py --status <issue>      # show current claim state

Heartbeat protocol (see CLAUDE.md 'Coordination'):
  - Claimed items MUST heartbeat every <=10 min while owned
  - Items w/ last heartbeat > 2h are considered abandoned
  - Reclaim posts an audit comment naming the old owner + reason

Storage: heartbeat state is posted as a hidden HTML comment on the
issue body (invisible in rendered markdown but grep-able for any
agent). Format:

  <!-- pi-claim: owner=<who> hb=<ISO8601Z> action=<claim|heartbeat|reclaim> -->

The most recent such comment is the source of truth. This lives on
the issue timeline so it works across sessions/agents/machines and
never needs a separate DB.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "prajoria/OpenBB"
REPO_ROOT = Path(__file__).resolve().parents[1]
ITEMS_JSON = REPO_ROOT / "scripts" / "pi_project_items.json"

PROJECT_ID = "PVT_kwHOAOc7384BdSTg"
STATUS_FIELD_ID = "PVTSSF_lAHOAOc7384BdSTgzhX058Y"
STATUS_OPTIONS = {
    "todo": "f75ad846",
    "in-progress": "47fc9ee4",
    "done": "98236657",
}

HEARTBEAT_INTERVAL_MIN = 10
STALE_HOURS = 2

HB_MARKER_RE = re.compile(
    r"<!--\s*pi-claim:\s*owner=(?P<owner>\S+)\s+hb=(?P<hb>\S+)\s+action=(?P<action>\S+)\s*-->"
)


# ---------------------------------------------------------------------------
# Small gh CLI helpers
# ---------------------------------------------------------------------------


def gh(*args: str, check: bool = True) -> str:
    """Run gh CLI, return stdout. Raises on non-zero when check=True."""
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout


def gh_json(*args: str) -> object:
    return json.loads(gh(*args))


def whoami() -> str:
    """Return the authenticated GH login."""
    try:
        return json.loads(gh("api", "user"))["login"]
    except Exception:
        return "unknown-agent"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s.rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Item resolution
# ---------------------------------------------------------------------------


def item_id_for(issue: str) -> str:
    """Look up the Project #4 item_id for an issue number."""
    if not ITEMS_JSON.exists():
        raise RuntimeError(f"{ITEMS_JSON} not found")
    mapping = json.loads(ITEMS_JSON.read_text(encoding="utf-8"))
    entry = mapping.get(str(int(issue)))
    if not entry:
        raise RuntimeError(
            f"issue #{issue} not in {ITEMS_JSON}. "
            "Was it added to Project #4? Re-sync via pi_sync_project_items."
        )
    return entry["item_id"] if isinstance(entry, dict) else entry


# ---------------------------------------------------------------------------
# Status mutation
# ---------------------------------------------------------------------------


def set_status(issue: str, status: str) -> None:
    item = item_id_for(issue)
    option = STATUS_OPTIONS[status]
    query = f"""
    mutation {{
      updateProjectV2ItemFieldValue(input: {{
        projectId: "{PROJECT_ID}",
        itemId: "{item}",
        fieldId: "{STATUS_FIELD_ID}",
        value: {{ singleSelectOptionId: "{option}" }}
      }}) {{ projectV2Item {{ id }} }}
    }}
    """.strip()
    gh("api", "graphql", "-f", f"query={query}")


# ---------------------------------------------------------------------------
# Heartbeat comment protocol
# ---------------------------------------------------------------------------


def latest_heartbeat(issue: str) -> tuple[dict | None, str | None]:
    """Return (parsed hb dict, comment id) for the most recent hb comment.

    A hb dict has keys: owner, hb (datetime str, ISO), action.
    """
    # Fetch comments in reverse-chron
    data = gh_json(
        "api",
        f"/repos/{REPO}/issues/{issue}/comments?per_page=100",
    )
    latest_hb: dict | None = None
    latest_id: str | None = None
    for c in reversed(data):
        body = c.get("body") or ""
        m = HB_MARKER_RE.search(body)
        if m:
            latest_hb = m.groupdict()
            latest_id = str(c["id"])
            break
    return latest_hb, latest_id


def post_heartbeat_comment(issue: str, action: str, note: str | None = None) -> None:
    """Post a hb comment. `action` in {claim, heartbeat, release, reclaim, done}."""
    owner = whoami()
    body = f"<!-- pi-claim: owner={owner} hb={now_iso()} action={action} -->\n"
    if action == "claim":
        body += f"🟢 **Claimed** by `{owner}` at {now_iso()}. Will heartbeat every ≤{HEARTBEAT_INTERVAL_MIN} min."
    elif action == "heartbeat":
        # Silent heartbeat — no rendered content. Marker only.
        # This keeps the timeline uncluttered; the rendered comment is empty.
        body += ""
    elif action == "release":
        reason = f" ({note})" if note else ""
        body += f"🟡 **Released** by `{owner}` at {now_iso()}.{reason} Back to Todo."
    elif action == "reclaim":
        # Named in caller
        body += f"🔄 **Reclaimed** by `{owner}` at {now_iso()}.{f' Reason: {note}' if note else ''}"
    elif action == "done":
        body += f"✅ **Marked done** by `{owner}` at {now_iso()}."
    gh(
        "api",
        f"/repos/{REPO}/issues/{issue}/comments",
        "-f",
        f"body={body}",
        "-X",
        "POST",
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_status(issue: str) -> int:
    hb, _ = latest_heartbeat(issue)
    if not hb:
        print(f"#{issue}: no heartbeat comment yet")
        return 0
    age = datetime.now(timezone.utc) - parse_iso(hb["hb"])
    stale = age > timedelta(hours=STALE_HOURS)
    print(
        f"#{issue}: owner={hb['owner']}  last={hb['hb']}  "
        f"age={int(age.total_seconds() // 60)}min  "
        f"action={hb['action']}  {'STALE' if stale else 'fresh'}"
    )
    return 0


def cmd_list_stale() -> int:
    """Print all In Progress items whose last heartbeat > 2h (or missing)."""
    # Fetch the In Progress items via GraphQL
    query = """
    { user(login:"prajoria"){ projectV2(number:4){ items(first:100){ nodes{
      content{ ... on Issue { number title } }
      fieldValues(first:20){ nodes{ ... on ProjectV2ItemFieldSingleSelectValue { name field{... on ProjectV2FieldCommon{name}}}}}
    }}}}}
    """
    d = gh_json("api", "graphql", "-f", f"query={query}")
    items = d["data"]["user"]["projectV2"]["items"]["nodes"]
    in_progress = []
    for n in items:
        c = n.get("content") or {}
        num = c.get("number")
        if not num:
            continue
        st = None
        for fv in (n.get("fieldValues") or {}).get("nodes", []):
            if (fv.get("field") or {}).get("name") == "Status":
                st = fv.get("name")
        if st == "In Progress":
            in_progress.append((num, c.get("title", "")[:60]))

    now = datetime.now(timezone.utc)
    printed = 0
    for num, title in in_progress:
        hb, _ = latest_heartbeat(str(num))
        if not hb:
            print(f"  #{num:>4}  NO-HEARTBEAT  {title}")
            printed += 1
            continue
        age = now - parse_iso(hb["hb"])
        if age > timedelta(hours=STALE_HOURS):
            print(
                f"  #{num:>4}  owner={hb['owner']:<20}  "
                f"age={int(age.total_seconds() // 60)}min (STALE)  {title}"
            )
            printed += 1
    if not printed:
        print(f"no stale claims (all {len(in_progress)} In Progress items heartbeat within {STALE_HOURS}h)")
    return 0


def cmd_transition(issue: str, action: str, note: str | None = None) -> int:
    """Combined status + comment transition."""
    if action == "in-progress" or action == "claim":
        set_status(issue, "in-progress")
        post_heartbeat_comment(issue, "claim")
        print(f"#{issue} -> Status=in-progress (claimed by {whoami()})")

    elif action == "heartbeat":
        # Verify claim is still ours (or nobody's) before heartbeating
        hb, _ = latest_heartbeat(issue)
        me = whoami()
        if hb and hb["owner"] != me and hb["action"] in ("claim", "heartbeat", "reclaim"):
            age = datetime.now(timezone.utc) - parse_iso(hb["hb"])
            if age < timedelta(hours=STALE_HOURS):
                print(
                    f"WARNING: #{issue} is claimed by {hb['owner']} "
                    f"(last hb {int(age.total_seconds() // 60)}min ago). "
                    f"Not heartbeating over another agent's fresh claim."
                )
                return 3
        post_heartbeat_comment(issue, "heartbeat")
        print(f"#{issue} heartbeat by {me}")

    elif action == "release":
        set_status(issue, "todo")
        post_heartbeat_comment(issue, "release", note=note)
        print(f"#{issue} -> Status=todo (released)")

    elif action == "reclaim":
        hb, _ = latest_heartbeat(issue)
        if hb:
            age = datetime.now(timezone.utc) - parse_iso(hb["hb"])
            if age < timedelta(hours=STALE_HOURS):
                print(
                    f"REFUSED: #{issue} last heartbeat only "
                    f"{int(age.total_seconds() // 60)}min ago by {hb['owner']}. "
                    f"Only stale claims (>={STALE_HOURS}h) can be reclaimed."
                )
                return 3
            old_owner = hb["owner"]
            note = note or f"previous owner {old_owner} last hb {hb['hb']} (>{STALE_HOURS}h stale)"
        set_status(issue, "in-progress")
        post_heartbeat_comment(issue, "reclaim", note=note)
        print(f"#{issue} reclaimed by {whoami()}")

    elif action == "done":
        set_status(issue, "done")
        post_heartbeat_comment(issue, "done")
        print(f"#{issue} -> Status=done")

    elif action == "todo":
        set_status(issue, "todo")
        print(f"#{issue} -> Status=todo (no comment posted)")

    else:
        print(f"unknown action: {action}")
        return 2
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("issue", nargs="?")
    p.add_argument("action", nargs="?")
    p.add_argument("--note", default=None)
    p.add_argument("--list-stale", action="store_true")
    p.add_argument("--status", metavar="ISSUE")
    p.add_argument("-h", "--help", action="store_true")
    a = p.parse_args()

    if a.help or (not a.issue and not a.list_stale and not a.status):
        print(__doc__)
        return 0

    if a.list_stale:
        return cmd_list_stale()

    if a.status:
        return cmd_status(str(int(a.status)))

    issue = str(int(a.issue))
    action = (a.action or "").lower().strip()

    if action in {"in-progress", "claim", "heartbeat", "release", "reclaim", "done", "todo"}:
        try:
            return cmd_transition(issue, action, note=a.note)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    print(f"unknown action: {action!r}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
