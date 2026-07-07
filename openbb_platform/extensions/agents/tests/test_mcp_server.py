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
