"""Crawl TradingView community scripts library into a URL+fingerprint index.

Implements PRD §3.4 (wild-corpus methodology) for the openbb-extension-pine
project. Produces ``tests/wild_corpus/index.json`` — a JSON array of
per-script fingerprints used by the ``wild-corpus-coverage`` CI job (L0.5) to
compute "fraction of scripts that would run unedited."

What we store per script
------------------------
- ``url``        — the script's TradingView permalink
- ``title``      — human-readable script name (from card)
- ``author``     — author handle (last path segment of ``/u/{handle}/``)
- ``likes``      — boost count (integer; 0 if absent)
- ``script_type``— "indicator" or "strategy" or None (from card badge)
- ``pine_version`` — int (5 or 6) parsed from ``//@version=`` if visible, else None
- ``builtins_used`` — sorted list of unique builtin identifiers (namespace.member)
                     found in visible body, or None when source_visible is False
- ``features_used`` — dict of grammar-feature booleans/counts (see FEATURE_KEYS)
                     or None when source_visible is False
- ``source_visible`` — True when the script page yielded code-like markers we
                      could regex against; False when the page is just a
                      description with no Pine syntax visible (the common case
                      — TradingView gates full source behind login)
- ``crawled_at`` — UTC ISO timestamp

What we do NOT store
--------------------
Pine source code. Per PRD §2.1 (TradingView API/feeds off-limits) + §3.4
("Source URLs only — we **do not** redistribute script source"), the crawler
extracts metadata derived from publicly-visible script pages and nothing more.

Politeness
----------
- Configurable rate limit (default 1.5 s between requests)
- 5-retry exponential backoff on 429 / 5xx
- Idempotent disk cache under ``tools/pine/_cache/`` (gitignored — never
  committed; the cache is HTTP-bytes-on-disk, not part of the deliverable)
- Resumable: ``--resume`` skips URLs already in the output index
- Honors the User-Agent string the PRD prescribes

Usage
-----
::

    python tools/pine/crawl_wild_corpus.py \\
        --target 1000 \\
        --out tests/wild_corpus/index.json \\
        --rate-limit-sec 1.5 \\
        [--resume]

For routine quarterly re-crawls, use ``tools/pine/refresh_wild_corpus.py``,
which is a thin wrapper that always passes ``--resume``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(__file__).resolve().parent / "_cache"
LISTING_BASE = "https://www.tradingview.com/scripts/"
SCRIPT_HOST = "https://www.tradingview.com"

USER_AGENT = (
    "openbb-extension-pine wild-corpus-crawler "
    "/ +https://github.com/prajoria/OpenBB"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_RATE_LIMIT_SEC = 1.5
MAX_RETRIES = 5
REQUEST_TIMEOUT_SEC = 30
SCRIPTS_PER_LISTING_PAGE = 23  # TV's current page size; only used as a hint

# Builtin identifier regex — see PRD §3.4 (the namespace prefixes listed are
# the public Pine v5/v6 builtin namespaces). We capture ``namespace.member``
# pairs so callers can intersect against an "implemented" set later.
BUILTIN_NAMESPACES = (
    "ta", "math", "input", "str", "array", "matrix", "map", "color",
    "chart", "strategy", "request", "library", "line", "label", "box",
    "table", "syminfo", "barstate", "session", "alert", "currency",
    "dayofweek", "display", "earnings", "extend", "fixnan", "location",
    "month", "na", "plot", "price", "runtime", "sym", "year", "hl2",
    "hlc3", "ohlc4",
)
BUILTIN_RE = re.compile(
    r"\b(?:" + "|".join(BUILTIN_NAMESPACES) + r")\.\w+\b"
)

# Grammar-feature markers. These run as text-scan over visible body —
# they are not AST-accurate (we can't enforce "at top-level" without a
# parser) but suffice for the coverage gate: any positive match is at
# minimum a reference to that feature.
VERSION_RE = re.compile(r"//\s*@version\s*=\s*(\d+)")
FEATURE_PATTERNS: dict[str, re.Pattern[str]] = {
    "uses_request_security": re.compile(r"\brequest\.security\b"),
    "uses_library_directive": re.compile(r"\blibrary\s*\("),
    "uses_drawings": re.compile(r"\b(?:line|label|box|table)\.new\b"),
    "uses_strategy_directive": re.compile(r"\bstrategy\s*\("),
    "uses_indicator_directive": re.compile(r"\bindicator\s*\("),
}
INPUT_COUNT_RE = re.compile(r"\binput\.\w+\s*\(")

# Markers that mean "this body has actual Pine code in it" — used to set
# source_visible=True. If none of these fire, the body is just author prose
# and the script counts as "source not visible" in L0.5.
CODE_MARKERS_RE = re.compile(
    r"//\s*@version\s*="
    r"|\bindicator\s*\("
    r"|\bstrategy\s*\("
    r"|\blibrary\s*\("
    r"|\bplot\s*\("
    r"|\bta\.\w+\s*\("
)

FEATURE_KEYS = (
    "uses_request_security",
    "uses_library_directive",
    "uses_drawings",
    "uses_strategy_directive",
    "uses_indicator_directive",
    "uses_input_array",
)

REQUIRED_INDEX_KEYS = (
    "url",
    "title",
    "author",
    "likes",
    "script_type",
    "pine_version",
    "builtins_used",
    "features_used",
    "source_visible",
    "crawled_at",
)


# ---------------------------------------------------------------------------
# HTTP fetch with cache + retries
# ---------------------------------------------------------------------------


def _cache_path(url: str) -> Path:
    """Stable on-disk filename for a URL (sha256 of url + .html)."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.html"


def fetch(
    url: str,
    session: requests.Session,
    rate_limit_sec: float,
    last_request_ts: list[float],
) -> str | None:
    """Fetch ``url`` with disk cache + exponential backoff on 429/5xx.

    Returns the HTML body, or None on terminal failure. The ``last_request_ts``
    list is a single-element holder used to enforce inter-request spacing
    across the entire crawl (not just per-call).
    """
    cache = _cache_path(url)
    if cache.exists():
        try:
            return cache.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"  cache-read failed for {url}: {exc}", file=sys.stderr)

    # Inter-request rate limiting (we do this even before retries so the
    # first attempt is also paced — TV doesn't care which attempt overlapped,
    # they care about total request rate).
    elapsed = time.monotonic() - last_request_ts[0]
    if elapsed < rate_limit_sec:
        time.sleep(rate_limit_sec - elapsed)

    backoff = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SEC)
        except requests.RequestException as exc:
            print(
                f"  attempt {attempt + 1}/{MAX_RETRIES} network error: {exc}",
                file=sys.stderr,
            )
            time.sleep(backoff)
            backoff *= 2
            last_request_ts[0] = time.monotonic()
            continue
        last_request_ts[0] = time.monotonic()

        if resp.status_code == 200:
            resp.encoding = resp.apparent_encoding or "utf-8"
            text = resp.text
            try:
                cache.write_text(text, encoding="utf-8")
            except OSError as exc:
                print(f"  cache-write failed for {url}: {exc}", file=sys.stderr)
            return text

        if resp.status_code in (429, 500, 502, 503, 504):
            # Honor Retry-After if present, else exponential backoff.
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = int(retry_after)
            else:
                wait = backoff
            print(
                f"  attempt {attempt + 1}/{MAX_RETRIES} HTTP {resp.status_code} "
                f"on {url}; sleeping {wait:.1f}s",
                file=sys.stderr,
            )
            time.sleep(wait)
            backoff *= 2
            continue

        # 4xx other than 429 — not retryable. Cache nothing, return None.
        print(
            f"  HTTP {resp.status_code} on {url} — skipping",
            file=sys.stderr,
        )
        return None

    print(f"  exhausted retries for {url}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Listing-page scraping
# ---------------------------------------------------------------------------


def listing_url(page_num: int) -> str:
    """TradingView listing URL for page N (page 1 is the bare /scripts/)."""
    if page_num <= 1:
        return LISTING_BASE
    return f"{LISTING_BASE}page-{page_num}/"


def _parse_int_prefix(s: str) -> int:
    """Pull a leading integer out of strings like '671 boosts' or '3 comments'."""
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else 0


def parse_listing(html: str) -> list[dict[str, Any]]:
    """Extract per-card metadata from a listing page.

    Returns a list of dicts with keys: url, title, author, likes,
    script_type. These are the card-level fields; per-script body fields
    (pine_version, builtins_used, features_used, source_visible) get
    populated by ``parse_script_page`` later.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for card in soup.select("article.ideaCard-JnG_0lGR"):
        href_a = card.select_one('a[href*="/script/"]')
        if not href_a:
            continue
        href = href_a.get("href", "")
        if not href.startswith("http"):
            href = SCRIPT_HOST + href
        # Strip any fragment / query so the URL is canonical
        parsed = urlparse(href)
        url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        title_el = card.select_one(".title-z9bt_ORN")
        title = title_el.get_text(strip=True) if title_el else ""

        author_a = card.select_one('a[href^="/u/"]')
        author = ""
        if author_a:
            ahref = author_a.get("href", "")
            # /u/{handle}/ -> handle
            parts = [p for p in ahref.split("/") if p]
            if len(parts) >= 2 and parts[0] == "u":
                author = parts[1]

        boost_el = card.select_one('[aria-label*="boost" i]')
        likes = _parse_int_prefix(boost_el.get("aria-label", "")) if boost_el else 0

        badge_el = card.select_one(".visuallyHiddenLabel-fmsomiGu")
        badge_text = (badge_el.get_text(strip=True) if badge_el else "").lower()
        if "strategy" in badge_text:
            script_type: str | None = "strategy"
        elif "indicator" in badge_text:
            script_type = "indicator"
        else:
            script_type = None

        out.append(
            {
                "url": url,
                "title": title,
                "author": author,
                "likes": likes,
                "script_type": script_type,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Script-page fingerprinting
# ---------------------------------------------------------------------------


def _extract_visible_body(html: str) -> str:
    """Pull out the visible script-description text.

    TradingView gates full Pine source behind a JS auth flow; the only
    publicly-visible body is the description block (which sometimes
    contains author-pasted code snippets) + the og:description meta. We
    concatenate both and run the marker scan against the result.
    """
    soup = BeautifulSoup(html, "html.parser")

    chunks: list[str] = []

    # og:description meta — short summary
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        chunks.append(og["content"])

    # full description elements (TV's class names rotate; match loosely)
    for sel in (
        ".tv-chart-view__description",
        "[class*=descriptionWrap]",
        "[class*=description]",
        "[class*=Description]",
    ):
        for el in soup.select(sel):
            text = el.get_text(" ", strip=True)
            if text and len(text) > 40:
                chunks.append(text)

    # If TV ever starts exposing <pre>/<code> blocks server-side, capture
    # them too — costs nothing today and means we get the win automatically.
    for tag in soup.find_all(("pre", "code")):
        text = tag.get_text(" ", strip=True)
        if text:
            chunks.append(text)

    return "\n".join(chunks)


def fingerprint_body(body: str) -> dict[str, Any]:
    """Run the regex marker scans over ``body``.

    Returns a partial fingerprint dict with keys: pine_version,
    builtins_used, features_used, source_visible. Used fields are None
    when source_visible is False (the L0.5 metric treats those as the
    "unknown" cohort).
    """
    if not body or not CODE_MARKERS_RE.search(body):
        return {
            "pine_version": None,
            "builtins_used": None,
            "features_used": None,
            "source_visible": False,
        }

    ver_match = VERSION_RE.search(body)
    if ver_match:
        try:
            pine_version: int | None = int(ver_match.group(1))
        except ValueError:
            pine_version = None
    else:
        pine_version = None

    builtins_used = sorted({m.group(0) for m in BUILTIN_RE.finditer(body)})

    features: dict[str, Any] = {}
    for key, pat in FEATURE_PATTERNS.items():
        features[key] = bool(pat.search(body))
    features["uses_input_array"] = len(INPUT_COUNT_RE.findall(body))

    return {
        "pine_version": pine_version,
        "builtins_used": builtins_used,
        "features_used": features,
        "source_visible": True,
    }


def parse_script_page(html: str) -> dict[str, Any]:
    """Public entry: extract body, run fingerprint scan."""
    return fingerprint_body(_extract_visible_body(html))


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------


def load_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"warning: existing index at {path} is not valid JSON: {exc}",
              file=sys.stderr)
        return []
    if not isinstance(data, list):
        print(f"warning: existing index at {path} is not a JSON array",
              file=sys.stderr)
        return []
    return data


def write_index(path: Path, entries: list[dict[str, Any]]) -> None:
    """Pretty-printed write so PR diffs stay reviewable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sort by URL so a re-crawl produces a stable diff (helpful in PRs).
    entries_sorted = sorted(entries, key=lambda e: e.get("url", ""))
    path.write_text(
        json.dumps(entries_sorted, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------


def crawl(
    *,
    target: int,
    out_path: Path,
    rate_limit_sec: float,
    resume: bool,
) -> int:
    """Run the crawl. Returns process exit code."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    existing = load_index(out_path) if resume else []
    seen_urls = {e["url"] for e in existing if isinstance(e, dict) and "url" in e}
    entries: list[dict[str, Any]] = list(existing)
    initial_count = len(entries)

    session = requests.Session()
    last_request_ts = [0.0]  # mutable holder; see fetch()

    # Step 1: paginate listing pages, collecting card metadata until we have
    # enough URLs to (newly) fingerprint up to --target.
    cards: list[dict[str, Any]] = []
    page = 1
    empty_pages = 0
    while len([c for c in cards if c["url"] not in seen_urls]) + initial_count < target:
        url = listing_url(page)
        print(f"[listing] page {page} -> {url}")
        html = fetch(url, session, rate_limit_sec, last_request_ts)
        if html is None:
            print(f"  listing page {page} unfetchable; stopping pagination",
                  file=sys.stderr)
            break
        page_cards = parse_listing(html)
        if not page_cards:
            empty_pages += 1
            print(f"  page {page} had 0 cards; empty_pages={empty_pages}")
            if empty_pages >= 2:
                print("  two empty listing pages in a row — assuming end of corpus")
                break
        else:
            empty_pages = 0
            # Dedupe within this run as well (TV occasionally repeats cards
            # across pagination boundaries during edits).
            for c in page_cards:
                if c["url"] not in {existing_c["url"] for existing_c in cards}:
                    cards.append(c)
        page += 1
        # Safety: cap pages at 200 so we never runaway loop if TV pagination
        # misbehaves. 200 pages × 23 cards = ~4600 scripts, far above target.
        if page > 200:
            print("  hit pagination safety cap (page > 200)", file=sys.stderr)
            break

    print(f"[listing] collected {len(cards)} cards from {page - 1} page(s); "
          f"{initial_count} already in index")

    # Step 2: fingerprint each unseen card up to --target.
    new_count = 0
    for card in cards:
        if (initial_count + new_count) >= target:
            break
        if card["url"] in seen_urls:
            continue

        print(f"[script] {new_count + 1}: {card['url'][-60:]}")
        html = fetch(card["url"], session, rate_limit_sec, last_request_ts)
        if html is None:
            # The card metadata is still useful; record source_visible=false.
            entry = {
                **card,
                "pine_version": None,
                "builtins_used": None,
                "features_used": None,
                "source_visible": False,
                "crawled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        else:
            body_fp = parse_script_page(html)
            entry = {
                **card,
                **body_fp,
                "crawled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }

        entries.append(entry)
        seen_urls.add(card["url"])
        new_count += 1

        # Flush index every 25 entries so a Ctrl-C or crash mid-crawl
        # doesn't waste the work.
        if new_count % 25 == 0:
            write_index(out_path, entries)
            print(f"  [flush] wrote {len(entries)} entries to {out_path}")

    write_index(out_path, entries)
    print(f"DONE: {len(entries)} entries written to {out_path} "
          f"(added {new_count} this run)")

    # Print distribution summary
    src_true = sum(1 for e in entries if e.get("source_visible") is True)
    src_false = len(entries) - src_true
    v5 = sum(1 for e in entries if e.get("pine_version") == 5)
    v6 = sum(1 for e in entries if e.get("pine_version") == 6)
    vnull = sum(1 for e in entries if e.get("pine_version") is None)
    print(f"  distribution: source_visible true={src_true} false={src_false}; "
          f"pine_version 5={v5} 6={v6} null={vnull}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl TradingView community scripts library into a fingerprint "
            "index. URL + visible metadata only; no Pine source is stored "
            "(PRD §2.1, §3.4)."
        )
    )
    parser.add_argument(
        "--target",
        type=int,
        default=1000,
        help="Number of script entries to aim for (default 1000)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "tests" / "wild_corpus" / "index.json",
        help="Output index path (default tests/wild_corpus/index.json)",
    )
    parser.add_argument(
        "--rate-limit-sec",
        type=float,
        default=DEFAULT_RATE_LIMIT_SEC,
        help=(
            "Minimum seconds between requests (default 1.5). Increase if "
            "TV starts returning 429s — we don't want to be a noisy neighbor."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "If --out exists, skip URLs already fingerprinted there. "
            "Idempotent."
        ),
    )
    args = parser.parse_args(argv)

    if args.target <= 0:
        parser.error("--target must be > 0")
    if args.rate_limit_sec < 0:
        parser.error("--rate-limit-sec must be >= 0")

    try:
        return crawl(
            target=args.target,
            out_path=args.out,
            rate_limit_sec=args.rate_limit_sec,
            resume=args.resume,
        )
    except KeyboardInterrupt:
        print("\ninterrupted; partial index has been flushed at each 25-entry "
              "boundary", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
