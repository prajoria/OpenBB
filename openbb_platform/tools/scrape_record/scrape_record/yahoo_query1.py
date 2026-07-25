"""Yahoo Finance ``query1`` fast-path client with Playwright-seeded session.

Rationale (from ``.dev-cycle/yahoo-scraping-investigation/INVESTIGATION_REPORT.md``):

- The public ``/quote/<SYM>`` page migrated to a SvelteKit SPA and no
  longer fires ``quoteSummary`` XHRs. Old ``page.expect_response``
  recording scripts always time out.
- The ``query1.finance.yahoo.com/v10/finance/quoteSummary/<SYM>`` REST
  endpoint still works if the request carries a valid ``crumb`` +
  matching Yahoo session cookies (``A1`` / ``A3`` / ``cmp`` / ``A1S``).
- Plain ``httpx`` without cookies returns ``401 Invalid Crumb``. Seeding
  the cookie jar from a warmed persistent Chromium context fixes this
  — the resulting httpx call returns the full ``quoteSummary`` JSON in
  under a second.

This module gives the layered fast+fallback recordings (see
``scrape_record/recordings/yahoo_equity_*.py``) a shared session
manager: seed once via Playwright, cache to disk with TTL, refresh on
401. The cache lives at ``~/.scrape_record/session.json`` — same
directory as the persistent Chromium profile, both governed by
``scrape_record.config._validate_profile_outside_repo`` so nothing
leaks into the repo.

Public surface:

- ``get_session(cfg, force_refresh=False) -> Query1Session``  synchronous
- ``fetch_quote_summary(cfg, symbol, modules, ...) -> dict``  synchronous
- ``Query1Session``  dataclass  (crumb + cookies + UA + issued_at)
"""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

QUERY1_BASE = "https://query1.finance.yahoo.com"
QUERY1_QUOTE_SUMMARY_TPL = (
    QUERY1_BASE + "/v10/finance/quoteSummary/{symbol}?modules={modules}&crumb={crumb}"
)

# Cache location — sibling of the persistent chrome_profile dir.
DEFAULT_SESSION_CACHE_NAME = "session.json"

# Session TTL — the crumb is stable for several hours; re-seed daily is
# safe. Set conservatively.
SESSION_TTL = timedelta(hours=6)

# Cookies Yahoo cares about for the query1 endpoint.
YAHOO_COOKIE_NAMES = frozenset({"A1", "A3", "A1S", "cmp", "gpp", "gpp_sid", "eids"})


class Query1Error(RuntimeError):
    """Raised when the fast path definitively cannot serve a request.

    Distinct from a transient error: recording scripts treat this as
    the signal to fall back to DOM-scrape.
    """


@dataclass
class Query1Session:
    """A warmed Yahoo session — crumb, cookies, user-agent, issued time."""

    crumb: str
    cookies: dict[str, str]
    user_agent: str
    issued_at: str  # ISO-8601 UTC
    source: str = "playwright-warmup"

    def is_expired(self, ttl: timedelta = SESSION_TTL) -> bool:
        """Return True if this session was issued more than ``ttl`` ago."""
        try:
            issued = datetime.fromisoformat(self.issued_at)
        except (TypeError, ValueError):
            return True
        return (datetime.now(timezone.utc) - issued) > ttl

    @classmethod
    def from_dict(cls, data: dict) -> Query1Session:
        """Rehydrate a Query1Session from its JSON-serialized dict form."""
        return cls(
            crumb=data["crumb"],
            cookies={str(k): str(v) for k, v in (data.get("cookies") or {}).items()},
            user_agent=data.get("user_agent", ""),
            issued_at=data.get("issued_at", ""),
            source=data.get("source", "unknown"),
        )


def session_cache_path(cfg) -> Path:
    """Path to the session cache file, sibling of the Chromium profile."""
    return cfg.profile_dir.parent / DEFAULT_SESSION_CACHE_NAME


def _load_cached_session(cfg) -> Query1Session | None:
    path = session_cache_path(cfg)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return Query1Session.from_dict(data)
    except (KeyError, TypeError):
        return None


def _save_session(cfg, sess: Query1Session) -> None:
    path = session_cache_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(sess), indent=2), encoding="utf-8")


async def _seed_via_playwright(cfg, target_symbol: str = "MSFT") -> Query1Session:
    """Open persistent Chromium, warm session, fetch a fresh crumb.

    Uses the same persistent context path as the DOM-fallback recordings.
    If the profile is cold (no consent click-through), Yahoo redirects
    to the GDPR consent page and this returns an empty crumb — the caller
    can detect and raise ``Query1Error``.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.profile_dir),
            headless=cfg.headless,
            viewport={"width": 1200, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        # Touch a valid ticker page so Yahoo issues session cookies
        await page.goto(
            f"https://finance.yahoo.com/quote/{target_symbol}/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        # Let cookies settle
        await asyncio.sleep(2)
        crumb = await page.evaluate("""async () => {
                const r = await fetch(
                    'https://query1.finance.yahoo.com/v1/test/getcrumb',
                    {credentials: 'include'},
                );
                return await r.text();
            }""")
        ua = await page.evaluate("() => navigator.userAgent")
        all_cookies = await ctx.cookies()
        yahoo_cookies = {
            c["name"]: c["value"]
            for c in all_cookies
            if any(dom in c["domain"] for dom in ("yahoo", ".yahoo.com"))
            and c["name"] in YAHOO_COOKIE_NAMES
        }
        await ctx.close()

    if not crumb or not crumb.strip() or len(crumb) > 64:
        raise Query1Error(
            f"Playwright seed returned bad crumb {crumb!r} — profile probably "
            "needs interactive consent click-through. Run scrape_record_warmup.py."
        )

    return Query1Session(
        crumb=crumb.strip(),
        cookies=yahoo_cookies,
        user_agent=ua,
        issued_at=datetime.now(timezone.utc).isoformat(),
        source="playwright-warmup",
    )


def get_session(cfg, *, force_refresh: bool = False) -> Query1Session:
    """Return a fresh or cached ``Query1Session``.

    Seeds via Playwright if the cache is missing, expired, or
    ``force_refresh=True``. Blocks on the seed (which needs headed
    Chromium) — callers that only want a quick fetch should ensure a
    warm cache first.
    """
    if not force_refresh:
        cached = _load_cached_session(cfg)
        if cached is not None and not cached.is_expired():
            return cached
    sess = asyncio.run(_seed_via_playwright(cfg))
    _save_session(cfg, sess)
    return sess


def fetch_quote_summary(
    cfg,
    symbol: str,
    modules: str,
    *,
    max_retries: int = 1,
    timeout: float = 15.0,
) -> dict:
    """Call query1 for ``quoteSummary``; return parsed JSON.

    On HTTP 401 (bad or expired crumb) refresh the session up to
    ``max_retries`` times, then raise ``Query1Error``. Any other
    HTTP error also raises ``Query1Error`` — callers fall back to
    DOM-scrape.
    """
    attempts = 0
    last_error: str = ""
    while attempts <= max_retries:
        sess = get_session(cfg, force_refresh=(attempts > 0))
        url = QUERY1_QUOTE_SUMMARY_TPL.format(
            symbol=symbol, modules=modules, crumb=sess.crumb
        )
        headers = {"User-Agent": sess.user_agent} if sess.user_agent else {}
        try:
            with httpx.Client(
                headers=headers, cookies=sess.cookies, timeout=timeout
            ) as client:
                resp = client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            last_error = f"httpx {type(exc).__name__}: {exc}"
            attempts += 1
            continue

        if resp.status_code == 401:
            last_error = f"401 Unauthorized on attempt {attempts + 1}"
            attempts += 1
            continue
        if resp.status_code != 200:
            raise Query1Error(
                f"query1 non-200: {resp.status_code} for {symbol} "
                f"modules={modules} — body: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise Query1Error(f"query1 returned non-JSON for {symbol}: {exc}") from exc
        # Yahoo may return {"finance":{"error":{...}}} instead of quoteSummary
        if not isinstance(data, dict) or "quoteSummary" not in data:
            raise Query1Error(
                f"query1 payload missing quoteSummary for {symbol}: "
                f"keys={list(data.keys())[:5]}"
            )
        if not (data["quoteSummary"] or {}).get("result"):
            raise Query1Error(
                f"query1 quoteSummary.result empty for {symbol} "
                f"modules={modules} (endpoint OK, ticker/module miss?)"
            )
        return data
    raise Query1Error(f"query1 exhausted retries for {symbol}: {last_error}")
