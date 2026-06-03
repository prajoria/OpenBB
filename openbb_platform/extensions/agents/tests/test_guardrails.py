"""Tests for openbb_agents.guardrails — PII redaction (no DB, no LLM).

The redaction core (`redact_pii`) is a pure function over a state dict so it can
be tested without constructing a real ADK CallbackContext. The
`pii_redaction_callback` wrapper is exercised with a lightweight fake context.
"""

import sys
from pathlib import Path

# Ensure the extension package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeSession:
    def __init__(self, state):
        self.state = state


class _FakeCtx:
    """Mimics ADK CallbackContext.session.state access used by the callback."""

    def __init__(self, state=None):
        self.session = _FakeSession(state if state is not None else {})


class TestAccountRedaction:
    def test_alphanumeric_account_redacted(self):
        from openbb_agents.guardrails import redact_pii

        state: dict = {}
        out = redact_pii("Account Z12345678 holds 100 shares", state)
        assert "Z12345678" not in out
        assert "<ACCT-1>" in out

    def test_bare_numeric_account_redacted(self):
        from openbb_agents.guardrails import redact_pii

        state: dict = {}
        out = redact_pii("Routing to 1234567890 complete", state)
        assert "1234567890" not in out
        assert "<ACCT-1>" in out

    def test_same_account_gets_stable_token(self):
        from openbb_agents.guardrails import redact_pii

        state: dict = {}
        first = redact_pii("acct Z12345678 here", state)
        second = redact_pii("again Z12345678 there", state)
        # Same raw account → same token across calls in the same session
        assert "<ACCT-1>" in first
        assert "<ACCT-1>" in second

    def test_distinct_accounts_get_distinct_tokens(self):
        from openbb_agents.guardrails import redact_pii

        state: dict = {}
        out = redact_pii("A12345678 and B87654321 differ", state)
        assert "<ACCT-1>" in out
        assert "<ACCT-2>" in out
        assert "A12345678" not in out
        assert "B87654321" not in out


class TestOwnerRedaction:
    def test_known_owner_redacted(self):
        from openbb_agents.guardrails import redact_pii

        state = {"_known_owners": ["Alice Johnson"]}
        out = redact_pii("Owner Alice Johnson bought shares", state)
        assert "Alice Johnson" not in out
        assert "<OWNER-REDACTED>" in out

    def test_short_owner_string_not_redacted(self):
        from openbb_agents.guardrails import redact_pii

        # Names of length <= 2 are ignored to avoid over-redaction
        state = {"_known_owners": ["Al"]}
        out = redact_pii("Al went to the market", state)
        assert "<OWNER-REDACTED>" not in out


class TestDollarRedaction:
    def test_dollar_amount_not_redacted_by_default(self):
        from openbb_agents.guardrails import redact_pii

        state: dict = {}
        out = redact_pii("Position worth $12,345.67 today", state)
        assert "$12,345.67" in out

    def test_dollar_amount_redacted_when_opted_in(self):
        from openbb_agents.guardrails import redact_pii

        state: dict = {}
        out = redact_pii("Position worth $12,345.67 today", state, redact_dollars=True)
        assert "$12,345.67" not in out
        assert "<AMOUNT-REDACTED>" in out


class TestCallbackWrapper:
    def test_callback_redacts_via_session_state(self):
        from openbb_agents.guardrails import pii_redaction_callback

        ctx = _FakeCtx({"_known_owners": ["Bob Smith"]})
        out = pii_redaction_callback(ctx, "Bob Smith on Z12345678")
        assert "Bob Smith" not in out
        assert "Z12345678" not in out
        assert "<OWNER-REDACTED>" in out
        assert "<ACCT-1>" in out

    def test_callback_initializes_pii_map(self):
        from openbb_agents.guardrails import pii_redaction_callback

        ctx = _FakeCtx({})
        pii_redaction_callback(ctx, "acct Z12345678")
        assert "_pii_map" in ctx.session.state
