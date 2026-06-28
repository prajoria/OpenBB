"""SEC bulk-quarterly-ZIP URL discovery (#99 T4 / Q-A A1).

Single responsibility: walk the SEC's published Form N-PORT data-sets page,
find the per-quarter ZIP links, return a stable ``{"2026Q1": "https://..."}``
mapping.

Why a discovery step at all (Q-A Resolution):
SEC publishes the per-quarter ZIPs under predictable filenames but at URLs
that have moved twice in the last three years (the `/data/n-port/` path was
deprecated then resurrected; the page now lives under
`/data-research/sec-markets-data/form-n-port-data-sets`). Hard-coding the
URL pattern is brittle. The discovery step costs one GET per ingest run
and makes the loader robust to the next URL move.

The raise-loudly-on-empty guard (the #97 regression):
#97 v1 had a bulk loader that returned `[]` silently when the page
reorganized. The cache stored zero rows as "fresh." The fix codified here:
when ``discover_quarter_zips()`` parses zero rows, it raises
``BulkDiscoveryEmpty`` instead of returning ``{}``. A SIGINT-equivalent
signal to the operator: "the SEC page changed, don't trust me to find ZIPs."

L3 compliance: every HTTP call goes through ``sec_http.get`` (T1) so the
L2 User-Agent is enforced and 429/Retry-After is honored — even at the
discovery layer.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from openbb_sec.utils.sec_http import get

logger = logging.getLogger(__name__)

NPORT_DATA_SETS_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets"
)

# Two parts to identify a quarter-ZIP link:
#   1. The filename must contain "nport" (filters out unrelated 2026q1 strings)
#   2. The filename must contain a "YYYY[qQ][1-4]" token in either order:
#         2026q1_nport_p.zip  (current SEC convention — quarter prefix)
#         nport_p_2026q1.zip  (historical convention — quarter suffix)
# We extract year+quarter independently of position so future filename
# tweaks that keep both tokens still match.
_ZIP_HREF_RE = re.compile(
    r"""
    (?P<href>                          # full href captured for url join
      [^"'\s>]*?                       #  any leading path chars (or absolute URL)
      [^"'\s>/]*                       #  filename body (no slashes/quotes/whitespace)
      n[-_]?port                       #  must contain the literal nport substring
      [^"'\s>]*                        #  any chars (allowing _, -, p, etc.)
      \.zip                            #  literal .zip
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Year/quarter extractor — run on the matched href to pull out YYYYQn.
_YEAR_Q_RE = re.compile(r"(?P<year>\d{4})[-_]?[qQ](?P<quarter>[1-4])")


class BulkDiscoveryEmpty(RuntimeError):
    """Raised by ``discover_quarter_zips()`` when zero quarter-ZIP links parse.

    This is the #97 silent-empty regression guard codified into Q-A. The
    operator MUST see this fail loudly — a return of ``{}`` would silently
    skip the bulk backfill and store the result as "fresh empty."
    """


class _HrefCollector(HTMLParser):
    """Minimal HTMLParser that collects every <a href=...> on the page.

    We don't try to be selective about which links are "data" links — the
    quarter-ZIP filename pattern matches narrowly enough that any
    non-N-PORT link will simply not match the regex below.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Collect href values from every <a> tag."""
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)


def _extract_quarter_zip_links(html: str) -> dict[str, str]:
    """Parse hrefs out of the page HTML and reduce to ``{quarter: full_url}``."""
    collector = _HrefCollector()
    try:
        collector.feed(html)
    except Exception as exc:  # noqa: BLE001 — HTMLParser can raise odd errors on weird input
        logger.warning("HTML parse error during quarter-ZIP discovery: %s", exc)
        return {}

    quarters: dict[str, str] = {}
    for href in collector.hrefs:
        match = _ZIP_HREF_RE.search(href)
        if not match:
            continue
        raw_href = match.group("href")
        # Pull the year/quarter from the matched filename. The href regex
        # only confirmed nport*.zip; this second pass finds the YYYYQn token
        # regardless of whether it's a prefix (2026q1_nport_p.zip) or a
        # suffix (nport_p_2026q1.zip).
        yq = _YEAR_Q_RE.search(raw_href)
        if not yq:
            continue
        key = f"{yq.group('year')}Q{yq.group('quarter')}"
        # Resolve relative URLs against the data-sets page itself.
        full_url = urljoin(NPORT_DATA_SETS_URL, raw_href)
        # First-seen wins to avoid duplicate-archive overrides.
        quarters.setdefault(key, full_url)
    return quarters


def discover_quarter_zips(*, page_url: str = NPORT_DATA_SETS_URL) -> dict[str, str]:
    """Discover the per-quarter ZIP URLs from the SEC N-PORT data-sets page.

    Returns: ``{"2026Q1": "https://www.sec.gov/files/...zip", ...}``

    Raises:
        BulkDiscoveryEmpty: if zero quarter-ZIP links parse from the page.
            This is the Q-A raise-loudly guard; do NOT swallow it.
        sec_http.SecHttpConfigError: if the L2 User-Agent is not configured.
        requests.RequestException: on transport failures (the underlying
            ``sec_http.get`` propagates these after its 429 retry budget).

    Args:
        page_url: override the default data-sets URL (used by tests so we
            don't have to patch the whole module).
    """
    response = get(page_url)
    response.raise_for_status()
    quarters = _extract_quarter_zip_links(response.text)
    if not quarters:
        raise BulkDiscoveryEmpty(
            f"No quarter-ZIP links found on {page_url}. SEC may have reorganized "
            "the page. Re-check the URL and the _ZIP_HREF_RE pattern in "
            "openbb_sec.utils.bulk_url_discovery; do NOT silently fall through "
            "to an empty bulk ingest (this is the #97 v1 regression guard)."
        )
    logger.info(
        "Discovered %d quarter-ZIP URLs from %s (latest: %s)",
        len(quarters),
        page_url,
        max(quarters.keys()),
    )
    return quarters


__all__ = [
    "BulkDiscoveryEmpty",
    "NPORT_DATA_SETS_URL",
    "discover_quarter_zips",
]
