"""Shared helpers used by both ``main`` and ``widgets_endpoints`` (#1007).

Split into a leaf module (no imports FROM ``main`` or ``widgets_endpoints``)
so both consumers can depend on it without creating an import cycle.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth config — evaluated at import time
# ---------------------------------------------------------------------------

_AUTH_TOKEN = os.environ.get("PI_WIDGET_BACKEND_TOKEN", "").strip()
_AUTH_MODE = os.environ.get("PI_WIDGET_BACKEND_AUTH_MODE", "required").strip().lower()

_VALID_AUTH_MODES = {"required", "loopback-dev"}
if _AUTH_MODE not in _VALID_AUTH_MODES:
    raise RuntimeError(
        f"PI_WIDGET_BACKEND_AUTH_MODE={_AUTH_MODE!r} is invalid; "
        f"must be one of {sorted(_VALID_AUTH_MODES)}"
    )

if _AUTH_MODE == "required" and not _AUTH_TOKEN:
    raise RuntimeError(
        "PI_WIDGET_BACKEND_TOKEN is required in the default 'required' "
        "auth mode. Either set the token, or explicitly opt into "
        "PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev (dev-only, insecure)."
    )

if _AUTH_MODE == "loopback-dev":
    logger.warning(
        "PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev — /pi/* routes are "
        "UNAUTHENTICATED. This is for local dev only. NEVER expose this "
        "backend off-host in this mode."
    )


# ---------------------------------------------------------------------------
# Regex validators — reject before echoing user input into response bodies
# ---------------------------------------------------------------------------

# Symbol allowlist — covers real-world tickers (BRK.B, BF-A) but rejects
# markdown/HTML/shell metacharacters before they reach string formatting.
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
# Account-id allowlist — reasonable identifier shape; no metacharacters.
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_LIVE_TRADER_ROLE = "live-trader"


# ---------------------------------------------------------------------------
# Auth dependency + shared account_id validator
# ---------------------------------------------------------------------------


def require_auth(request: Request) -> None:
    """Authenticate /pi/* calls via bearer token.

    Policy is set by ``PI_WIDGET_BACKEND_AUTH_MODE`` at import time. See
    the module docstring for the full policy matrix. Token comparison
    uses ``hmac.compare_digest`` to avoid timing side-channels.
    """
    if _AUTH_MODE == "loopback-dev":
        return
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    supplied = header.split(" ", 1)[1].strip()
    if not hmac.compare_digest(supplied.encode("utf-8"), _AUTH_TOKEN.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid bearer token")


@dataclass(frozen=True)
class TradingPrincipal:
    """Server-authenticated identity and its live-trading authorization."""

    principal_id: str
    roles: frozenset[str]
    account_ids: frozenset[str]


def require_live_trading_principal(
    request: Request,
    *,
    account_id: str,
) -> TradingPrincipal:
    """Resolve a server-trusted principal and authorize a live account."""
    require_auth(request)
    resolver = getattr(request.app.state, "t5_execution_principal_resolver", None)
    if resolver is None:
        raise HTTPException(status_code=403, detail="live principal unavailable")
    raw = resolver(request)
    if isinstance(raw, TradingPrincipal):
        principal = raw
    elif isinstance(raw, Mapping):
        principal = TradingPrincipal(
            principal_id=str(raw.get("principal_id", "")),
            roles=frozenset(raw.get("roles", ())),
            account_ids=frozenset(raw.get("account_ids", ())),
        )
    else:
        raise HTTPException(status_code=403, detail="live principal unavailable")
    if not _ACCOUNT_ID_RE.fullmatch(principal.principal_id):
        raise HTTPException(status_code=403, detail="live principal unavailable")
    if _LIVE_TRADER_ROLE not in principal.roles:
        raise HTTPException(status_code=403, detail="live-trader role required")
    if account_id not in principal.account_ids:
        raise HTTPException(status_code=403, detail="live account authorization denied")
    return principal


def validate_account(account_id: str) -> None:
    """Shared account_id validator. Rejects empty + metacharacters."""
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")
    if not _ACCOUNT_ID_RE.match(account_id):
        raise HTTPException(
            status_code=400,
            detail="account_id must match [A-Za-z0-9_.\\-]{1,64}",
        )
