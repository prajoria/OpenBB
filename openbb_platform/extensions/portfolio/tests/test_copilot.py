"""Unit + integration tests for the custom-copilot backend (#1794).

The copilot backend implements the OpenBB Workspace agent HTTP contract
(``/agents.json`` + ``/query``) and streams answers from the local
``copilot-api`` proxy on ``127.0.0.1:4141``.

Unit tests exercise the real code path with a fake OpenAI stream (no live
proxy). The single ``@pytest.mark.integration`` test hits the real proxy and
is skipped when it is unreachable.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import pytest
from openbb_portfolio import copilot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _query_request(messages: list[dict]):
    """Build a real ``QueryRequest`` from role/content dicts."""
    from openbb_ai.models import QueryRequest

    return QueryRequest(messages=messages)


async def _collect(agen: AsyncGenerator) -> list:
    return [item async for item in agen]


# ---------------------------------------------------------------------------
# _to_openai_messages — role mapping (discriminating: wrong mapping fails)
# ---------------------------------------------------------------------------
def test_to_openai_messages_maps_human_and_ai_roles():
    """Human -> user, ai -> assistant, in order, with system prompt prepended."""
    req = _query_request(
        [
            {"role": "human", "content": "What is MSFT's PE ratio?"},
            {"role": "ai", "content": "MSFT trades around 35x."},
            {"role": "human", "content": "Is that high?"},
        ]
    )
    out = copilot._to_openai_messages(req.messages)

    # System prompt is prepended, then the mapped history in order.
    assert out[0]["role"] == "system"
    assert out[1] == {"role": "user", "content": "What is MSFT's PE ratio?"}
    assert out[2] == {"role": "assistant", "content": "MSFT trades around 35x."}
    assert out[3] == {"role": "user", "content": "Is that high?"}
    assert len(out) == 4


def test_to_openai_messages_skips_non_text_tool_messages():
    """Function-call / tool-result messages (non-str content) are dropped in v1.

    Discriminating: a naive ``str(content)`` mapping would append a 4th
    (garbage) message; the correct code skips it, leaving system+user only.
    """
    from openbb_ai.models import (
        LlmClientFunctionCall,
        LlmClientMessage,
        RoleEnum,
    )

    fn_call = LlmClientMessage(
        role=RoleEnum.ai,
        content=LlmClientFunctionCall(function="get_widget_data", input_arguments={}),
    )
    messages = [
        LlmClientMessage(role=RoleEnum.human, content="Summarize my portfolio"),
        fn_call,
    ]
    out = copilot._to_openai_messages(messages)

    roles = [m["role"] for m in out]
    assert roles == ["system", "user"]  # the function-call message is skipped
    assert all(isinstance(m["content"], str) for m in out)


# ---------------------------------------------------------------------------
# _sse_stream — wraps proxy deltas as copilotMessageChunk SSE events
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sse_stream_wraps_deltas_as_copilot_message_chunks(monkeypatch):
    """Each proxy delta becomes one copilotMessageChunk SSE event, in order."""
    async def fake_deltas(_openai_messages):  # noqa: ANN001
        for piece in ["Hello", ", ", "world"]:
            yield piece

    monkeypatch.setattr(copilot, "_proxy_deltas", fake_deltas)

    req = _query_request([{"role": "human", "content": "hi"}])
    events = await _collect(copilot._sse_stream(req.messages))

    # Every event is a copilotMessageChunk carrying one delta.
    assert [e["event"] for e in events] == ["copilotMessageChunk"] * 3
    import json

    deltas = [json.loads(e["data"])["delta"] for e in events]
    assert deltas == ["Hello", ", ", "world"]


@pytest.mark.asyncio
async def test_sse_stream_loud_empty_when_proxy_yields_nothing(monkeypatch, caplog):
    """R7.3/R7.9: empty proxy output must log a WARNING (the load-bearing signal).

    Reverse-verify: if the loud-empty branch is removed, the warning count
    drops to 0 and this test fails.
    """

    async def empty_deltas(_openai_messages):  # noqa: ANN001
        return
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(copilot, "_proxy_deltas", empty_deltas)

    req = _query_request([{"role": "human", "content": "hi"}])
    with caplog.at_level(logging.WARNING, logger="openbb_portfolio.copilot"):
        events = await _collect(copilot._sse_stream(req.messages))

    warnings = [
        r for r in caplog.records if "no content" in r.getMessage().lower()
    ]
    assert len(warnings) == 1, "empty proxy output must emit exactly one WARNING"
    # A fallback chunk is still streamed so the user sees something.
    assert events and events[0]["event"] == "copilotMessageChunk"


@pytest.mark.asyncio
async def test_sse_stream_emits_fallback_when_proxy_raises(monkeypatch, caplog):
    """Proxy-down (connection error) must log a WARNING and emit a fallback chunk.

    Reverse-verify: without the try/except around ``_proxy_deltas`` this raises
    out of the generator and Workspace gets a silently-broken empty stream (no
    fallback chunk, test fails on the assert below).
    """

    async def raising_deltas(_openai_messages):  # noqa: ANN001
        raise ConnectionError("connection refused to :4141")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(copilot, "_proxy_deltas", raising_deltas)

    req = _query_request([{"role": "human", "content": "hi"}])
    with caplog.at_level(logging.WARNING, logger="openbb_portfolio.copilot"):
        events = await _collect(copilot._sse_stream(req.messages))

    failures = [r for r in caplog.records if "failed" in r.getMessage().lower()]
    assert len(failures) == 1, "proxy failure must emit exactly one WARNING"
    # The user still sees a fallback message rather than a broken empty stream.
    assert len(events) == 1
    assert events[0]["event"] == "copilotMessageChunk"
    import json

    assert "copilot-api" in json.loads(events[0]["data"])["delta"]


@pytest.mark.asyncio
async def test_proxy_deltas_closes_self_created_client(monkeypatch):
    """A client created inside ``_proxy_deltas`` is closed on completion.

    Reverse-verify: dropping the ``finally: await client.close()`` leaves
    ``closed`` False and this test fails — the connection pool would leak.
    """
    closed = {"value": False}

    class _FakeChunk:
        class _Choice:
            class _Delta:
                content = "hi"

            delta = _Delta()

        choices = [_Choice()]

    class _FakeStream:
        def __aiter__(self):
            async def _gen():
                yield _FakeChunk()

            return _gen()

    class _FakeCompletions:
        async def create(self, **_kwargs):
            return _FakeStream()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeAsyncOpenAI:
        def __init__(self, **_kwargs):
            self.chat = _FakeChat()

        async def close(self):
            closed["value"] = True

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)

    deltas = [d async for d in copilot._proxy_deltas([{"role": "user", "content": "x"}])]
    assert deltas == ["hi"]
    assert closed["value"] is True, "self-created client must be closed"


# ---------------------------------------------------------------------------
# /agents.json descriptor
# ---------------------------------------------------------------------------
def test_agents_descriptor_shape():
    """The descriptor exposes the copilot id, query URL and streaming feature."""
    desc = copilot.agents_descriptor("https://127.0.0.1:6902/query")
    assert len(desc) == 1
    (agent_id, meta), = desc.items()
    assert agent_id == copilot.COPILOT_ID
    assert meta["endpoints"]["query"] == "https://127.0.0.1:6902/query"
    assert meta["features"]["streaming"] is True
    assert "name" in meta and "description" in meta


def test_agents_json_route_builds_query_url_from_request():
    """GET /agents.json returns 200 with a request-derived query URL."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(copilot.router)
    client = TestClient(app)

    resp = client.get("/agents.json")
    assert resp.status_code == 200
    body = resp.json()
    meta = body[copilot.COPILOT_ID]
    # The query URL is derived from the request base URL, not hardcoded.
    assert meta["endpoints"]["query"].endswith("/query")


# ---------------------------------------------------------------------------
# Integration — live proxy round-trip (skipped when 4141 unreachable)
# ---------------------------------------------------------------------------
def _proxy_reachable() -> bool:
    import httpx

    base = copilot._proxy_base_url().rstrip("/")
    # /v1/models on the copilot-api proxy
    url = base + "/models" if base.endswith("/v1") else base + "/v1/models"
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {copilot._proxy_api_key()}"}, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _proxy_reachable(), reason="copilot-api proxy not reachable on :4141")
@pytest.mark.asyncio
async def test_query_streams_live_from_proxy():
    """Integration: the live proxy streams non-empty copilotMessageChunk text."""
    req = _query_request(
        [{"role": "human", "content": "Reply with exactly the single word: pong"}]
    )
    events = await _collect(copilot._sse_stream(req.messages))
    assert events, "expected at least one SSE chunk from the live proxy"
    assert all(e["event"] == "copilotMessageChunk" for e in events)

    import json

    text = "".join(json.loads(e["data"])["delta"] for e in events)
    assert text.strip(), "live proxy returned empty text"
