"""Crawl all 208 TradingView built-in indicator articles to local markdown.

- Source: https://www.tradingview.com/support/folders/43000587405-built-in-indicators/
- Output: H:/masterswork/git/OpenBBTechnical/temp/TradingView/{slug}.md + README.md
- Cross-refs: any /support/solutions/{N}-{slug}/ link inside an article that
  matches a slug in our set is rewritten to ./{slug}.md so the local tree is
  fully navigable; unknown solution links stay absolute.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import html2text
import requests
from bs4 import BeautifulSoup

ROOT = Path(r"H:\masterswork\git\OpenBBTechnical")
OUT_DIR = ROOT / "temp" / "TradingView"
INDEX_MD = OUT_DIR / "README.md"
INDEX_JSON = ROOT / "temp" / "tv_indicators_full.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip"}
THROTTLE_SECONDS = 0.5  # be polite

INDICATOR_URL_RE = re.compile(
    r"/support/solutions/(\d+)-([a-z0-9-]+)/?", re.IGNORECASE
)


def load_indicator_index() -> list[dict]:
    """Read the list of indicators saved by the prior chrome-devtools traversal."""
    src = ROOT / "temp" / "tradingvie.md"
    items: list[dict] = []
    line_re = re.compile(
        r"^- \[(?P<title>[^\]]+)\]\((?P<url>https://www\.tradingview\.com/support/solutions/(?P<sol>\d+)-(?P<slug>[^/]+)/)\)$"
    )
    for line in src.read_text(encoding="utf-8").splitlines():
        m = line_re.match(line.strip())
        if not m:
            continue
        items.append(
            {
                "title": m.group("title"),
                "url": m.group("url"),
                "sol": m.group("sol"),
                "slug": m.group("slug"),
            }
        )
    return items


def fetch(url: str, session: requests.Session, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code in (429, 503):
                wait = int(r.headers.get("Retry-After", "5"))
                print(f"  {r.status_code}; sleeping {wait}s")
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code} on {url}")
            return None
        except requests.RequestException as e:
            print(f"  attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)
    return None


def rewrite_crosslinks(article: BeautifulSoup, slug_lookup: dict[str, str]) -> None:
    """In-place: rewrite each <a> whose href targets a known sibling indicator."""
    for a in article.find_all("a", href=True):
        href = a["href"]
        m = INDICATOR_URL_RE.search(href)
        if not m:
            continue
        slug = m.group(2).lower()
        if slug in slug_lookup:
            a["href"] = f"./{slug}.md"
        elif href.startswith("/"):
            a["href"] = f"https://www.tradingview.com{href}"


def html_to_markdown(article_html: str) -> str:
    h = html2text.HTML2Text()
    h.body_width = 0           # don't wrap
    h.ignore_links = False
    h.ignore_images = False
    h.protect_links = True
    h.unicode_snob = True
    h.skip_internal_links = False
    h.mark_code = True
    return h.handle(article_html).strip()


def render_md(item: dict, body_md: str) -> str:
    return (
        f"# {item['title']}\n\n"
        f"**Source:** <{item['url']}>  \n"
        f"**Indicator ID:** {item['sol']}  \n"
        f"**Slug:** `{item['slug']}`\n\n"
        f"[← back to index](./README.md)\n\n"
        f"---\n\n"
        f"{body_md}\n\n"
        f"---\n\n"
        f"[← back to index](./README.md)\n"
    )


def render_index(items: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# TradingView — Built-in Indicators (full crawl)")
    lines.append("")
    lines.append(
        "**Source:** "
        "<https://www.tradingview.com/support/folders/43000587405-built-in-indicators/>"
    )
    lines.append(f"**Captured:** {time.strftime('%Y-%m-%d')}")
    lines.append(f"**Indicators:** {len(items)}")
    lines.append("")
    lines.append(
        "Each indicator below links to a local markdown copy of its TradingView "
        "support article. Cross-references between articles have been rewritten "
        "to local files; external links (images, glossary) remain absolute."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    # A–Z grouping
    def bucket(t: str) -> str:
        c = t[:1].upper()
        return c if "A" <= c <= "Z" else "#"

    grouped: dict[str, list[dict]] = {}
    for it in items:
        grouped.setdefault(bucket(it["title"]), []).append(it)
    order = sorted(grouped.keys(), key=lambda x: (x != "#", x))

    lines.append("## Table of contents")
    lines.append("")
    for k in order:
        lines.append(f"- [{k}](#{k.lower()}) ({len(grouped[k])})")
    lines.append("")
    lines.append("---")
    lines.append("")
    for k in order:
        lines.append(f"## {k}")
        lines.append("")
        for it in sorted(grouped[k], key=lambda x: x["title"].lower()):
            status = "" if it.get("ok") else " *(fetch failed)*"
            lines.append(f"- [{it['title']}](./{it['slug']}.md){status}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items = load_indicator_index()
    if not items:
        print("no indicators parsed from tradingvie.md")
        return 1
    slug_lookup = {it["slug"].lower(): it for it in items}
    print(f"loaded {len(items)} indicators; output -> {OUT_DIR}")

    session = requests.Session()
    failures: list[dict] = []
    converter_failures: list[dict] = []

    for i, it in enumerate(items, 1):
        out_path = OUT_DIR / f"{it['slug']}.md"
        if out_path.exists() and out_path.stat().st_size > 500:
            it["ok"] = True
            if i % 25 == 0:
                print(f"[{i:3}/{len(items)}] skip (already have) {it['slug']}")
            continue
        print(f"[{i:3}/{len(items)}] {it['slug']}")
        html = fetch(it["url"], session)
        if not html:
            it["ok"] = False
            failures.append(it)
            continue
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article")
        if not article:
            it["ok"] = False
            converter_failures.append(it)
            continue
        # strip nav/footer-like junk if present inside article
        for tag in article.select("nav, footer, script, style, .breadcrumb"):
            tag.decompose()
        rewrite_crosslinks(article, slug_lookup)
        try:
            body_md = html_to_markdown(str(article))
        except Exception as e:  # pragma: no cover
            print(f"  html2text failed: {e}")
            it["ok"] = False
            converter_failures.append(it)
            continue
        # drop the first-heading duplicate (we add our own H1 header)
        body_md = re.sub(
            rf"^#\s+{re.escape(it['title'])}\s*\n+",
            "",
            body_md,
            count=1,
            flags=re.IGNORECASE,
        )
        out_path.write_text(render_md(it, body_md), encoding="utf-8")
        it["ok"] = True
        time.sleep(THROTTLE_SECONDS)

    # Index
    INDEX_MD.write_text(render_index(items), encoding="utf-8")
    INDEX_JSON.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    ok_count = sum(1 for it in items if it.get("ok"))
    print()
    print(f"DONE: {ok_count}/{len(items)} articles written")
    print(f"Failures: HTTP={len(failures)}, parse/convert={len(converter_failures)}")
    if failures:
        print("HTTP failures (first 10):", [f["slug"] for f in failures[:10]])
    if converter_failures:
        print(
            "parse/convert failures (first 10):",
            [f["slug"] for f in converter_failures[:10]],
        )
    return 0 if ok_count == len(items) else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
