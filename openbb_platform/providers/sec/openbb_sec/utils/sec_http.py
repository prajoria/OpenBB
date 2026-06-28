"""SEC HTTP chokepoint helper (#99 T1).

Single audit point for every ``sec.gov`` / ``data.sec.gov`` request from
the N-PORT ingest pipeline. Mandatory User-Agent (L2) resolved from the
``SEC_USER_AGENT`` env var first, then ``user_settings.credentials.sec_user_agent``
via openbb_core's ``UserService``. Missing config raises ``SecHttpConfigError``
at the first call site rather than silently letting SEC return a 403.

L3 disciplines (mirrors #93's ``openfigi.py`` patterns):
- ``requests`` only; no ``aiohttp`` (broken on Win/Py3.12).
- One module-level ``requests.Session`` for connection pooling.
- ``Accept-Encoding: gzip`` on every request.
- ``Retry-After`` honored on 429; exponential fallback when the header is
  absent; retry budget capped to prevent runaway loops.

Why this is a new module instead of extending ``openbb_sec.utils.helpers``:
the existing helper uses ``aiohttp`` (L3 forbids that path for #99) and
hard-codes a placeholder UA in ``definitions.SEC_HEADERS`` — exactly the
L2 violation this module exists to fix. Migrating the existing async path
is out of scope for #99; a follow-up bd can do that consolidation later.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 30
DEFAULT_MAX_RETRIES = 5


class SecHttpConfigError(RuntimeError):
    """Raised when the L2 mandatory User-Agent is not configured.

    Carrying this is non-negotiable: SEC returns 403 to default Python UAs,
    which manifests as a silent empty download in #97 v1. This exception
    fires at the FIRST get/post call so the failure is at startup,
    diagnosable from one line of trace, not 200 lines deep in an ingest.
    """


_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    """Return the module-level requests.Session (lazy + reused)."""
    global _SESSION  # noqa: PLW0603 — intentional single shared session per L3
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


def _user_service_credentials() -> Any | None:
    """Return ``user_settings.credentials`` or ``None`` if openbb_core is absent.

    Mirrors ``openfigi._user_service_credentials`` so the cred-resolution
    pattern is uniform across SEC helpers.
    """
    try:
        from openbb_core.app.service.user_service import UserService  # noqa: PLC0415

        return UserService().default_user_settings.credentials
    except Exception as exc:  # noqa: BLE001
        logger.debug("UserService unavailable for SEC UA resolution: %s", exc)
        return None


def _resolve_user_agent() -> str:
    """Resolve the L2 User-Agent per the documented ladder.

    Order: ``SEC_USER_AGENT`` env → ``user_settings.credentials.sec_user_agent``
    → ``SecHttpConfigError``.

    Never returns a default placeholder — silent defaults are the L2 anti-pattern.
    """
    import os  # noqa: PLC0415 — keep top-of-module light

    env_ua = os.environ.get("SEC_USER_AGENT")
    if env_ua:
        return env_ua
    creds = _user_service_credentials()
    if creds is not None:
        ua = getattr(creds, "sec_user_agent", None)
        if ua:
            return ua
    raise SecHttpConfigError(
        "SEC User-Agent not configured. Set either:\n"
        "  1. SEC_USER_AGENT env var (e.g. 'AcmeCorp ops@acme.com'), or\n"
        "  2. user_settings.credentials.sec_user_agent in ~/.openbb_platform/user_settings.json.\n"
        "Format: '<entity name> <contact email>' (per SEC's fair-access policy)."
    )


def _request(
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    **kw: Any,
) -> requests.Response:
    """Dispatch the shared request internals with L2/L3 enforcement."""
    ua = _resolve_user_agent()  # raises SecHttpConfigError if missing
    headers = dict(kw.pop("headers", None) or {})
    headers.setdefault("User-Agent", ua)
    headers.setdefault("Accept-Encoding", "gzip")
    kw.setdefault("timeout", DEFAULT_TIMEOUT_SECS)

    session = _get_session()
    backoff = 1.0
    last_response: requests.Response | None = None
    for attempt in range(max_retries):
        resp = session.request(method, url, headers=headers, **kw)
        last_response = resp
        if resp.status_code != 429:
            return resp

        retry_after = resp.headers.get("Retry-After")
        wait: float
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                # Some servers send HTTP-date Retry-After; fall back to backoff.
                wait = backoff
        else:
            wait = backoff
        logger.info(
            "SEC 429 on %s; sleeping %.1fs (attempt %d/%d)",
            url, wait, attempt + 1, max_retries,
        )
        time.sleep(wait)
        backoff = min(backoff * 2, 60.0)

    # Retry budget exhausted — surface the last 429.
    if last_response is not None:
        last_response.raise_for_status()
    raise requests.HTTPError(f"SEC retry budget exhausted for {url}")


def get(
    url: str,
    *,
    params: dict | None = None,
    stream: bool = False,
    max_retries: int = DEFAULT_MAX_RETRIES,
    **kw: Any,
) -> requests.Response:
    """GET ``url`` with L2 UA + L3 retry/gzip/session.

    Raises ``SecHttpConfigError`` at startup if the L2 UA is unconfigured.
    """
    return _request("GET", url, params=params, stream=stream, max_retries=max_retries, **kw)


def post(
    url: str,
    *,
    json: list | dict | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    **kw: Any,
) -> requests.Response:
    """POST ``url`` with L2 UA + L3 retry/gzip/session."""
    return _request("POST", url, json=json, max_retries=max_retries, **kw)
