"""Portfolio lineage evidence tests."""

import subprocess
from pathlib import Path

import pytest

from openbb_mcp_server.service.capability_provenance import (
    collect_lineage_metadata,
)


def git(repo: Path, *args: str) -> str:
    """Run a local Git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def commit(repo: Path, message: str, content: str) -> str:
    """Create one deterministic test commit."""
    (repo / "file.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path) -> tuple[Path, str]:
    """Create a repository with one base commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "user.name", "Tests")
    return repo, commit(repo, "base", "base")


def test_explicit_comparison_reports_ahead(repository):
    """Explicit SHA comparison is independent from branch upstream config."""
    repo, base = repository
    commit(repo, "feature", "feature")
    lineage = collect_lineage_metadata(
        repo,
        comparison_sha=base,
        base_ref="portfolio",
    )
    assert lineage.state == "available"
    assert lineage.comparison_source == "explicit"
    assert lineage.ahead == 1
    assert lineage.behind == 0
    assert lineage.relation == "ahead"
    assert lineage.base_is_portfolio is True


def test_ci_base_sha_wins_without_local_tracking(repository):
    """GitHub base SHA/ref supply CI evidence without remote refs."""
    repo, base = repository
    lineage = collect_lineage_metadata(
        repo,
        environment={
            "GITHUB_BASE_SHA": base,
            "GITHUB_BASE_REF": "portfolio",
        },
    )
    assert lineage.state == "available"
    assert lineage.comparison_source == "github_base_sha"
    assert lineage.relation == "equal"


def test_ci_event_file_supplies_pr_base(repository, tmp_path):
    """Native GitHub event metadata supplies the PR base SHA/ref."""
    repo, base = repository
    event = tmp_path / "event.json"
    event.write_text(
        f'{{"pull_request":{{"base":{{"sha":"{base}","ref":"portfolio"}}}}}}',
        encoding="utf-8",
    )
    lineage = collect_lineage_metadata(
        repo, environment={"GITHUB_EVENT_PATH": str(event)}
    )
    assert lineage.state == "available"
    assert lineage.comparison_source == "github_base_sha"
    assert lineage.base_is_portfolio is True


def test_missing_comparison_and_non_portfolio_base_are_explicit(repository):
    """No implicit origin/portfolio lookup hides missing or wrong bases."""
    repo, _ = repository
    missing = collect_lineage_metadata(repo)
    assert missing.state == "comparison_missing"
    wrong_base = collect_lineage_metadata(
        repo,
        environment={"GITHUB_BASE_REF": "develop"},
    )
    assert wrong_base.state == "comparison_missing"
    assert wrong_base.base_is_portfolio is False
    assert wrong_base.warnings == ("non_portfolio_base:develop",)
    blank = collect_lineage_metadata(
        repo, environment={"GITHUB_BASE_SHA": "", "GITHUB_BASE_REF": ""}
    )
    assert blank.state == "comparison_missing"
    nested = collect_lineage_metadata(
        repo,
        comparison_sha="HEAD",
        base_ref="feature/portfolio",
    )
    assert nested.base_is_portfolio is False
    assert nested.warnings == ("non_portfolio_base:feature/portfolio",)


def test_missing_ref_is_reported_without_fetch(repository):
    """A missing object is evidence failure, not an implicit network operation."""
    repo, _ = repository
    lineage = collect_lineage_metadata(
        repo,
        comparison_sha="f" * 40,
        base_ref="portfolio",
    )
    assert lineage.state == "comparison_ref_missing"
    assert lineage.relation == "unknown"
    assert "comparison_ref_missing" in lineage.warnings


def test_diverged_history_reports_ahead_and_behind(repository):
    """A stale/diverged branch is represented by symmetric commit counts."""
    repo, root = repository
    git(repo, "checkout", "-b", "comparison")
    comparison = commit(repo, "comparison", "comparison")
    git(repo, "checkout", "-b", "feature", root)
    commit(repo, "feature", "feature")
    lineage = collect_lineage_metadata(
        repo,
        comparison_sha=comparison,
        base_ref="portfolio",
    )
    assert lineage.state == "available"
    assert lineage.ahead == 1
    assert lineage.behind == 1
    assert lineage.relation == "diverged"


def test_explicit_sha_ignores_stale_tracking_configuration(repository):
    """A stale origin/portfolio ref cannot replace the explicit comparison."""
    repo, base = repository
    git(repo, "update-ref", "refs/remotes/origin/portfolio", base)
    git(repo, "config", "branch.master.remote", "origin")
    git(repo, "config", "branch.master.merge", "refs/heads/portfolio")
    commit(repo, "feature", "feature")
    lineage = collect_lineage_metadata(
        repo,
        comparison_sha=base,
        base_ref="origin/portfolio",
    )
    assert lineage.relation == "ahead"
    assert lineage.ahead == 1
    assert lineage.base_is_portfolio is True


def test_shallow_history_categorizes_missing_base(tmp_path, repository):
    """Shallow clones distinguish incomplete history from a bad full ref."""
    source, base = repository
    commit(source, "tip", "tip")
    clone = tmp_path / "shallow"
    subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            source.resolve().as_uri(),
            str(clone),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lineage = collect_lineage_metadata(
        clone,
        comparison_sha=base,
        base_ref="portfolio",
    )
    assert lineage.shallow is True
    assert lineage.state == "history_incomplete"
    assert lineage.warnings == ("history_incomplete",)
