"""Source-only notebook story inventory contracts (#2211, N01)."""

import csv
import json
import re
from pathlib import Path

import pytest

from scripts.notebook_story_inventory import (
    NotebookInventoryError,
    compare_with_inventory,
    inventory_notebooks,
    main,
    repository_lineage,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
CORPUS = REPO_ROOT / "notebooks"
AUDIT_INVENTORY = (
    REPO_ROOT / "docs" / "cross_repo_workflow" / "notebook-mcp-story-inventory.csv"
)


def _write_notebook(path: Path, cells: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "cells": cells,
        "metadata": {"kernelspec": {"name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def notebook_factory(tmp_path):
    """Write one synthetic notebook whose outputs and metadata vary freely."""

    def factory(
        output: str = "saved-output",
        root: Path | None = None,
        source: str = "from openbb import obb\nobb.equity.price.historical('SYNTH')",
        relative: str = "portfolio/01-synthetic.ipynb",
        execution_count: int = 1,
    ) -> Path:
        root = root or tmp_path / "notebooks"
        _write_notebook(
            root / relative,
            [
                {"cell_type": "markdown", "metadata": {}, "source": ["# Synthetic"]},
                {
                    "cell_type": "code",
                    "execution_count": execution_count,
                    "metadata": {"execution": {"started": output}},
                    "outputs": [{"output_type": "stream", "text": [output]}],
                    "source": source,
                },
            ],
        )
        return root

    return factory


def test_saved_outputs_do_not_change_source_hash(notebook_factory):
    """Outputs, execution counts and run metadata never move the hash."""
    root = notebook_factory(output="private-output-a")
    before = inventory_notebooks(root)[0].source_sha256
    notebook_factory(output="private-output-b", root=root, execution_count=9)
    assert inventory_notebooks(root)[0].source_sha256 == before


def test_source_change_changes_hash(notebook_factory):
    """Editing cell source changes the fingerprint."""
    root = notebook_factory()
    before = inventory_notebooks(root)[0].source_sha256
    notebook_factory(root=root, source="x = 2")
    assert inventory_notebooks(root)[0].source_sha256 != before


def test_inventory_never_carries_outputs(notebook_factory):
    """Saved outputs never reach the inventory record."""
    root = notebook_factory(output="private-output-a")
    assert "private-output-a" not in repr(inventory_notebooks(root))


def test_symbols_are_extracted_with_one_based_cell_positions(notebook_factory):
    """Calls and imports are attributed to one-based notebook positions."""
    root = notebook_factory()
    source = inventory_notebooks(root)[0]
    (code_cell,) = [cell for cell in source.cells if cell.cell_type == "code"]
    assert code_cell.position == 2
    assert "obb.equity.price.historical" in code_cell.calls
    assert "openbb" in code_cell.imports


def test_ipython_magics_do_not_create_parse_diagnostics(notebook_factory):
    """Magic and shell lines are not reported as Python syntax errors."""
    root = notebook_factory(source="%matplotlib inline\n!echo hi\nx = 1")
    assert inventory_notebooks(root)[0].diagnostics == ()


def test_parse_failure_is_reported_without_cell_text(notebook_factory):
    """Unparseable code becomes a diagnostic that never quotes the cell."""
    root = notebook_factory(source="x = 1\nSECRET narrative — text")
    source = inventory_notebooks(root)[0]
    (diagnostic,) = source.diagnostics
    assert diagnostic.position == 2
    assert diagnostic.kind == "syntax_error"
    assert diagnostic.classification is None
    assert source.unclassified_diagnostics == (diagnostic,)
    assert "SECRET" not in repr(source)
    assert "—" not in repr(source)


def test_malformed_notebook_names_path_without_content(tmp_path):
    """Malformed JSON names the notebook without echoing its content."""
    path = tmp_path / "notebooks" / "portfolio" / "01-broken.ipynb"
    path.parent.mkdir(parents=True)
    path.write_text('{"cells": [SECRET', encoding="utf-8")
    with pytest.raises(
        NotebookInventoryError, match="portfolio/01-broken.ipynb"
    ) as error:
        inventory_notebooks(tmp_path / "notebooks")
    assert "SECRET" not in str(error.value)


def test_unknown_story_folder_is_rejected(notebook_factory):
    """A notebook outside the reviewed story folders fails loudly."""
    root = notebook_factory(relative="scratch/01-new.ipynb")
    with pytest.raises(NotebookInventoryError, match="scratch"):
        inventory_notebooks(root)


def test_real_corpus_has_25_stories_and_both_portfolio_variants():
    """All 25 stories are present, with both Portfolio provider variants."""
    sources = inventory_notebooks(CORPUS)
    assert len(sources) == 25
    assert len({source.story_id for source in sources}) == 25
    assert {source.variant for source in sources} == {
        "portfolio",
        "free-provider",
        "techtrade",
    }
    portfolio_families = {
        source.family for source in sources if source.family.startswith("portfolio/")
    }
    for family in portfolio_families:
        variants = {s.variant for s in sources if s.family == family}
        assert variants == {"portfolio", "free-provider"}, family
    assert "portfolio/08" in portfolio_families


def test_morning_scan_narrative_cell_is_classified_not_discarded():
    """The known morning-scan defect is reported and classified."""
    sources = {source.story_id: source for source in inventory_notebooks(CORPUS)}
    (diagnostic,) = sources["techtrade/02"].diagnostics
    assert (diagnostic.position, diagnostic.kind) == (7, "syntax_error")
    assert diagnostic.classification == "narrative-in-code"
    assert all(not source.unclassified_diagnostics for source in sources.values())


def test_real_corpus_matches_reviewed_audit_inventory():
    """Changed, added or removed stories fail until the inventory is reviewed."""
    assert compare_with_inventory(inventory_notebooks(CORPUS), AUDIT_INVENTORY) == []


def test_drift_against_inventory_is_reported(notebook_factory, tmp_path):
    """Changed, missing and unreviewed notebooks are each reported."""
    root = notebook_factory()
    (source,) = inventory_notebooks(root)
    reviewed = tmp_path / "inventory.csv"
    with reviewed.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["notebook_path", "source_sha256"])
        writer.writeheader()
        writer.writerow(
            {"notebook_path": f"notebooks/{source.path}", "source_sha256": "0" * 64}
        )
        writer.writerow(
            {
                "notebook_path": "notebooks/portfolio/02-gone.ipynb",
                "source_sha256": "1" * 64,
            }
        )
    notebook_factory(root=root, relative="portfolio/03-new.ipynb")
    problems = compare_with_inventory(inventory_notebooks(root), reviewed)
    assert problems == [
        "changed: notebooks/portfolio/01-synthetic.ipynb",
        "missing: notebooks/portfolio/02-gone.ipynb",
        "unreviewed: notebooks/portfolio/03-new.ipynb",
    ]


def test_repository_lineage_records_branch_upstream_and_base():
    """Lineage records head, branch, upstream and merge base separately."""
    lineage = repository_lineage(REPO_ROOT)
    assert re.fullmatch(r"[0-9a-f]{40}", lineage.head_sha)
    assert lineage.base_ref == "origin/portfolio"
    assert lineage.base_sha is None or re.fullmatch(r"[0-9a-f]{40}", lineage.base_sha)
    assert lineage.branch is None or lineage.branch


def test_cli_check_passes_on_reviewed_corpus(capsys):
    """The CLI check succeeds on the reviewed corpus and reports it."""
    assert main(["--root", str(CORPUS), "--check", str(AUDIT_INVENTORY)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stories"] == 25
    assert report["unclassified_diagnostics"] == []
    assert report["drift"] == []
