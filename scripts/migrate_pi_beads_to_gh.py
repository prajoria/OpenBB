"""Migrate 87 portfolio-intel beads to GitHub issues on prajoria/OpenBB.

Bead: OpenBBTechnical-qy83 program.

Strategy:
- Enumerate beads via `bd list --json`
- Sort epic -> phases (qy83.N) -> tasks (qy83.N.M) so parents are created
  before children
- For each bead:
  * gh issue create with title, body, labels
  * If parent already migrated: link via GitHub's sub-issue API
  * If bead was closed, gh issue close --reason completed with the
    original close_reason as a comment
  * bd update <id> --notes-append "github_issue: <url>"
- Rate-limit safe: sleep 0.25s between API calls

Produces `scripts/pi_bead_to_gh_map.json` mapping bead-id -> {issue_num, url}
so the migration is idempotent — reruns skip already-migrated beads.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = "prajoria/OpenBB"
MAP_FILE = Path(__file__).parent / "pi_bead_to_gh_map.json"
SLEEP = 0.25  # seconds between GH API calls


# ---------- helpers ----------
def sh(cmd: list[str], *, check: bool = True, input_: str | None = None) -> str:
    """Run a shell command, return stdout as str, raise on non-zero exit."""
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


def load_map() -> dict[str, dict]:
    """Load the resume map — bead-id -> {issue_num, url, node_id}."""
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


def save_map(m: dict[str, dict]) -> None:
    """Persist map atomically after every write."""
    tmp = MAP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MAP_FILE)


def parent_bead_id(bead_id: str) -> str | None:
    """qy83.4.12 -> qy83.4 ;  qy83.1 -> qy83 ;  qy83 -> None."""
    parts = bead_id.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else None


# ---------- bead -> gh mapping ----------
def bead_labels(bead: dict) -> list[str]:
    """Compute GH labels for a bead."""
    out = ["portfolio-intel", "bd-migrated"]
    # Type
    itype = bead.get("issue_type", "task")
    out.append(f"type-{itype}")
    # Phase & lane labels come from bead's own label list
    for lbl in bead.get("labels") or []:
        if lbl.startswith("m") and lbl in ("m0", "m4"):
            out.append(f"phase-{lbl}")
        elif lbl.startswith("p") and lbl in ("p0", "p1", "p2", "p3"):
            out.append(f"phase-{lbl}")
        elif lbl.startswith("lane-"):
            out.append(lbl)
    return sorted(set(out))


def bead_body(bead: dict) -> str:
    """Build a GH issue body from a bead."""
    lines: list[str] = []
    if bead.get("description"):
        lines.append(bead["description"])
        lines.append("")
    lines.append("---")
    lines.append("**Provenance**")
    lines.append(f"- Migrated from beads: `{bead['id']}`")
    lines.append(f"- Created at: {bead.get('created_at', '')}")
    lines.append(f"- Priority: P{bead.get('priority', 2)}")
    if bead.get("close_reason"):
        lines.append(f"- Original close reason: {bead['close_reason']}")
    parent = parent_bead_id(bead["id"])
    if parent:
        lines.append(f"- Parent bead: `{parent}`")
    return "\n".join(lines)


# ---------- gh api ops ----------
def gh_create_issue(title: str, body: str, labels: list[str]) -> dict:
    """gh issue create and return {issue_num, url, node_id}."""
    out = sh(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            REPO,
            "--title",
            title,
            "--body",
            body,
            "--label",
            ",".join(labels),
        ]
    ).strip()
    # gh issue create prints the URL
    url = out.splitlines()[-1].strip()
    issue_num = int(url.rsplit("/", 1)[-1])
    # Fetch node_id for the sub-issue API
    time.sleep(SLEEP)
    view = json.loads(
        sh(
            [
                "gh",
                "issue",
                "view",
                str(issue_num),
                "--repo",
                REPO,
                "--json",
                "id",
            ]
        )
    )
    return {"issue_num": issue_num, "url": url, "node_id": view["id"]}


def gh_close_issue(issue_num: int, comment: str) -> None:
    """gh issue close with a comment citing the original close reason."""
    sh(
        [
            "gh",
            "issue",
            "close",
            str(issue_num),
            "--repo",
            REPO,
            "--comment",
            comment,
            "--reason",
            "completed",
        ]
    )


def gh_add_sub_issue(parent_num: int, child_node_id: str) -> bool:
    """Wire child issue as a sub-issue of parent via GitHub's REST sub-issues API.

    Returns True on success, False on failure (logged; not fatal).

    Uses `gh api` to hit /repos/{owner}/{repo}/issues/{issue_number}/sub_issues
    with the sub-issue's *node* ID (GraphQL id, e.g. I_kwDO...).
    """
    endpoint = f"/repos/{REPO}/issues/{parent_num}/sub_issues"
    payload = json.dumps({"sub_issue_id": child_node_id})
    try:
        sh(
            [
                "gh",
                "api",
                "-X",
                "POST",
                endpoint,
                "-H",
                "Accept: application/vnd.github+json",
                "--input",
                "-",
            ],
            input_=payload,
        )
        return True
    except RuntimeError as e:
        # Sub-issues API needs the node ID's numeric database id, not the
        # GraphQL id. Fall back to fetching the database id via GraphQL.
        print(f"  sub-issue link failed (will retry with db id): {e}")
        return False


def gh_add_sub_issue_by_db_id(parent_num: int, child_issue_num: int) -> bool:
    """Sub-issue link via the child's numeric database ID.

    GH's sub-issues REST API accepts either the child's issue number in
    the same repo (as `sub_issue_id` if it's the DB id, NOT the issue
    number) — the terminology is confusing. Correct call: pass the
    integer `id` field from `gh api repos/.../issues/N` (not the `number`).
    """
    try:
        child_info = json.loads(
            sh(["gh", "api", f"/repos/{REPO}/issues/{child_issue_num}"])
        )
        child_db_id = child_info["id"]
        endpoint = f"/repos/{REPO}/issues/{parent_num}/sub_issues"
        payload = json.dumps({"sub_issue_id": child_db_id})
        sh(
            [
                "gh",
                "api",
                "-X",
                "POST",
                endpoint,
                "-H",
                "Accept: application/vnd.github+json",
                "--input",
                "-",
            ],
            input_=payload,
        )
        return True
    except RuntimeError as e:
        print(f"  sub-issue link (db id) failed: {e}")
        return False


# ---------- bead annotation ----------
def annotate_bead(bead_id: str, gh_url: str) -> None:
    """Append `github_issue: <url>` to bead notes."""
    try:
        sh(
            [
                "bd",
                "update",
                bead_id,
                "--append-notes",
                f"github_issue: {gh_url}",
            ]
        )
    except RuntimeError as e:
        print(f"  bd annotate failed for {bead_id}: {e}")


# ---------- main ----------
def main() -> int:
    """Migrate open + closed portfolio-intel beads to GH issues."""
    print("Loading beads…")
    raw = sh(["bd", "list", "-l", "portfolio-intel", "--all", "--json", "-n", "300"])
    beads = json.loads(raw)
    print(f"  {len(beads)} beads")

    # Sort so parents come before children: shortest ID first, then lex.
    beads.sort(key=lambda b: (b["id"].count("."), b["id"]))

    already = load_map()
    print(f"  {len(already)} already migrated (resume mode)")

    for i, bead in enumerate(beads, 1):
        bid = bead["id"]
        if bid in already:
            print(f"[{i}/{len(beads)}] SKIP {bid} — already migrated to #{already[bid]['issue_num']}")
            continue

        title = bead["title"]
        labels = bead_labels(bead)
        body = bead_body(bead)

        print(f"[{i}/{len(beads)}] CREATE {bid}: {title[:70]}")
        try:
            info = gh_create_issue(title, body, labels)
        except RuntimeError as e:
            print(f"  FAILED: {e}")
            continue

        already[bid] = info
        save_map(already)
        print(f"  -> #{info['issue_num']}  {info['url']}")

        # Wire sub-issue link (parent -> child)
        parent_id = parent_bead_id(bid)
        if parent_id and parent_id in already:
            parent_num = already[parent_id]["issue_num"]
            time.sleep(SLEEP)
            ok = gh_add_sub_issue_by_db_id(parent_num, info["issue_num"])
            if ok:
                print(f"  linked as sub-issue of #{parent_num}")

        # Close if the bead was closed
        if bead.get("status") == "closed":
            reason = bead.get("close_reason") or "migrated (bead was already closed)"
            time.sleep(SLEEP)
            try:
                gh_close_issue(
                    info["issue_num"],
                    f"Bead was already closed with reason:\n\n> {reason}",
                )
                print(f"  closed #{info['issue_num']} (bead was already closed)")
            except RuntimeError as e:
                print(f"  close failed: {e}")

        # Annotate the bead so it's easy to trace back
        time.sleep(SLEEP)
        annotate_bead(bid, info["url"])

    print("\nDone. Map at:", MAP_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
