"""Custom-copilot backend for OpenBB Workspace (#1794).

Implements the OpenBB Workspace *agent* HTTP contract so the hosted Workspace
Copilot can be pointed at a **local** backend that answers using the local
``copilot-api`` proxy on ``127.0.0.1:4141`` (GitHub Copilot models exposed as an
OpenAI-compatible API) instead of the OpenBB-hosted LLM.

Two routes, mounted on the existing portfolio backend (``launch.py`` on
``https://127.0.0.1:6902``) so they reuse the already-trusted self-signed cert
and the CORS origin Workspace already talks to:

* ``GET  /agents.json`` — agent descriptor (name, features, query URL).
* ``POST /query``       — accepts a ``QueryRequest`` and streams the answer back
  as ``copilotMessageChunk`` Server-Sent Events.

The LLM call is a plain streaming ``chat.completions`` request whose base URL is
swapped to the proxy — see :func:`_proxy_deltas`. Everything is configurable via
environment variables so a different OpenAI-compatible endpoint (or model) can be
used without code changes.

v1 scope is deliberately text-only: ``human``/``ai`` history is forwarded and the
streamed answer is returned. Widget/dashboard-context ingestion, reasoning-step
events, citations and artifacts are follow-up work.

.. note::
    This module intentionally does **not** use ``from __future__ import
    annotations`` — but for a different reason than the core routers (#1788): it
    keeps runtime type resolution simple for the FastAPI ``QueryRequest`` body
    parameter. It is a plain ``fastapi.APIRouter``, not an ``openbb_core``
    ``Router.command``.
"""

import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import openai
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from openbb_ai import message_chunk
from openbb_ai.models import QueryRequest
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Identity + descriptor
# ---------------------------------------------------------------------------
COPILOT_ID = "portfolio_copilot_proxy"
COPILOT_NAME = "Portfolio Copilot (local proxy)"
COPILOT_DESCRIPTION = (
    "Answers using your local GitHub Copilot proxy (copilot-api on :4141) "
    "instead of the OpenBB-hosted model. Surfaces data and analysis only — "
    "it does not give investment advice."
)

# A restrained system prompt. The portfolio program guardrails forbid
# buy/sell/hold recommendations, so the copilot describes and explains only.
SYSTEM_PROMPT = (
    "You are the OpenBB Portfolio Copilot. You help the user understand "
    "financial data, portfolios, and single-stock analysis shown in OpenBB "
    "Workspace. Be concise and factual. Never give investment advice or "
    "buy/sell/hold recommendations; surface and explain data instead."
)


# ---------------------------------------------------------------------------
# Configuration (env-overridable — never hardcode secrets)
# ---------------------------------------------------------------------------
def _proxy_base_url() -> str:
    """OpenAI-compatible base URL for the LLM proxy (default copilot-api :4141)."""
    return os.getenv("COPILOT_PROXY_BASE_URL", "http://127.0.0.1:4141/v1")


def _proxy_api_key() -> str:
    """Return the API key sent to the proxy (copilot-api accepts ``copilot``)."""
    return os.getenv("COPILOT_PROXY_API_KEY", "copilot")


def _proxy_model() -> str:
    """Model id requested from the proxy.

    The copilot-api proxy accepts any id and routes to its configured Copilot
    model, so this is mostly a label; override with ``COPILOT_PROXY_MODEL`` to
    target a specific model on a compliant endpoint.
    """
    return os.getenv("COPILOT_PROXY_MODEL", "gpt-4o")


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------
def agents_descriptor(query_url: str) -> dict:
    """Return the ``/agents.json`` descriptor for this copilot."""
    return {
        COPILOT_ID: {
            "name": COPILOT_NAME,
            "description": COPILOT_DESCRIPTION,
            "endpoints": {"query": query_url},
            "features": {
                "streaming": True,
                "widget-dashboard-select": False,
                "widget-dashboard-search": False,
            },
        }
    }


@router.get("/agents.json", include_in_schema=False)
async def agents_json(request: Request) -> JSONResponse:
    """Serve the agent descriptor.

    The query URL is derived from the incoming request so the descriptor is
    correct regardless of the host/port/scheme the backend is served on.
    """
    base = str(request.base_url).rstrip("/")
    return JSONResponse(content=agents_descriptor(f"{base}/query"))


# ---------------------------------------------------------------------------
# Message mapping
# ---------------------------------------------------------------------------
def _to_openai_messages(messages) -> list[dict]:
    """Map the Workspace conversation to OpenAI chat-completion messages.

    ``human`` -> ``user``, ``ai`` -> ``assistant``. Tool/function-call messages
    (non-``str`` content) are skipped in v1. The system prompt is prepended.
    """
    out: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for message in messages:
        role = getattr(message.role, "value", message.role)
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            # Function-call requests / tool results are not handled in v1.
            continue
        if role == "human":
            out.append({"role": "user", "content": content})
        elif role == "ai":
            out.append({"role": "assistant", "content": content})
        # role == "tool" (and anything else) is intentionally ignored.
    return out


# ---------------------------------------------------------------------------
# Proxy streaming (the seam — monkeypatched in unit tests)
# ---------------------------------------------------------------------------
async def _proxy_deltas(
    openai_messages: list[dict],
    client: Any = None,
) -> AsyncGenerator[str, None]:
    """Yield text deltas from the LLM proxy for the given messages.

    ``client`` is injectable for testing; when omitted a fresh
    ``openai.AsyncOpenAI`` pointed at the proxy is created.
    """
    owns_client = client is None
    if client is None:
        client = openai.AsyncOpenAI(
            base_url=_proxy_base_url(), api_key=_proxy_api_key()
        )

    # Close a self-created client (and its httpx connection pool) on normal
    # completion, on error, and on cancellation (client disconnect throws
    # ``GeneratorExit``/``CancelledError`` into this generator). Without this
    # each ``/query`` would leak a connection pool until GC.
    try:
        stream = await client.chat.completions.create(
            model=_proxy_model(),
            messages=openai_messages,
            stream=True,
        )
        async for event in stream:
            if not getattr(event, "choices", None):
                continue
            delta = event.choices[0].delta.content
            if delta:
                yield delta
    finally:
        if owns_client:
            await client.close()


async def _sse_stream(messages) -> AsyncGenerator[dict, None]:
    """Stream ``copilotMessageChunk`` SSE dicts for a conversation."""
    openai_messages = _to_openai_messages(messages)
    emitted = False
    failed = False
    try:
        async for delta in _proxy_deltas(openai_messages):
            emitted = True
            yield message_chunk(delta).model_dump(exclude_none=True)
    except Exception as exc:  # noqa: BLE001 — surface any proxy failure to the user
        # A connection-refused / API error (e.g. proxy down) raises here rather
        # than yielding an empty stream. ``EventSourceResponse`` has already sent
        # the 200 + SSE headers, so we cannot change the status code — instead we
        # emit a user-visible fallback chunk (below) so Workspace shows a message
        # rather than a silently broken empty stream.
        failed = True
        logger.warning(
            "copilot proxy at %s failed for a %d-message conversation: %s: %s",
            _proxy_base_url(),
            len(openai_messages),
            type(exc).__name__,
            exc,
        )

    if not emitted:
        if not failed:
            # Loud empty: a non-empty conversation that produces no tokens (proxy
            # up but returning nothing) almost always means a misconfiguration.
            logger.warning(
                "copilot proxy at %s returned no content for a %d-message "
                "conversation — check the proxy is running and the model is valid",
                _proxy_base_url(),
                len(openai_messages),
            )
        yield message_chunk(
            "(No response from the local model proxy. Is copilot-api running "
            "on :4141?)"
        ).model_dump(exclude_none=True)


@router.post("/query", include_in_schema=False)
async def query(request: QueryRequest) -> EventSourceResponse:
    """Stream an answer for the conversation via the local Copilot proxy."""
    return EventSourceResponse(
        content=_sse_stream(request.messages),
        media_type="text/event-stream",
    )


__all__ = [
    "router",
    "agents_descriptor",
    "COPILOT_ID",
    "COPILOT_NAME",
]
