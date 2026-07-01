"""Tests for :mod:`openbb_pine.mcp_tools` — MCP tool registration hook (bead 0e9.5.54).

Locks:

1. :func:`register` exists and is callable with an MCP-server-like object.
2. Calling ``register(mock_server)`` invokes ``mock_server.register_tool``
   once per widgets.json entry.
3. Each ``register_tool`` call carries a valid JSON schema derived from
   the widget's ``params``.
4. The registered handler's docstring / name reflects the widget id.
5. The stubbed dispatch body raises :class:`NotImplementedError` with a
   clear "M4 launch" message — this proves the wiring is intentional and
   not silently returning empty data.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from openbb_pine import _load_bundled_widgets
from openbb_pine.mcp_tools import (
    MCPServerLike,
    _derive_schema_from_widget,
    _dispatch_via_pine_run,
    _json_type_of,
    register,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def test_register_is_callable() -> None:
    """The public entry point ``register`` must be callable."""
    assert callable(register)


def test_register_calls_register_tool_once_per_widget() -> None:
    """One ``register_tool`` call per top-level entry in widgets.json."""
    mock_server = MagicMock()
    register(mock_server)
    expected = len(_load_bundled_widgets())
    assert mock_server.register_tool.call_count == expected, (
        f"expected {expected} register_tool calls, got "
        f"{mock_server.register_tool.call_count}"
    )


def test_register_uses_widget_id_as_tool_name() -> None:
    """Each tool name is the widget id verbatim — widget ids already carry
    the ``pine_`` prefix per D3 §7.2 convention."""
    mock_server = MagicMock()
    register(mock_server)
    call_names = {
        call.kwargs["name"] for call in mock_server.register_tool.call_args_list
    }
    assert call_names == set(_load_bundled_widgets().keys())


def test_register_carries_widget_description() -> None:
    """The tool description comes from the widget's ``description`` field."""
    mock_server = MagicMock()
    register(mock_server)
    widgets = _load_bundled_widgets()
    for call in mock_server.register_tool.call_args_list:
        widget_id = call.kwargs["name"]
        assert call.kwargs["description"] == widgets[widget_id]["description"]


def test_register_carries_a_json_schema_per_widget() -> None:
    """Each ``schema`` arg is a JSON-schema dict with ``type`` = ``"object"``."""
    mock_server = MagicMock()
    register(mock_server)
    for call in mock_server.register_tool.call_args_list:
        schema = call.kwargs["schema"]
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert "properties" in schema


def test_register_handler_is_callable() -> None:
    """Each handler is a callable ready to accept **overrides."""
    mock_server = MagicMock()
    register(mock_server)
    for call in mock_server.register_tool.call_args_list:
        handler = call.kwargs["handler"]
        assert callable(handler)


# ---------------------------------------------------------------------------
# Schema derivation
# ---------------------------------------------------------------------------


def test_derive_schema_from_widget_types_scalar_params() -> None:
    """Scalar params get inferred JSON types from Python type."""
    spec: dict[str, Any] = {
        "params": {
            "source": "print('hi')",   # string
            "length": 20,                # integer
            "mult": 2.0,                 # number
            "overlay": True,             # boolean
        }
    }
    schema = _derive_schema_from_widget(spec)
    props = schema["properties"]
    assert props["source"]["type"] == "string"
    assert props["length"]["type"] == "integer"
    assert props["mult"]["type"] == "number"
    assert props["overlay"]["type"] == "boolean"


def test_derive_schema_from_widget_handles_missing_params() -> None:
    """A widget with no ``params`` still yields a valid empty schema."""
    schema = _derive_schema_from_widget({})
    assert schema == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": True,
    }


def test_json_type_of_boolean_before_integer() -> None:
    """``bool`` is a subclass of ``int`` in Python — the mapper must check
    bool FIRST or every boolean would surface as integer."""
    assert _json_type_of(True) == "boolean"
    assert _json_type_of(False) == "boolean"
    assert _json_type_of(0) == "integer"
    assert _json_type_of(1) == "integer"


def test_json_type_of_list_and_dict() -> None:
    assert _json_type_of([1, 2, 3]) == "array"
    assert _json_type_of({"k": "v"}) == "object"


def test_json_type_of_unknown_falls_back_to_string() -> None:
    """Unknown types are conservatively mapped to string — the pine-run
    endpoint's own validator does the strict typing."""

    class WeirdType:
        pass

    assert _json_type_of(WeirdType()) == "string"


# ---------------------------------------------------------------------------
# Dispatch stub — M1 posture is NotImplementedError, not silent success.
# ---------------------------------------------------------------------------


def test_dispatch_raises_not_implemented_at_m1() -> None:
    """The real dispatch body lands at M4 — hitting the stub must raise
    loudly so a live MCP server never returns stale data."""
    spec = {"params": {"symbol": "AAPL"}, "endpoint": "/api/v1/pine/run"}
    with pytest.raises(NotImplementedError, match="M4 launch"):
        _dispatch_via_pine_run("pine_test", spec, symbol="MSFT")


def test_dispatch_error_message_lists_merged_params() -> None:
    """The error message includes the merged param keys — surfacing what
    a caller actually sent so debugging a wiring miss is one grep."""
    spec = {"params": {"symbol": "AAPL", "interval": "1d"}}
    with pytest.raises(NotImplementedError) as exc_info:
        _dispatch_via_pine_run(
            "pine_test", spec, symbol="MSFT", start="2024-01-01"
        )
    msg = str(exc_info.value)
    # All three keys — 2 from widget defaults + 1 override — must appear.
    assert "symbol" in msg
    assert "interval" in msg
    assert "start" in msg


# ---------------------------------------------------------------------------
# Structural protocol
# ---------------------------------------------------------------------------


def test_mcp_server_like_protocol_is_satisfied_by_mock() -> None:
    """A plain ``MagicMock`` satisfies the structural protocol — this is
    what unit tests use to avoid pulling openbb-mcp-server as a hard dep."""
    mock_server = MagicMock(spec=MCPServerLike)
    register(mock_server)
    assert mock_server.register_tool.called
