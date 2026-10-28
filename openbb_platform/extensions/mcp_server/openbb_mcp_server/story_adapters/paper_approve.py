"""Approve a prepared story paper action as a person (#2331, N09a).

Usage::

    python -m openbb_mcp_server.story_adapters.paper_approve <request_id>

The approver reads the request from the server's own store and shows the
arguments the server will apply, never a description supplied by the model
that prepared it. It needs ``OPENBB_STORY_APPROVAL_KEY`` and a terminal: text
piped in by a program is refused. On ``yes`` it prints the approval to pass
to ``story_paper_apply``. It is not an MCP tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from openbb_mcp_server.story_adapters import paper
from openbb_mcp_server.story_adapters.registry import default_store_path


class ApprovalDenied(Exception):
    """The person declined, or the request cannot be approved."""


def shown(value: Any) -> str:
    """Render one value for the prompt; anything unusual is visibly escaped."""
    text = str(value)
    if text.isascii() and text.isprintable():
        return text
    # Newlines, terminal escapes and invisible or reordering characters could
    # forge or hide lines, so they are shown as escapes on a single line.
    return json.dumps(text, ensure_ascii=True)


def _lines(value: Any, indent: str = "  ") -> list[str]:
    if isinstance(value, dict):
        lines = []
        for key in sorted(value):
            item = value[key]
            if isinstance(item, dict | list):
                lines.append(f"{indent}{shown(key)}:")
                lines.extend(_lines(item, indent + "  "))
            else:
                lines.append(f"{indent}{shown(key)}: {shown(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for index, item in enumerate(value, start=1):
            lines.append(f"{indent}[{index}]")
            lines.extend(_lines(item, indent + "  "))
        return lines
    return [f"{indent}{shown(value)}"]


def render_summary(row: Any) -> str:
    """Describe a stored request from its stored arguments."""
    arguments = json.loads(row["arguments"])
    return "\n".join(
        [
            f"Story paper action: {shown(row['action'])}",
            f"Sandbox: {shown(row['sandbox_id'])} (run {shown(row['run_id'])},"
            f" {shown(row['manifest_version'])})",
            f"Operation: {shown(row['operation_id'])}",
            f"Expires: {shown(row['expires_at'])}",
            "Arguments:",
            *_lines(arguments),
        ]
    )


def approve_request(
    request_id: str,
    *,
    db_path: Path | None = None,
    confirm: Callable[[str], bool],
) -> str:
    """Return the approval for a pending request once ``confirm`` agrees."""
    key = paper.approval_key()
    if key is None:
        raise ApprovalDenied(
            f"{paper.APPROVAL_KEY_ENV} is not set to a key of at least"
            f" {paper.MIN_KEY_LENGTH} characters."
        )
    store = paper.PaperStore(
        db_path or default_store_path(), paper.default_paper_root()
    )
    row = store.request(request_id)
    if row is None:
        raise ApprovalDenied(f"No paper request {request_id!r}.")
    if row["status"] != "pending":
        raise ApprovalDenied(f"The request is {row['status']}, not pending.")
    # Same clock as the routes, so both agree on expiry.
    now = paper._now()  # pylint: disable=protected-access
    if datetime.fromisoformat(row["expires_at"]) <= now:
        raise ApprovalDenied("The request has expired; prepare it again.")
    if not confirm(render_summary(row)):
        raise ApprovalDenied("Declined.")
    return paper.request_signature(key, paper.signed_view(row))


def _is_terminal() -> bool:
    return sys.stdin.isatty()


def main(argv: list[str] | None = None) -> int:
    """Show a request, ask for an explicit yes, and print its approval."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("request_id")
    parser.add_argument("--store", type=Path, default=None, help="Run store path.")
    args = parser.parse_args(argv)
    if not _is_terminal():
        print(  # noqa: T201  # this command's output is for a person
            "Approval needs a person at a terminal; stdin is not one.", file=sys.stderr
        )
        return 2

    def ask(summary: str) -> bool:
        print(summary)  # noqa: T201
        answer = input("Approve this paper action? [y/N] ")
        return answer.strip().lower() in {"y", "yes"}

    try:
        token = approve_request(args.request_id, db_path=args.store, confirm=ask)
    except ApprovalDenied as error:
        print(f"Not approved: {error}", file=sys.stderr)  # noqa: T201
        return 1
    print(token)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
