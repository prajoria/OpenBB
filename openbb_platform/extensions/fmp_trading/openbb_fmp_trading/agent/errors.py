"""Agent-layer exception hierarchy (Phase 3).

Every failure mode of the two agent turns raises one of these; the turn
wrappers catch all of them and route to the deterministic fallback. No
uncaught exception should ever escape :meth:`PreOpenAgentTurn.run` or
:meth:`PostCloseAgentTurn.run`.

Design-review lineage:

* :class:`AgentUnavailable` — original design.
* :class:`RiskOverrideLoosening` — T1 (P0). LLM-emitted plan tried to
  loosen risk beyond ``DailyConfig`` defaults.
* :class:`RegistryDrift` — A3 (P0). Tool schema disagrees with router;
  raised at test-time / mcp-serve startup, NEVER at module import.
* :class:`InjectionRejected` — A1 (P0). Post-LLM validator rejected
  something the model emitted (out-of-universe symbol, oversized
  watchlist, etc.). Caught by the turn wrapper same as ValidationError.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent-layer failures. Caught by turn wrappers."""


class AgentUnavailable(AgentError):
    """LLM call impossible.

    Raised when:

    * ``[agent]`` extra missing (``anthropic`` / ``mcp`` uninstalled)
    * API call fails after the SDK's own retries
    * :class:`AlwaysUnavailableBackend` is in use (test / air-gapped mode)
    * ``BandwidthMeter`` mode is ``halted`` or ``conservation`` and the
      turn opted to skip rather than proceed

    Turn wrapper catches this and falls through to the deterministic
    fallback identically whether the extra is missing or the network died.
    """


class RiskOverrideLoosening(AgentError):
    """T1 (P0): the LLM returned a ``DailyPlan`` whose ``session_risk``
    loosens the ``DailyConfig`` defaults (bigger position size, wider
    max_daily_loss, etc.).

    Never passed through — the turn wrapper retries once with the error
    surfaced back to the model, then falls through to the deterministic
    fallback. This is a load-bearing safety invariant, not a validation
    nicety.
    """


class InjectionRejected(AgentError):
    """A1 (P0): a post-LLM defense validator rejected an LLM-emitted
    field (out-of-universe symbol, oversized watchlist, unknown preset).

    Attributes carry the offending field + value for the audit trail
    (:class:`PromptInjectionRejectedEvent`).
    """

    def __init__(self, defense_layer: str, field: str, offending_value):
        self.defense_layer = defense_layer
        self.field = field
        self.offending_value = offending_value
        super().__init__(
            f"{defense_layer} rejected {field}={offending_value!r}"
        )


class RegistryDrift(AgentError):
    """A tool schema in :mod:`tool_registry` disagrees with the current
    ``obb.fmp_trading.*`` router signature.

    Raised by :func:`assert_no_drift` at test-time and at
    ``mcp-serve`` startup. **NEVER** at module import time (A3 P0) —
    that would break ``import openbb`` for users without the ``[agent]``
    extra.
    """


__all__ = [
    "AgentError",
    "AgentUnavailable",
    "InjectionRejected",
    "RegistryDrift",
    "RiskOverrideLoosening",
]
