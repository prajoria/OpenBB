"""AgentBackend Protocol + ClaudeAgentBackend + AlwaysUnavailableBackend.

Three-layer design:

1. :class:`AgentBackend` (Protocol) — the interface every backend must
   satisfy. Callers depend on this shape, not on any concrete backend.
2. :class:`ClaudeAgentBackend` — the real Anthropic SDK backend (D1).
   Requires the ``[agent]`` extra. Delegates forced-tool-calling to
   ``messages.create`` with ``tool_choice={"type":"tool", "name":...}``.
3. :class:`AlwaysUnavailableBackend` — unconditional-fallback backend
   for tests and air-gapped operators (renamed from
   ``DeterministicFallbackBackend`` per A11 to avoid "clever but easy
   to misread" naming).

The backend abstraction is deliberately narrow: one method
(:meth:`AgentBackend.run_turn`), one return type (:class:`ToolCall`).
No session state, no caching, no retry policy at this layer — the turn
wrappers (``pre_open.py``, ``post_close.py``) own the retry loop and
the fallback decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from openbb_fmp_trading.agent.errors import AgentUnavailable


@dataclass
class ToolCall:
    """The final tool call the backend was forced to emit.

    Attributes:
        name:            Tool name (matches ``required_final_tool``
                         arg passed to :meth:`AgentBackend.run_turn`).
        args:            Tool arguments, a plain dict. The turn wrapper
                         validates these with
                         ``DailyPlan.model_validate(args)`` /
                         ``EndOfDayReport.model_validate(args)``.
        model_id:        Model identifier reported by the SDK
                         (``response.model``). Journaled on the
                         :class:`DailyPlanCommittedEvent` for audit (A6).
        input_tokens:    Actual input tokens per ``response.usage``.
                         Fed to :meth:`BandwidthMeter.reconcile` (A4).
        output_tokens:   Actual output tokens per ``response.usage``.
        tool_call_count: Number of tool-call round-trips consumed. Bounded
                         by ``max_iterations``; useful for cost telemetry (A4/A9).
    """

    name: str
    args: dict[str, Any]
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_call_count: int = 1


class AgentBackend(Protocol):
    """One-shot LLM call with forced structured output via a required final tool.

    Stateless: no session mgmt, no caching. Implementations MUST honor
    ``temperature`` and ``max_iterations`` as hard caps — the turn
    wrappers depend on these bounds for reproducibility (A6) and cost
    control (A4).

    Return contract: a :class:`ToolCall` whose ``args`` are the arguments
    the model passed to ``required_final_tool``. On failure (network,
    API error, refusal to emit the required tool, malformed args
    unrecoverable at the SDK layer), raise :class:`AgentUnavailable`.
    Never return a partial or fallback result — that decision belongs
    to the turn wrapper.
    """

    def run_turn(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        required_final_tool: str,
        budget: Any = None,
        temperature: float = 0.0,
        max_iterations: int = 8,
        max_tokens: int = 4096,
    ) -> ToolCall:
        ...


@dataclass
class ClaudeAgentBackend:
    """Real backend using the Anthropic Claude Agent SDK (D1).

    Requires ``pip install openbb-fmp-trading[agent]``. Missing SDK
    manifests as :class:`AgentUnavailable` at construction time — the
    turn wrapper's fallback path is identical whether the SDK is
    missing, network is down, or the API rejected the call.

    Loops until the model calls ``required_final_tool`` or
    ``max_iterations`` is exhausted. Each iteration executes any
    intermediate read-only tool calls (movers, snapshots, news) by
    dispatching through :func:`tool_registry.dispatch`; the model sees
    tool results and eventually converges on the forced final tool.
    """

    model: str = "claude-sonnet-4-5"

    def __post_init__(self) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise AgentUnavailable(
                "install openbb-fmp-trading[agent] to use ClaudeAgentBackend"
            ) from exc
        # Anthropic() reads ANTHROPIC_API_KEY from env — never journaled,
        # never in prompts (6.3 API-key handling invariant).
        self._client = Anthropic()

    def run_turn(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        required_final_tool: str,
        budget: Any = None,
        temperature: float = 0.0,
        max_iterations: int = 8,
        max_tokens: int = 4096,
    ) -> ToolCall:
        """Execute the forced-tool-calling loop.

        Real body deferred to the P3.1 GREEN pass; for the initial spec
        implementation we ship the interface + AlwaysUnavailableBackend
        for testing and defer the live SDK loop to the ``[agent]``
        installation path. Tests for pre_open.py inject
        :class:`AlwaysUnavailableBackend` or a ``MagicMock`` typed as
        :class:`AgentBackend` — no live Claude call happens in CI (A5).
        """
        # NOTE: the messages.create loop with tool_choice={"type":"tool",
        # "name":required_final_tool} + tool-result round-trips lives
        # here. Body intentionally minimal for the shipping unit — the
        # AC-1-ext integration test in P3.3 exercises this path via a
        # canned/recorded backend, not a live call.
        raise AgentUnavailable(
            "ClaudeAgentBackend.run_turn body ships in P3.3 with the "
            "canned-backend integration harness. Use AlwaysUnavailableBackend "
            "or a MagicMock for unit testing."
        )


@dataclass
class AlwaysUnavailableBackend:
    """Unconditional-fallback backend. Raises :class:`AgentUnavailable`
    on every call.

    Renamed from ``DeterministicFallbackBackend`` per design-review
    A11 — the old name implied "runs the deterministic path" when
    actually it just refuses to run at all, forcing the turn wrapper's
    own fallback branch to fire.

    Two use cases:

    * **Tests:** :class:`PreOpenAgentTurn` constructed with this backend
      exercises the fallback branch without importing anthropic.
    * **Air-gapped ops:** operators who explicitly do NOT want an LLM
      call today (bandwidth-conservation mode, cost-freeze period) can
      wire this backend and the two turns will still produce valid
      ``DailyPlan`` / ``EndOfDayReport`` objects via the deterministic
      fallback paths.
    """

    def run_turn(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        required_final_tool: str,
        budget: Any = None,
        temperature: float = 0.0,
        max_iterations: int = 8,
        max_tokens: int = 4096,
    ) -> ToolCall:
        raise AgentUnavailable(
            "AlwaysUnavailableBackend refuses every call by design"
        )


__all__ = [
    "AgentBackend",
    "AlwaysUnavailableBackend",
    "ClaudeAgentBackend",
    "ToolCall",
]
