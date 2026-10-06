"""Authenticated live Workspace MCP parity harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

EXPECTED_TOOLS = {
    "add_generative_widget",
    "assign_tasks_to_agents",
    "create_widget",
    "delete_widget",
    "get_params_options",
    "get_skill_content",
    "get_widget_data",
    "get_widget_schema",
    "get_workspace_snapshot",
    "list_available_widgets",
    "manage_apps",
    "manage_backends",
    "manage_dashboard",
    "manage_navigation_bar",
    "navigate_workspace",
    "read_widget",
    "update_widget",
    "update_widget_layout",
}


def _structured(result: Any) -> dict[str, Any]:
    if result.is_error:
        raise RuntimeError("Workspace MCP tool returned a protocol error")
    value = result.structured_content
    if isinstance(value, dict):
        return value
    text = next(
        (
            content.text
            for content in result.content
            if getattr(content, "type", None) == "text"
        ),
        None,
    )
    if not text:
        raise RuntimeError("Workspace MCP tool returned no structured result")
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _data(payload: dict[str, Any]) -> Any:
    return payload.get("data", payload)


def _ids(value: Any) -> set[str]:
    """Collect backend/widget identifiers without retaining user content."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"id", "widget_id", "origin", "name"} and isinstance(item, str):
                found.add(item.lower())
            found.update(_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_ids(item))
    return found


async def _verify_metadata(client: Client) -> dict[str, Any]:
    tools = await client.list_tools()
    tool_names = {tool.name for tool in tools}
    if tool_names != EXPECTED_TOOLS:
        raise RuntimeError(
            f"Workspace tool drift: missing={sorted(EXPECTED_TOOLS - tool_names)}, "
            f"unexpected={sorted(tool_names - EXPECTED_TOOLS)}"
        )
    resources = await client.list_resources()
    if not resources:
        raise RuntimeError("Workspace resource catalog is empty")
    if len(resources) != 16:
        raise RuntimeError(
            f"Workspace resource descriptor count drift: {len(resources)}"
        )
    descriptors = {
        str(resource.uri): {
            "mime_type": resource.mimeType,
            "name": resource.name,
        }
        for resource in resources
    }
    if "openbb://workspace/app-builder/index" not in descriptors:
        raise RuntimeError("Workspace app-builder index resource is missing")
    descriptor = descriptors["openbb://workspace/app-builder/index"]
    expected_descriptor = {
        "mime_type": "text/markdown",
        "name": "App Builder Index",
    }
    if descriptor != expected_descriptor:
        raise RuntimeError(
            "Workspace app-builder descriptor drift: "
            f"expected={expected_descriptor}, actual={descriptor}"
        )
    content = await client.read_resource("openbb://workspace/app-builder/index")
    if not content:
        raise RuntimeError("Workspace app-builder index resource is unreadable")
    return {
        "resources": len(resources),
        "app_builder_descriptor": "matched",
        "tools": len(tools),
    }


async def _verify_no_browser(client: Client) -> dict[str, Any]:
    """Prove browser-backed reads fail instead of returning empty success."""
    try:
        payload = _structured(await client.call_tool("get_workspace_snapshot", {}))
    except (ToolError, RuntimeError):
        return {"browser": "unavailable", "failure": "explicit"}
    if payload.get("ok") is False:
        return {"browser": "unavailable", "failure": "explicit"}
    raise RuntimeError("Workspace snapshot unexpectedly succeeded without a browser")


async def _verify_registered_reads(client: Client) -> dict[str, Any]:
    snapshot = _structured(await client.call_tool("get_workspace_snapshot", {}))
    if not snapshot.get("ok", True):
        raise RuntimeError("Workspace browser bridge is unavailable")

    backends = _structured(
        await client.call_tool("manage_backends", {"operation": "list"})
    )
    widgets = _structured(await client.call_tool("list_available_widgets", {}))
    identifiers = _ids([_data(backends), _data(widgets)])
    required = {"portfolio", "pi_", "tt_"}
    if not any("portfolio" in item for item in identifiers):
        raise RuntimeError("Registered Portfolio backend/widgets are missing")
    if not any("pi_" in item for item in identifiers):
        raise RuntimeError("Registered Portfolio Intelligence widgets are missing")
    if not any("tt_" in item for item in identifiers):
        raise RuntimeError("Registered Trading Desk widgets are missing")
    return {
        "browser": "connected",
        "registered_surfaces": sorted(required),
        "snapshot": "available",
    }


async def _verify_mutation(client: Client, dashboard_id: str) -> dict[str, Any]:
    snapshot = _structured(await client.call_tool("get_workspace_snapshot", {}))
    snapshot_data = _data(snapshot)
    original_dashboard_id = None
    original_tab_id = None
    if isinstance(snapshot_data, dict):
        context = snapshot_data.get("session_context", snapshot_data)
        if isinstance(context, dict):
            original_dashboard_id = context.get("current_dashboard_uuid")
            original_tab_id = context.get("current_tab_id")
    target = _structured(
        await client.call_tool(
            "manage_dashboard",
            {"operation": "read", "dashboard_id": dashboard_id},
        )
    )
    target_data = _data(target)
    dashboard = target_data.get("dashboard") if isinstance(target_data, dict) else None
    if not isinstance(dashboard, dict):
        raise RuntimeError("Workspace mutation target metadata is unavailable")
    returned_id = dashboard.get("dashboard_id") or dashboard.get("uuid")
    dashboard_name = dashboard.get("name")
    if returned_id != dashboard_id:
        raise RuntimeError("Workspace mutation target identity mismatch")
    if not isinstance(dashboard_name, str) or (
        "mcp parity disposable" not in dashboard_name.lower()
    ):
        raise RuntimeError(
            "Workspace mutation target is not marked MCP parity disposable"
        )
    suffix = uuid.uuid4().hex[:10]
    created_uuid: str | None = None
    cleanup_failures: list[str] = []
    try:
        created = _structured(
            await client.call_tool(
                "add_generative_widget",
                {
                    "dashboard_id": dashboard_id,
                    "widget_type": "note",
                    "name": f"MCP parity {suffix}",
                    "description": "Disposable parity widget",
                    "data": f"Disposable MCP parity marker {suffix}",
                },
            )
        )
        created_data = _data(created)
        if isinstance(created_data, dict):
            created_uuid = created_data.get("widget_uuid")
        if not created_uuid:
            raise RuntimeError("Workspace mutation returned no widget UUID")
        updated = _structured(
            await client.call_tool(
                "update_widget",
                {
                    "dashboard_id": dashboard_id,
                    "widget_uuid": created_uuid,
                    "ui_args": {"title": f"MCP parity updated {suffix}"},
                },
            )
        )
        if not updated.get("ok", True):
            raise RuntimeError("Workspace widget update failed")
        navigated = _structured(
            await client.call_tool(
                "navigate_workspace",
                {"operation": "dashboard", "dashboard_id": dashboard_id},
            )
        )
        if not navigated.get("ok", True):
            raise RuntimeError("Workspace navigation failed")
        return {
            "cleanup": "pending",
            "create": "passed",
            "delete": "pending",
            "navigate": "passed",
            "update": "passed",
        }
    finally:
        if created_uuid:
            try:
                deleted = _structured(
                    await client.call_tool(
                        "delete_widget",
                        {
                            "dashboard_id": dashboard_id,
                            "widget_uuid": created_uuid,
                        },
                    )
                )
                if not deleted.get("ok", True):
                    cleanup_failures.append("widget deletion failed")
            except (ToolError, RuntimeError):
                cleanup_failures.append("widget deletion failed")
        if original_dashboard_id:
            try:
                restored = _structured(
                    await client.call_tool(
                        "navigate_workspace",
                        {
                            "operation": "dashboard",
                            "dashboard_id": original_dashboard_id,
                        },
                    )
                )
                if not restored.get("ok", True):
                    cleanup_failures.append("dashboard restoration failed")
                elif original_tab_id:
                    restored_tab = _structured(
                        await client.call_tool(
                            "navigate_workspace",
                            {
                                "operation": "tab",
                                "dashboard_id": original_dashboard_id,
                                "tab_id": original_tab_id,
                            },
                        )
                    )
                    if not restored_tab.get("ok", True):
                        cleanup_failures.append("tab restoration failed")
            except (ToolError, RuntimeError):
                cleanup_failures.append("route restoration failed")
        if cleanup_failures:
            raise RuntimeError(
                "Workspace cleanup failed: " + ", ".join(cleanup_failures)
            )


async def run(mode: str, allow_mutation: bool, dashboard_id: str | None) -> dict:
    """Run authenticated metadata/read parity and optional disposable mutation."""
    url = os.environ.get("WORKSPACE_MCP_URL", "").strip()
    token = os.environ.get("WORKSPACE_MCP_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError("Workspace MCP URL and short-lived token are required")
    if mode == "mutation" and not allow_mutation:
        raise RuntimeError("Workspace mutation requires explicit approval")
    if mode == "mutation" and not dashboard_id:
        raise RuntimeError("Workspace mutation requires a disposable dashboard ID")

    async with Client(url, auth=token, name="portfolio-workspace-parity") as client:
        evidence = {
            "metadata": await _verify_metadata(client),
        }
        if mode == "no-browser":
            evidence["no_browser"] = await _verify_no_browser(client)
        else:
            evidence["read"] = await _verify_registered_reads(client)
        if mode == "mutation":
            evidence["mutation"] = await _verify_mutation(client, dashboard_id or "")
            evidence["mutation"]["cleanup"] = "passed"
            evidence["mutation"]["delete"] = "passed"
        return evidence


def main() -> int:
    """Parse harness arguments and emit sanitized status evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("no-browser", "read", "mutation"),
        required=True,
    )
    parser.add_argument("--allow-mutation", action="store_true")
    parser.add_argument("--dashboard-id")
    args = parser.parse_args()
    evidence = asyncio.run(run(args.mode, args.allow_mutation, args.dashboard_id))
    print(json.dumps(evidence, sort_keys=True))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
