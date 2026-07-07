"""Tests for openbb_agents.mcp_server — tool discovery & schema generation.

These tests exercise the in-process introspection helpers (no stdio transport,
no DB). They verify that public tool functions are auto-discovered, that JSON
schemas are derived from type hints, and that a discovered tool can be invoked.
"""

import sys
from pathlib import Path

# Ensure the extension package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestToolDiscovery:
    def test_collect_tools_finds_public_functions(self):
        from openbb_agents.mcp_server import collect_tools

        tools = collect_tools()
        names = {t["name"] for t in tools}
        # Portfolio tools layer is implemented; these must be registered.
        assert "get_positions" in names
        assert "get_sector_exposure" in names

    def test_private_functions_excluded(self):
        from openbb_agents.mcp_server import collect_tools

        tools = collect_tools()
        names = {t["name"] for t in tools}
        # Underscore-prefixed helpers must never be exposed as tools.
        assert not any(n.startswith("_") for n in names)
        assert "_default_fetch" not in names


class TestSchemaGeneration:
    def test_input_schema_is_valid_json_schema_object(self):
        from openbb_agents.mcp_server import build_input_schema

        def sample(symbol: str, limit: int = 4) -> dict:
            """Sample tool."""
            return {}

        schema = build_input_schema(sample)
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "symbol" in schema["properties"]
        assert schema["properties"]["symbol"]["type"] == "string"
        assert schema["properties"]["limit"]["type"] == "integer"
        # Required params (no default) listed; optional ones not.
        assert "symbol" in schema["required"]
        assert "limit" not in schema["required"]


class TestInvocation:
    def test_call_collected_tool_returns_result(self):
        from openbb_agents.mcp_server import collect_tools

        tools = {t["name"]: t for t in collect_tools()}
        # get_positions accepts an injected _fetch via kwargs passthrough.
        import pandas as pd

        fake = lambda: pd.DataFrame(
            [
                {
                    "symbol": "MSFT",
                    "total_quantity": 1,
                    "total_cost_basis": 1.0,
                    "total_current_value": 2.0,
                    "pct_return": 100.0,
                    "portfolio_weight_pct": 100.0,
                }
            ]
        )
        result = tools["get_positions"]["fn"](_fetch=fake)
        assert isinstance(result, list)
        assert result[0]["symbol"] == "MSFT"


class TestExceptionSanitization:
    """Regression tests for OpenBBTechnical-9ck7 / lq4l — MCP tool exceptions
    must NOT leak paths/creds/DSNs to the LLM client.

    The pre-fix code returned ``json.dumps({"error": str(exc)})`` which
    happily serialized every embedded absolute path, credential fragment,
    DSN string, or HTTP URL from provider errors back to the LLM.

    Fix: return a generic ``{"error": "tool_failed", "tool": name}`` payload
    to the LLM, log the full ``str(exc)`` + traceback locally only.
    """

    _SENTINEL_LEAKY_MESSAGE = (
        "Connection to mysql://admin:S3CR3T@db.internal:3306/prod failed at "
        "C:/Users/daaji/AppData/openbb/cache.db with key sk-live-ABC123XYZ"
    )

    def test_call_tool_safe_returns_generic_error_on_exception(self):
        """A raising tool returns ``{'error': 'tool_failed', 'tool': ...}`` only."""
        import json

        from openbb_agents.mcp_server import _call_tool_safe

        def raising_tool(**_kwargs):
            raise RuntimeError(self._SENTINEL_LEAKY_MESSAGE)

        descriptor = {"name": "leaky_tool", "fn": raising_tool}
        result_texts, is_error = _call_tool_safe(descriptor, arguments={"x": 1})

        assert is_error is True, "raising tool must set is_error=True"
        assert len(result_texts) == 1
        payload = json.loads(result_texts[0])
        assert payload == {
            "error": "tool_failed",
            "tool": "leaky_tool",
        }, f"Non-generic error payload leaked: {payload!r}"

    def test_call_tool_safe_does_not_leak_exception_str(self):
        """No fragment of the raised exception message appears in the returned payload."""
        from openbb_agents.mcp_server import _call_tool_safe

        def raising_tool(**_kwargs):
            raise RuntimeError(self._SENTINEL_LEAKY_MESSAGE)

        descriptor = {"name": "leaky_tool", "fn": raising_tool}
        result_texts, _is_error = _call_tool_safe(descriptor, arguments={})
        combined = "\n".join(result_texts)

        # None of the sensitive fragments must appear
        for fragment in (
            "mysql://admin",
            "S3CR3T",
            "db.internal",
            "C:/Users/daaji",
            "openbb/cache.db",
            "sk-live-ABC123XYZ",
        ):
            assert (
                fragment not in combined
            ), f"Sensitive fragment {fragment!r} leaked in payload: {combined!r}"
        # Also rule out class-name / exception-repr leaks
        assert (
            "RuntimeError" not in combined
        ), f"Exception class name leaked in payload: {combined!r}"

    def test_call_tool_safe_logs_full_exception_locally(self, caplog):
        """The FULL exception details (str + traceback) are logged locally.

        Operators need the full error to debug; only the LLM sees the
        generic payload. Tightened Round-1 review feedback: asserts the
        full sentinel message reaches the log (not just any fragment)
        so the operator-debuggability contract is a hard regression lock.
        """
        import logging

        from openbb_agents.mcp_server import _call_tool_safe

        def raising_tool(**_kwargs):
            raise RuntimeError(self._SENTINEL_LEAKY_MESSAGE)

        descriptor = {"name": "leaky_tool", "fn": raising_tool}
        with caplog.at_level(logging.ERROR, logger="openbb_agents.mcp_server"):
            _call_tool_safe(descriptor, arguments={})

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR-level log record"
        combined_log = (
            "\n".join(r.getMessage() for r in error_records)
            + "\n"
            + "\n".join((r.exc_text or "") for r in error_records)
        )
        # Hard invariant: the FULL sentinel message must be in the log.
        assert (
            self._SENTINEL_LEAKY_MESSAGE in combined_log
        ), f"Full exception details not logged locally: {combined_log!r}"
        # And the tool name must be in the log for operator triage
        assert "leaky_tool" in combined_log

    def test_call_tool_safe_happy_path_returns_json_result(self):
        """Non-raising tool returns json-serialized result + is_error=False."""
        import json

        from openbb_agents.mcp_server import _call_tool_safe

        def good_tool(x: int):
            return {"doubled": x * 2}

        descriptor = {"name": "good_tool", "fn": good_tool}
        result_texts, is_error = _call_tool_safe(descriptor, arguments={"x": 21})
        assert is_error is False, "happy-path tool must set is_error=False"
        assert len(result_texts) == 1
        assert json.loads(result_texts[0]) == {"doubled": 42}

    def test_call_tool_safe_generic_error_on_unknown_tool_name(self):
        """Unknown tool → generic error + is_error=True, no name-injection leak."""
        import json

        from openbb_agents.mcp_server import _call_tool_safe

        # Descriptor None means the tool wasn't found — the wrapper should
        # still return the generic error shape + is_error=True, not raise.
        result_texts, is_error = _call_tool_safe(None, arguments={}, name="ghost_tool")
        assert is_error is True, "unknown-tool branch must set is_error=True"
        payload = json.loads(result_texts[0])
        assert payload == {"error": "unknown_tool", "tool": "ghost_tool"}

    def test_call_tool_safe_json_dumps_failure_is_sanitized(self):
        """A tool returning a non-JSON-serializable value falls through to the sanitized path.

        Round-1 review INFO note: json.dumps sits inside the try, so a
        TypeError raised there (e.g., set/complex return that even
        default=str can't handle) is caught by the same except Exception
        and returns the generic error payload — no leak.
        """
        import json

        from openbb_agents.mcp_server import _call_tool_safe

        def unserializable_tool():
            # A class instance without __str__ / __repr__ raising
            class Weird:
                def __str__(self):
                    raise RuntimeError(
                        "S3CR3T from failed __str__ at C:/Users/daaji/leak"
                    )

                __repr__ = __str__

            return {"weird": Weird()}

        descriptor = {"name": "unserializable_tool", "fn": unserializable_tool}
        result_texts, is_error = _call_tool_safe(descriptor, arguments={})
        assert is_error is True
        payload = json.loads(result_texts[0])
        # Generic tag, no fragments from the failed __str__
        assert payload == {"error": "tool_failed", "tool": "unserializable_tool"}
        assert "S3CR3T" not in result_texts[0]
        assert "C:/Users/daaji" not in result_texts[0]


class TestMcpToolErrorWireContract:
    """Round-2 review: an end-to-end round-trip through the actual MCP SDK
    to verify that _McpToolError propagates BOTH ``isError=True`` AND the
    sanitized JSON payload to the wire.

    The Round-1 attempt carried payload on ``self.content`` — empirically
    verified to be dropped by the SDK's error path (v1.26+ uses only
    ``str(exc)``). This test locks in the corrected shape: exception
    message IS the sanitized payload, so both properties hold.
    """

    _SENTINEL_KEY = "SENTINEL_ROUND2_KEY_MUST_NOT_LEAK"

    def _make_error(self, payload: str):
        from openbb_agents.mcp_server import _McpToolError

        return _McpToolError(payload)

    def test_mcp_tool_error_str_equals_payload(self):
        """The exception's str() IS the sanitized JSON payload.

        The MCP SDK's ``_make_error_result(str(exc))`` (v1.26+) is what
        builds the wire response text. So ``str(exc)`` must be the JSON
        payload, not a fixed marker string.
        """
        payload = '{"error": "tool_failed", "tool": "my_tool"}'
        exc = self._make_error(payload)
        assert str(exc) == payload

    def test_mcp_tool_error_does_not_leak_sentinel(self):
        """Nothing in the exception surface exposes anything except the payload.

        The payload itself must be the sanitized shape — verified
        upstream by the ``_call_tool_safe`` tests. Here we confirm the
        exception doesn't smuggle extra state via ``args`` or ``__dict__``.
        """
        payload = f'{{"error": "tool_failed", "tool": "{self._SENTINEL_KEY}_tool"}}'
        exc = self._make_error(payload)
        assert self._SENTINEL_KEY not in "".join(map(str, exc.args)) or (
            self._SENTINEL_KEY in payload
        )  # payload itself may reference sentinel — that's fine, it's already-sanitized
        # Extra sentinel-in-attrs check: only args should carry the payload
        for attr_name in dir(exc):
            if attr_name.startswith("_"):
                continue
            if attr_name == "args":
                continue
            attr_val = getattr(exc, attr_name)
            if callable(attr_val):
                continue
            # No non-args attribute should carry the sentinel unless it's
            # inherited exception plumbing (str, repr, etc.)
            if attr_name in {"add_note", "with_traceback"}:
                continue
            assert self._SENTINEL_KEY not in str(
                attr_val or ""
            ), f"Attribute {attr_name!r} leaked sentinel: {attr_val!r}"

    def test_end_to_end_mcp_call_tool_wraps_isError_and_payload(self):
        """Round-trip through the MCP SDK: raising _McpToolError yields
        ``isError=True`` AND the sanitized JSON payload as wire content.

        Round-2 review demanded this: without an end-to-end test the
        assumption that ``_McpToolError.content`` reached the wire was
        never verified in-repo. The current shape (exception message
        IS the payload) is the only shape the SDK's error path actually
        surfaces to the client.
        """
        import asyncio
        import json

        try:
            from mcp.server import Server
            from mcp.types import CallToolRequest, CallToolRequestParams
        except ImportError:
            import pytest as _pytest

            _pytest.skip("mcp SDK not installed in this env")

        from openbb_agents.mcp_server import _McpToolError

        server: "Server" = Server("test-openbb-agents")

        @server.call_tool()
        async def call_tool(name: str, arguments: dict):
            # Force the error path with a sanitized payload
            raise _McpToolError(json.dumps({"error": "tool_failed", "tool": name}))

        # Dispatch a CallToolRequest through the SDK's request handler
        handler = server.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="probe_tool", arguments={"x": 1}),
        )
        result = asyncio.get_event_loop().run_until_complete(handler(request))

        # SDK wraps the exception into a ServerResult carrying CallToolResult
        # with isError=True and the exception's str() as the text content.
        inner = getattr(result, "root", result)  # ServerResult wrapper
        assert (
            getattr(inner, "isError", False) is True
        ), f"expected isError=True, got {inner!r}"
        # Content should carry the sanitized payload text
        content_texts = [
            getattr(c, "text", str(c)) for c in getattr(inner, "content", [])
        ]
        combined = "\n".join(content_texts)
        # The payload sees the wire
        assert "tool_failed" in combined, f"sanitized payload not on wire: {combined!r}"
        assert "probe_tool" in combined, f"tool name not on wire: {combined!r}"
