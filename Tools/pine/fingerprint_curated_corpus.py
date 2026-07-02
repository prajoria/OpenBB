"""Fingerprint locally-authored Pine fixtures into a curated corpus index.

Bead 0e9.13 — Step 3 of the M1 ship sequence per D4 §Option C. Walks the
already-shipped fixture directories (``tests/conformance/*.pine``,
``tests/integration/v5_fixtures/*.pine``, plus any operator-added
``tests/wild_corpus/curated_scripts/*.pine``), lexes each script, extracts
declared ``//@version=`` + set of builtin identifiers + set of grammar
features, and writes fingerprints to ``tests/wild_corpus/curated_index.json``
in the same schema the wild-crawl fingerprints use (see
``Tools/pine/crawl_wild_corpus.py``).

All entries have ``source_visible=true`` — they're author-derivative Pine
scripts we own outright (PRD §7.3 posture), unlike the TV-scraped
``index.json`` where TV login-walls the bodies.

Usage::

    python Tools/pine/fingerprint_curated_corpus.py

Idempotent — regenerates the index from scratch each run.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories to walk for locally-authored .pine files. Order matters only
# for stable output; the fingerprinter dedups by absolute path.
CURATED_DIRS = [
    REPO_ROOT / "tests" / "conformance",
    REPO_ROOT / "tests" / "integration" / "v5_fixtures",
    REPO_ROOT / "tests" / "wild_corpus" / "curated_scripts",
]

OUT_PATH = REPO_ROOT / "tests" / "wild_corpus" / "curated_index.json"

# Namespaces the lexer sees + our stdlib covers.  Matches
# `openbb_pine.compiler.builtin_signatures.PINE_NAMESPACES` — kept as a
# regex here for zero-import fingerprinting so this tool runs even before
# the extension is pip-installed.
_BUILTIN_NAMESPACES = (
    r"ta|math|input|str|array|matrix|map|color|chart|strategy|request|"
    r"library|line|label|box|table|syminfo|barstate|session|alert|"
    r"currency|dayofweek|display|earnings|extend|fixnan|location|month|"
    r"na|plot|price|runtime|sym|year|hl2|hlc3|ohlc4|script|ticker"
)
_BUILTIN_RE = re.compile(rf"\b({_BUILTIN_NAMESPACES})\.\w+\b")

# Grammar features (subset of the wild-corpus indexer's vocabulary).
_FEATURE_REGEXES = {
    "indicator":         re.compile(r"\bindicator\s*\("),
    "strategy":          re.compile(r"\bstrategy\s*\("),
    "library":           re.compile(r"\blibrary\s*\("),
    "input.int":         re.compile(r"\binput\.int\s*\("),
    "input.float":       re.compile(r"\binput\.float\s*\("),
    "input.bool":        re.compile(r"\binput\.bool\s*\("),
    "input.string":      re.compile(r"\binput\.string\s*\("),
    "input.source":      re.compile(r"\binput\.source\s*\("),
    "plot":              re.compile(r"\bplot\s*\("),
    "plotshape":         re.compile(r"\bplotshape\s*\("),
    "hline":             re.compile(r"\bhline\s*\("),
    "alert":             re.compile(r"\balert\s*\("),
    "if_else":           re.compile(r"\bif\b|\belse\b"),
    "for_loop":          re.compile(r"\bfor\b"),
    "while_loop":        re.compile(r"\bwhile\b"),
    "ternary":           re.compile(r"\?.*:"),
    "history_ref":       re.compile(r"\[\s*\d+\s*\]"),
    "var":               re.compile(r"\bvar\s+\w"),
    "varip":             re.compile(r"\bvarip\s+\w"),
    "function_def":      re.compile(r"^\s*\w+\s*\([^)]*\)\s*=>", re.MULTILINE),
    "type_annotation":   re.compile(r":\s*(series|simple|const|input)\s+"),
    "request.security":  re.compile(r"\brequest\.security\s*\("),
    "line.new":          re.compile(r"\bline\.new\s*\("),
    "label.new":         re.compile(r"\blabel\.new\s*\("),
    "box.new":           re.compile(r"\bbox\.new\s*\("),
    "table.new":         re.compile(r"\btable\.new\s*\("),
    "close":             re.compile(r"\bclose\b"),
    "open":              re.compile(r"\bopen\b"),
    "high":              re.compile(r"\bhigh\b"),
    "low":               re.compile(r"\blow\b"),
    "volume":            re.compile(r"\bvolume\b"),
    "time":              re.compile(r"\btime\b"),
    "na":                re.compile(r"\bna\b"),
    "nz":                re.compile(r"\bnz\s*\("),
}


def _detect_version(text: str) -> int:
    """Read the ``//@version=N`` pragma from the first ~5 non-comment lines.

    Missing pragma defaults to 6 — matches the compiler's behavior:
    ``compile_pine(source, target_version=6)`` treats no-pragma source as v6.
    Coverage metric therefore counts a no-pragma script as v6-supported.
    """
    for line in text.splitlines()[:10]:
        line = line.strip()
        if line.startswith("//@version="):
            digits = "".join(c for c in line[len("//@version="):] if c.isdigit())
            if digits:
                return int(digits)
    return 6


def _strip_comments(text: str) -> str:
    """Drop ``// …`` line comments so regex matches don't count identifiers
    that only appear in prose. Multi-line comments ``/* */`` are not part of
    Pine syntax."""
    return re.sub(r"//[^\n]*", "", text)


def _fingerprint_file(path: Path) -> dict:
    """Return the same-shape fingerprint dict crawl_wild_corpus.py produces."""
    raw = path.read_text(encoding="utf-8")
    body = _strip_comments(raw)
    version = _detect_version(raw)
    builtins = sorted({m.group(0) for m in _BUILTIN_RE.finditer(body)})
    features = sorted(
        name for name, rx in _FEATURE_REGEXES.items() if rx.search(body)
    )
    return {
        "url": f"file://{path.as_posix()}",
        "title": path.stem,
        "author": "author-derivative (PRD §7.3)",
        "likes": None,
        "script_type": (
            "strategy" if "strategy" in features else
            "library" if "library" in features else
            "indicator"
        ),
        "pine_version": version,
        "builtins_used": builtins,
        "features_used": features,
        "source_visible": True,
        "crawled_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def main() -> int:
    fingerprints: list[dict] = []
    seen: set[Path] = set()
    for d in CURATED_DIRS:
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.pine")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                fingerprints.append(_fingerprint_file(path))
            except OSError as e:
                print(f"WARN: could not read {path}: {e}", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(fingerprints, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(fingerprints)} fingerprints to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
