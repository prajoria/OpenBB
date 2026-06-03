"""PII redaction guardrail for OpenBB Agents.

Keeps raw PII (account numbers, owner names, optionally dollar amounts) out of
the LLM context window. Wired into ADK agents as a ``before_model_callback`` /
tool-response post-processor.

Two entry points:

- :func:`redact_pii` — pure function over a mutable ``state`` dict. No ADK
  dependency, fully unit-testable.
- :func:`pii_redaction_callback` — thin wrapper that reads/writes
  ``ctx.session.state`` so it can be registered with an ADK agent.

Redaction rules (see DESIGN.md §7.2):

==================  ====================================  ==================
PII type            Detection                             Replacement
==================  ====================================  ==================
Account (alpha-num) ``[A-Z]{1,2}-?\\d{6,12}``             ``<ACCT-N>`` (stable)
Account (numeric)   ``\\d{10,12}``                        ``<ACCT-N>`` (stable)
Owner name          exact match from ``_known_owners``    ``<OWNER-REDACTED>``
Dollar amount       ``$[\\d,]+(?:.\\d{2})?``              ``<AMOUNT-REDACTED>``
                                                          (opt-in only)
==================  ====================================  ==================
"""

from __future__ import annotations

import os
import re
from typing import Any

# Alphanumeric account (e.g. Z12345678, AB-123456) OR a bare 10–12 digit number.
_ACCT_PATTERN = re.compile(r"\b([A-Z]{1,2}-?\d{6,12})\b|\b(\d{10,12})\b")

# Dollar amounts: $1, $1,234, $1,234.56
_DOLLAR_PATTERN = re.compile(r"\$[\d,]+(?:\.\d{2})?")

# Minimum owner-name length to redact (avoids over-redacting common short words).
_MIN_OWNER_LEN = 3

# Env-var opt-in for dollar redaction (default: off).
_REDACT_DOLLARS_ENV = "REDACT_DOLLAR_AMOUNTS"


def _dollars_opt_in() -> bool:
    return os.getenv(_REDACT_DOLLARS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def redact_pii(
    text: str,
    state: dict[str, Any],
    *,
    redact_dollars: bool | None = None,
) -> str:
    """Redact PII from ``text``, recording stable account tokens in ``state``.

    Parameters
    ----------
    text:
        Raw tool response that may contain PII.
    state:
        Mutable session-state dict. ``state["_pii_map"]`` maps each raw account
        string to a stable ``<ACCT-N>`` token so the same account always maps to
        the same token within a session. ``state["_known_owners"]`` (optional) is
        a list of owner names to redact.
    redact_dollars:
        Override the dollar-redaction toggle. When ``None`` (default), the
        ``REDACT_DOLLAR_AMOUNTS`` env var decides (off by default).

    Returns
    -------
    str
        The redacted text.
    """
    if not text:
        return text

    pii_map: dict = state.setdefault("_pii_map", {})

    # 1) Dollar amounts first (opt-in) so account regex can't grab digits inside
    #    an amount that we're about to redact anyway.
    do_dollars = _dollars_opt_in() if redact_dollars is None else redact_dollars
    result = text
    if do_dollars:
        result = _DOLLAR_PATTERN.sub("<AMOUNT-REDACTED>", result)

    # 2) Account numbers — stable per-session token.
    def _replace_acct(match: re.Match) -> str:
        raw = match.group(0)
        key = ("acct", raw)
        if key not in pii_map:
            n = sum(1 for k in pii_map if isinstance(k, tuple) and k[0] == "acct") + 1
            pii_map[key] = f"<ACCT-{n}>"
        return pii_map[key]

    result = _ACCT_PATTERN.sub(_replace_acct, result)

    # 3) Owner names — exact string replacement from the known-owners list.
    for owner in state.get("_known_owners", []):
        if owner and len(owner) >= _MIN_OWNER_LEN:
            result = result.replace(owner, "<OWNER-REDACTED>")

    return result


def pii_redaction_callback(ctx: Any, tool_response: str) -> str:
    """ADK-shaped wrapper: redact ``tool_response`` using ``ctx.session.state``.

    Registered with an ADK agent so every tool response is scrubbed before it
    reaches the model. The session-state ``_pii_map`` persists token assignments
    across calls within the same session.
    """
    state = ctx.session.state
    return redact_pii(tool_response, state)
