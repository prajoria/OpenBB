"""Re-crawl the wild-corpus index — operator's quarterly refresh tool.

Per PRD §3.4, the wild-corpus index should be refreshed every quarter (and on
any major Pine version release) so the L0.5 ``wild-corpus-coverage`` CI gate
stays aligned with what the community is actually writing today.

This is a thin wrapper around ``crawl_wild_corpus.py`` that always passes
``--resume`` so previously-seen scripts are not refetched (the disk cache
in ``tools/pine/_cache/`` further protects against redundant work).

Usage
-----
::

    python tools/pine/refresh_wild_corpus.py
    # or, to expand the target above the existing default:
    python tools/pine/refresh_wild_corpus.py --target 1500

Any extra args are forwarded to ``crawl_wild_corpus.py``.
"""

from __future__ import annotations

import sys

from crawl_wild_corpus import main as crawl_main


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--resume" not in args:
        args.append("--resume")
    return crawl_main(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
