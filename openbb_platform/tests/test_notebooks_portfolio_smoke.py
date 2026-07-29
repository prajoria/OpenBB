"""Portfolio-notebook smoke tests (Phase B gate, closes #1370).

CI-safe smoke checks over ``notebooks/portfolio/*.ipynb`` — the 7-notebook
Portfolio Intelligence Engine user guide series.

**Why not full execution.** Running the notebooks end-to-end needs an
``fmp_cached`` API key and ~15 minutes, neither of which the platform CI
matrix provides. So this suite guards the two failure modes we CAN catch
without keys:

1. **Structural rot.** Each notebook must parse, contain markdown +
   code cells, and its code cells must ``compile()`` cleanly. Catches
   accidental corruption (e.g. an editor stripping the JSON), broken
   splices from a fill-script, or Python 3.12 syntax regressions.
2. **Recorded-output rot.** Every code cell that ran during the Phase B
   fulfillment MUST have non-empty outputs on disk. Catches the classic
   "someone opened + saved the notebook, wiping outputs, and pushed" —
   which would silently regress the entire series' documentation value.

**What CI cannot catch here.** Router-signature drift on
``obb.portfolio_intel.*`` / ``obb.backtest.*`` / ``obb.equity.*`` is
detectable only by re-execution. That's why the Phase B ship-check
(``notebooks/portfolio/README.md``) still requires a manual "kernel
restart + Run All in ``.venv_portfolio``" before publishing changes.
When the fork adds a proper key-provisioned CI lane, this file gains a
``@pytest.mark.integration`` execution test to close the gap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO_NB_DIR = REPO_ROOT / "notebooks" / "portfolio"

EXPECTED_NOTEBOOKS = [
    "01-getting-started-and-providers.ipynb",
    "02-single-name-deep-dive.ipynb",
    "03-basket-xray-and-risk.ipynb",
    "04-events-and-smart-money.ipynb",
    "05-whatif-attribution-and-paper.ipynb",
    "06-backtest-and-validation.ipynb",
    "07-offline-recording-and-end-to-end.ipynb",
    "08-analyst-recommendations-basket.ipynb",
]

# Track B (free-only) mirror lane. Same guards, separate constants so the
# parity between the two lanes stays visible in the failure output.
PORTFOLIO_YFINANCE_NB_DIR = REPO_ROOT / "notebooks" / "portfolio_yfinance"

EXPECTED_NOTEBOOKS_YFINANCE = [
    "01-getting-started-and-providers.ipynb",
    "02-single-name-deep-dive.ipynb",
    "03-basket-xray-and-risk.ipynb",
    "04-events-and-smart-money.ipynb",
    "05-whatif-attribution-and-paper.ipynb",
    "06-backtest-and-validation.ipynb",
    "07-offline-recording-and-end-to-end.ipynb",
    "08-analyst-recommendations-basket.ipynb",
]


def _load_notebook(path: Path) -> dict:
    """Load a .ipynb as a plain dict without importing nbformat.

    Keeps the smoke test dependency-free — nbformat is not a runtime
    requirement of the platform, so importing it here would gate this
    file on an optional install.
    """
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_exists(nb_name: str) -> None:
    """Every expected portfolio notebook is present under notebooks/portfolio/."""
    path = PORTFOLIO_NB_DIR / nb_name
    assert path.is_file(), f"missing: {path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_notebook_parses_and_has_cells(nb_name: str) -> None:
    """The notebook file is valid JSON, matches the Jupyter v4 schema loosely,
    and contains at least one markdown cell + one code cell."""
    path = PORTFOLIO_NB_DIR / nb_name
    nb = _load_notebook(path)
    assert isinstance(nb.get("cells"), list), f"{nb_name}: no cells list"
    types = {c.get("cell_type") for c in nb["cells"] if isinstance(c, dict)}
    assert "markdown" in types, f"{nb_name}: has no markdown cells"
    assert "code" in types, f"{nb_name}: has no code cells"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_code_cells_compile(nb_name: str) -> None:
    """Every code cell in the notebook must ``compile()`` under Python's
    parser. Catches syntax rot from Python-version drift or bad splices."""
    path = PORTFOLIO_NB_DIR / nb_name
    nb = _load_notebook(path)
    for idx, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        # Notebook cells routinely use top-level ``await`` (Jupyter kernel
        # feature). Enable the ``PyCF_ALLOW_TOP_LEVEL_AWAIT`` flag so those
        # do not fail this structural check.
        flags = 0x2000  # ast.PyCF_ALLOW_TOP_LEVEL_AWAIT (Python 3.8+)
        try:
            compile(src, f"{nb_name}#{idx}", "exec", flags=flags)
        except SyntaxError as exc:
            pytest.fail(f"{nb_name} cell {idx} SyntaxError: {exc}")


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_code_cells_have_recorded_outputs(nb_name: str) -> None:
    """Every non-trivial code cell must ship with recorded outputs.

    The Phase B ship rule is that every notebook lands with kernel-restart
    outputs captured on disk (so a reader browsing on GitHub sees results
    without running anything). If a cell has been edited and re-saved
    without outputs, this test surfaces it before the notebook ships.

    Ignored (allowed to be output-free):
      - Cells whose source is a single-line ``pass`` / comment only.
      - Cells whose source is empty.
    """
    path = PORTFOLIO_NB_DIR / nb_name
    nb = _load_notebook(path)
    offenders: list[int] = []
    for idx, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        stripped = "\n".join(
            line for line in src.splitlines() if line.strip() and not line.strip().startswith("#")
        ).strip()
        if not stripped or stripped == "pass":
            continue
        outs = cell.get("outputs") or []
        if not outs:
            offenders.append(idx)
    assert not offenders, (
        f"{nb_name}: code cells with source but no recorded outputs: {offenders}. "
        "Re-run the notebook in .venv_portfolio and re-save before shipping."
    )


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS)
def test_no_error_outputs(nb_name: str) -> None:
    """No code cell may ship with an ``error`` output type. If it does, the
    author ran the notebook, saw a red traceback, and pushed anyway — which
    breaks the series' honesty contract with the reader."""
    path = PORTFOLIO_NB_DIR / nb_name
    nb = _load_notebook(path)
    errors: list[tuple[int, str]] = []
    for idx, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        for out in cell.get("outputs") or []:
            if out.get("output_type") == "error":
                errors.append((idx, out.get("ename", "?")))
    assert not errors, f"{nb_name}: cells with error outputs: {errors}"


def test_series_has_readme_and_story_bible() -> None:
    """The series ships with its reader-facing docs."""
    for name in ("README.md", "STORY_BIBLE.md", "UNIVERSE.md"):
        p = PORTFOLIO_NB_DIR / name
        assert p.is_file(), f"missing: notebooks/portfolio/{name}"


# --------------------------------------------------------------------------
# Track B (free-only) parity guards.
#
# Same structural + no-error checks as the Track A block above, applied to
# ``notebooks/portfolio_yfinance/*.ipynb``. Kept as a parallel parametrized
# set (not a merged list) so a Track B failure surfaces distinctly from a
# Track A failure. Additional Track B invariant: no code cell may contain
# ``fmp`` / ``fmp_cached`` references -- the free-only lane must NEVER
# route through the paid tiers.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS_YFINANCE)
def test_yfinance_notebook_exists(nb_name: str) -> None:
    path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    assert path.is_file(), f"missing: {path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS_YFINANCE)
def test_yfinance_notebook_parses_and_has_cells(nb_name: str) -> None:
    path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    nb = _load_notebook(path)
    assert isinstance(nb.get("cells"), list), f"{nb_name}: no cells list"
    types = {c.get("cell_type") for c in nb["cells"] if isinstance(c, dict)}
    assert "markdown" in types, f"{nb_name}: has no markdown cells"
    assert "code" in types, f"{nb_name}: has no code cells"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS_YFINANCE)
def test_yfinance_code_cells_compile(nb_name: str) -> None:
    path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    nb = _load_notebook(path)
    for idx, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source") or [])
        if not src.strip():
            continue
        try:
            compile(src, f"{nb_name}#cell{idx}", "exec")
        except SyntaxError as exc:  # pragma: no cover - assertion below
            raise AssertionError(
                f"{nb_name}: code cell {idx} does not compile: {exc}"
            ) from exc


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS_YFINANCE)
def test_yfinance_no_error_outputs(nb_name: str) -> None:
    path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    nb = _load_notebook(path)
    errors: list[tuple[int, str]] = []
    for idx, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        for out in cell.get("outputs") or []:
            if out.get("output_type") == "error":
                errors.append((idx, out.get("ename", "?")))
    assert not errors, f"{nb_name}: cells with error outputs: {errors}"


@pytest.mark.parametrize("nb_name", EXPECTED_NOTEBOOKS_YFINANCE)
def test_yfinance_no_paid_provider_references(nb_name: str) -> None:
    """Track B (free-only) invariant: no code cell may call ``fmp`` or
    ``fmp_cached``. The whole point of the Track B lane is to prove the
    series runs with no paid keys — a stray ``provider="fmp_cached"``
    breaks that promise silently."""
    path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    nb = _load_notebook(path)
    offenders: list[tuple[int, str]] = []
    for idx, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source") or [])
        for needle in ("fmp_cached", "provider=\"fmp\"", "provider='fmp'"):
            if needle in src:
                offenders.append((idx, needle))
    assert not offenders, (
        f"{nb_name}: paid-provider references in code cells: {offenders}. "
        "Track B is free-only; route through cboe / sec / yfinance-snapshot instead."
    )


# ---------------------------------------------------------------------------
# #1461 guard: no bare `#NNNN` issue refs in markdown cells / .md siblings
# ---------------------------------------------------------------------------
# Same regex the rewriter (scripts/linkify_notebook_issue_refs.py) uses:
# - lookbehind rejects `[`, `(`, `/`, word chars (existing links & URL paths)
# - lookahead rejects `]`, word chars (existing links & multi-digit tokens)
_BARE_ISSUE_REF = __import__("re").compile(r"(?<![\w/(\[])#(\d{2,5})(?!\w|\])")


def _bare_refs_in_markdown(nb: dict) -> list[tuple[int, str]]:
    """Return [(cell_index, "#NNNN"), ...] for each bare ref in markdown cells."""
    out: list[tuple[int, str]] = []
    for idx, cell in enumerate(nb.get("cells") or []):
        if cell.get("cell_type") != "markdown":
            continue
        src = "".join(cell.get("source") or [])
        for m in _BARE_ISSUE_REF.finditer(src):
            out.append((idx, f"#{m.group(1)}"))
    return out


@pytest.mark.parametrize(
    "nb_name",
    EXPECTED_NOTEBOOKS + EXPECTED_NOTEBOOKS_YFINANCE,
)
def test_no_bare_issue_refs_in_markdown(nb_name: str) -> None:
    """#1461: every ``#NNNN`` in a markdown cell must be a real link
    (``[#NNNN](https://github.com/prajoria/OpenBB/issues/NNNN)``).

    A bare ``#1234`` renders as inert text in nbviewer / GitHub notebook
    preview, so readers can't click through to see what shipped. The
    rewriter script under ``scripts/linkify_notebook_issue_refs.py``
    keeps the whole series in the linked form; this guard prevents new
    bare refs from sneaking back in.
    """
    if nb_name in EXPECTED_NOTEBOOKS:
        path = PORTFOLIO_NB_DIR / nb_name
    else:
        path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    nb = _load_notebook(path)
    hits = _bare_refs_in_markdown(nb)
    assert not hits, (
        f"{nb_name}: bare issue refs in markdown cells: {hits}. "
        "Run `python scripts/linkify_notebook_issue_refs.py` to fix."
    )


@pytest.mark.parametrize(
    "md_relpath",
    [
        "notebooks/portfolio/README.md",
        "notebooks/portfolio/STORY_BIBLE.md",
        "notebooks/portfolio/UNIVERSE.md",
    ],
)
def test_no_bare_issue_refs_in_series_md(md_relpath: str) -> None:
    """Same guard for the checked-in ``.md`` companions."""
    path = REPO_ROOT / md_relpath
    if not path.exists():
        pytest.skip(f"{md_relpath} not present")
    text = path.read_text(encoding="utf-8")
    hits = [f"#{m.group(1)}" for m in _BARE_ISSUE_REF.finditer(text)]
    assert not hits, (
        f"{md_relpath}: bare issue refs: {hits}. "
        "Run `python scripts/linkify_notebook_issue_refs.py` to fix."
    )


# ---------------------------------------------------------------------------
# #1460 PII guard: notebook outputs must never contain known real usernames.
# ---------------------------------------------------------------------------
#
# The bridge cell (NB01 §6) reads ``~/.portfolio_importer/positions.db``
# and can, if not careful, emit real symbols/CUSIPs/weights + usernames
# into ``outputs``. Since outputs travel with commits (we intentionally
# preserve them for the reader), any operator running Run All with
# their own portfolio DB present could silently commit brokerage data.
#
# **Why usernames only?** CUSIPs are public SEC identifiers — the very
# same tokens that appear legitimately in the ETF-holdings/N-PORT demos
# (e.g. QQQ constituent NVIDIA = ``67066G104``). Scanning for CUSIP
# shape alone gives false positives on every notebook that shows real
# ETF holdings. Usernames, on the other hand, are the sharp signal that
# the bridge cell leaked personal data. The deny-list is seeded with the
# two usernames that #1460's initial leak already committed; add more
# here after any confirmed incident.
_KNOWN_LEAKED_USERNAMES = ["prajoria", "rashmi"]


def _extract_output_text(nb: dict) -> list[tuple[int, str]]:
    """Yield (cell_idx, output_text) for every text output in every code cell."""
    out: list[tuple[int, str]] = []
    for idx, cell in enumerate(nb.get("cells") or []):
        if cell.get("cell_type") != "code":
            continue
        for output in cell.get("outputs") or []:
            # stream outputs ("name": "stdout")
            if "text" in output:
                text = output["text"]
                if isinstance(text, list):
                    text = "".join(text)
                out.append((idx, text))
            # rich display / execute_result — text/plain fallback
            data = output.get("data") or {}
            plain = data.get("text/plain")
            if plain:
                if isinstance(plain, list):
                    plain = "".join(plain)
                out.append((idx, plain))
    return out


@pytest.mark.parametrize(
    "nb_name",
    EXPECTED_NOTEBOOKS + EXPECTED_NOTEBOOKS_YFINANCE,
)
def test_no_pii_in_notebook_outputs(nb_name: str) -> None:
    """#1460: notebook cell outputs must contain no known-real usernames.

    Reverse-verify (documented, not exercised by CI): manually inject
    ``prajoria`` into any code-cell output text, run this test — it
    MUST fail. Restore, it passes. The test is load-bearing only if
    that reverse-verify holds.
    """
    if nb_name in EXPECTED_NOTEBOOKS:
        path = PORTFOLIO_NB_DIR / nb_name
    else:
        path = PORTFOLIO_YFINANCE_NB_DIR / nb_name
    nb = _load_notebook(path)
    offenders: list[tuple[int, str, str]] = []
    for idx, text in _extract_output_text(nb):
        low = text.lower()
        for uname in _KNOWN_LEAKED_USERNAMES:
            if uname in low:
                offenders.append((idx, "known-username", uname))
    assert not offenders, (
        f"{nb_name}: PII tokens in cell outputs: {offenders}. "
        "The bridge cell (or any cell) is leaking real user data. "
        "Redact via portfolio_snapshot_importer.redact_basket_preview or "
        "strip outputs before commit."
    )
