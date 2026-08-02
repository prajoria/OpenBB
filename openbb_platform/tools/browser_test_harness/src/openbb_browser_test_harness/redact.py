"""PII redaction for screenshots + logs.

Deny-list is imported from a single source shared with
``openbb_platform/tests/test_notebooks_portfolio_smoke.py`` (P1-4 fix).

For now, this is a minimal working implementation. The deny-list will be
expanded as B5/B6 land and screenshot capture goes live.
"""

from __future__ import annotations

import re
from pathlib import Path

# Fragments that MUST NOT appear in any screenshot or log output.
# Keep in sync with notebook PII smoke — for now, hardcoded here; when the
# unified source lands (spec §10 P1-4), this becomes an import.
_DENY_FRAGMENTS: tuple[str, ...] = (
    # Home-directory paths
    "C:\\Users\\daaji",
    "C:/Users/daaji",
    "/home/daaji",
    "/Users/daaji",
    # Known usernames from prior PII incidents (extend as they surface)
    "daaji",
    "prajoria",  # GH login — safe in public issues, but not in screenshots
)


def contains_pii(text: str) -> tuple[bool, str]:
    """Return (True, fragment) if any deny-list fragment is present.

    Returns (False, "") if clean.
    """
    lowered = text.lower()
    for frag in _DENY_FRAGMENTS:
        if frag.lower() in lowered:
            return True, frag
    return False, ""


def redact_text(text: str) -> str:
    """Replace PII fragments with sentinels (``<user>``, ``<home>``).

    Sentinel style matches the notebook redaction (spec §14.4).
    """
    result = text
    result = re.sub(r"C:[\\/]Users[\\/][A-Za-z0-9_.-]+", "<home>", result)
    result = re.sub(r"/(home|Users)/[A-Za-z0-9_.-]+", "<home>", result)
    for frag in _DENY_FRAGMENTS:
        if frag.lower() in ("daaji", "prajoria"):
            result = re.sub(re.escape(frag), "<user>", result, flags=re.IGNORECASE)
    return result


def assert_screenshot_clean(png_path: str | Path) -> None:
    """Raise if the screenshot file's parent path or filename contains PII.

    Note: image-pixel-level PII detection (OCR) is out of scope for v1;
    prevented at capture-time by ``page.screenshot()``-only policy (P1-4).
    """
    p = Path(png_path)
    fragments = (str(p), p.name, p.parent.name)
    for frag in fragments:
        has_pii, offender = contains_pii(frag)
        if has_pii:
            raise ValueError(
                f"PII fragment {offender!r} detected in screenshot path "
                f"{frag!r} — refusing to save. Fix the output directory."
            )
