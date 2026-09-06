"""Regression tests for the Project #4 claim lifecycle helper."""

from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pi_claim.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pi_claim", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["pi_claim"] = module
    spec.loader.exec_module(module)
    return module


def _project_item(number: int, title: str, status: str) -> dict:
    return {
        "id": f"item-{number}",
        "content": {"number": number, "title": title},
        "fieldValues": {
            "nodes": [
                {
                    "name": status,
                    "field": {"name": "Status"},
                }
            ]
        },
    }


def test_list_stale_paginates_every_project_item(monkeypatch, capsys):
    """A stale claim after the first 100 project items must be reported."""
    module = _load_module()
    pages = iter(
        [
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "nodes": [_project_item(1, "First page", "Todo")],
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "cursor-100",
                                },
                            }
                        }
                    }
                }
            },
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "nodes": [
                                    _project_item(
                                        2042, "Stale promotion", "In Progress"
                                    )
                                ],
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                            }
                        }
                    }
                }
            },
        ]
    )
    calls: list[tuple[str, ...]] = []

    def fake_gh_json(*args: str) -> object:
        calls.append(args)
        return next(pages)

    monkeypatch.setattr(module, "gh_json", fake_gh_json)
    monkeypatch.setattr(
        module,
        "latest_heartbeat",
        lambda _issue: (
            {
                "owner": "prajoria",
                "hb": "2026-08-01T00:00:00Z",
                "action": "heartbeat",
            },
            "comment-id",
        ),
    )
    monkeypatch.setattr(module, "_age", lambda _heartbeat: timedelta(days=30))

    assert module.cmd_list_stale() == 0

    output = capsys.readouterr().out
    assert "#2042" in output
    assert "STALE" in output
    assert len(calls) == 2
    assert any("cursor-100" in arg for arg in calls[1])


def test_item_id_for_falls_back_to_live_project_items(monkeypatch, tmp_path):
    """New project items need not be present in the legacy JSON snapshot."""
    module = _load_module()
    missing_snapshot = tmp_path / "pi_project_items.json"
    monkeypatch.setattr(module, "ITEMS_JSON", missing_snapshot)
    monkeypatch.setattr(
        module,
        "_project_items",
        lambda: [_project_item(2045, "Lifecycle bug", "In Progress")],
    )

    assert module.item_id_for("2045") == "item-2045"
