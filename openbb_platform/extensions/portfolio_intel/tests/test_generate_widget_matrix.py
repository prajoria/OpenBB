"""Tests for scripts/generate_widget_matrix.py (#1811)."""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_widget_matrix.py"
FIXTURE = Path(__file__).parent / "fixtures" / "widgets_manifest_sample.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_widget_matrix", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["generate_widget_matrix"] = module
    spec.loader.exec_module(module)
    return module


gwm = _load_module()

GOLDEN = (
    "| id | name | type | endpoint | category prefix |\n"
    "|----|------|------|----------|-----------------|\n"
    "| `pi_book_context` | Book Context | markdown | `pi/context/book` |"
    " Portfolio Intelligence |\n"
    "| `pi_symbol_context` | Symbol Context Bar | markdown |"
    " `pi/context/symbol` | Portfolio Intelligence |\n"
    "| `pi_xray_sector` | X-Ray: Sector | table | `pi/xray/sector` |"
    " Portfolio Intelligence |\n"
    "| `tt_scan_table` | TechTrade Scan Table | table | `tt/scan/results` |"
    " TechTrade |\n"
)


def test_render_matrix_matches_golden():
    """Render matches the golden markdown table."""
    manifest = gwm.load_manifest(str(FIXTURE))
    assert gwm.render_matrix(manifest) == GOLDEN


def test_main_generate_prints_matrix(capsys):
    """CLI generate mode prints the golden matrix."""
    exit_code = gwm.main([str(FIXTURE)])
    assert exit_code == 0
    assert capsys.readouterr().out == GOLDEN


def test_check_passes_when_prd_matches(tmp_path):
    """--check exits 0 when PRD Appendix A matches."""
    prd = tmp_path / "prd.md"
    prd.write_text(
        "# PRD\n\n"
        "## Appendix A — Widget × Panel Mapping\n\n"
        "Intro line.\n\n"
        f"{GOLDEN}\n"
        "## Appendix B — Next\n",
        encoding="utf-8",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = gwm.main([str(FIXTURE), "--check", str(prd)])
    assert exit_code == 0
    assert buf.getvalue() == ""


def test_check_fails_and_prints_diff_on_mismatch(tmp_path, capsys):
    """--check exits non-zero with a unified diff on drift."""
    stale = GOLDEN.replace("Symbol Context Bar", "Old Name")
    prd = tmp_path / "prd.md"
    prd.write_text(
        "## Appendix A — Widget × Panel Mapping\n\n"
        f"{stale}\n"
        "## Appendix B — Next\n",
        encoding="utf-8",
    )
    exit_code = gwm.main([str(FIXTURE), "--check", str(prd)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Old Name" in out
    assert "Symbol Context Bar" in out
    assert "---" in out and "+++" in out


def test_missing_appendix_raises(tmp_path):
    """check_prd raises when Appendix A header is absent."""
    prd = tmp_path / "prd.md"
    prd.write_text("# no appendix here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Appendix A header not found"):
        gwm.check_prd(prd, GOLDEN)


def test_conflicting_sources_rejected():
    """CLI rejects both manifest path and --from-live."""
    with pytest.raises(SystemExit):
        gwm.main([str(FIXTURE), "--from-live", "http://example.invalid"])


def test_no_source_rejected():
    """CLI rejects invocation with no source."""
    with pytest.raises(SystemExit):
        gwm.main([])
