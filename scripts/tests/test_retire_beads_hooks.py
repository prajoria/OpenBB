"""Tests for retiring the Beads Git hook integration (#2235)."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import retire_beads_hooks  # noqa: E402  pylint: disable=wrong-import-position

BEADS_SECTION = (
    "# --- BEGIN BEADS INTEGRATION v1.0.4 ---\n"
    "if command -v bd >/dev/null 2>&1; then\n"
    '  bd hooks run pre-commit "$@"\n'
    "fi\n"
    "# --- END BEADS INTEGRATION v1.0.4 ---\n"
)


def _run_git(repo: Path, *args: str, check: bool = True):
    """Run git in ``repo``."""
    # Fixed executable; arguments are passed without a shell.
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=check,
        capture_output=True,
        text=True,
    )


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return stripped stdout."""
    return _run_git(repo, *args).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """Return a git repo whose hooksPath points at a Beads hooks directory."""
    _git(tmp_path, "init", "-q")
    beads_hooks = tmp_path / ".beads" / "hooks"
    beads_hooks.mkdir(parents=True)
    (beads_hooks / "pre-commit").write_text(
        "#!/usr/bin/env sh\n" + BEADS_SECTION, encoding="utf-8"
    )
    _git(tmp_path, "config", "core.hooksPath", str(beads_hooks))
    return tmp_path


def _hooks_dir(repo: Path) -> Path:
    return (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        / "hooks"
    )


def test_check_flags_hooks_path_into_beads(repo):
    """A hooksPath pointing at .beads/hooks is reported."""
    problems = retire_beads_hooks.find_problems(repo)
    assert any("core.hooksPath" in p for p in problems)


def test_check_flags_beads_section_in_default_hooks(tmp_path):
    """A Beads section inside .git/hooks is reported even without hooksPath."""
    _git(tmp_path, "init", "-q")
    (_hooks_dir(tmp_path) / "pre-commit").write_text(
        "#!/usr/bin/env sh\n" + BEADS_SECTION, encoding="utf-8"
    )
    problems = retire_beads_hooks.find_problems(tmp_path)
    assert problems == ["pre-commit: contains the Beads integration section"]


def test_migrate_unsets_hooks_path_and_check_passes(repo):
    """Migration removes the hooksPath and leaves nothing to report."""
    retire_beads_hooks.migrate(repo)
    result = _run_git(repo, "config", "--get", "core.hooksPath", check=False)
    assert result.returncode == 1, f"hooksPath still set: {result.stdout!r}"
    assert retire_beads_hooks.find_problems(repo) == []


def test_migrate_preserves_non_beads_hook_content(repo):
    """Custom lines outside the Beads markers move into .git/hooks."""
    hook = repo / ".beads" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/usr/bin/env sh\necho custom-check\n" + BEADS_SECTION, encoding="utf-8"
    )
    retire_beads_hooks.migrate(repo)
    kept = (_hooks_dir(repo) / "pre-commit").read_text(encoding="utf-8")
    assert "echo custom-check" in kept
    assert "bd hooks run" not in kept


def test_migrate_drops_hooks_that_were_only_beads(repo):
    """A hook with nothing but the Beads section is not recreated."""
    retire_beads_hooks.migrate(repo)
    assert not (_hooks_dir(repo) / "pre-commit").exists()


def test_migrate_strips_beads_section_from_default_hooks(tmp_path):
    """Beads sections already in .git/hooks are removed, other lines kept."""
    _git(tmp_path, "init", "-q")
    hook = _hooks_dir(tmp_path) / "pre-commit"
    hook.write_text(
        "#!/usr/bin/env sh\n" + BEADS_SECTION + "echo after\n", encoding="utf-8"
    )
    retire_beads_hooks.migrate(tmp_path)
    text = hook.read_text(encoding="utf-8")
    assert "BEADS INTEGRATION" not in text
    assert "echo after" in text


def test_migrate_is_idempotent(repo):
    """A second migration changes nothing."""
    first = retire_beads_hooks.migrate(repo)
    second = retire_beads_hooks.migrate(repo)
    assert first and second == []


def test_migrate_refuses_to_overwrite_existing_hook(repo):
    """A pre-existing default hook is never clobbered; config stays put."""
    (repo / ".beads" / "hooks" / "pre-commit").write_text(
        "#!/usr/bin/env sh\necho custom\n" + BEADS_SECTION, encoding="utf-8"
    )
    existing = _hooks_dir(repo) / "pre-commit"
    existing.write_text("#!/usr/bin/env sh\necho mine\n", encoding="utf-8")
    with pytest.raises(retire_beads_hooks.MigrationConflict):
        retire_beads_hooks.migrate(repo)
    assert existing.read_text(encoding="utf-8") == "#!/usr/bin/env sh\necho mine\n"
    assert _git(repo, "config", "--get", "core.hooksPath")


def test_committed_beads_hooks_never_invoke_bd():
    """Tracked .beads/hooks are inert so stale hooksPath configs run no Beads."""
    hooks = sorted((ROOT / ".beads" / "hooks").iterdir())
    assert hooks, "expected the tracked historical hook stubs"
    for hook in hooks:
        text = hook.read_text(encoding="utf-8")
        assert "bd " not in text, f"{hook.name} still invokes bd"
        assert "retire_beads_hooks.py" in text, f"{hook.name} lacks the fix hint"


def _retired_stub(name: str) -> str:
    """Return the tracked retired stub for hook ``name``."""
    return (ROOT / ".beads" / "hooks" / name).read_text(encoding="utf-8")


def test_migrate_does_not_copy_retired_stubs(repo):
    """Stubs in .beads/hooks are Beads-owned: nothing moves to .git/hooks."""
    (repo / ".beads" / "hooks" / "pre-commit").write_text(
        _retired_stub("pre-commit"), encoding="utf-8"
    )
    retire_beads_hooks.migrate(repo)
    assert not (_hooks_dir(repo) / "pre-commit").exists()
    assert retire_beads_hooks.find_problems(repo) == []


def test_migrate_removes_retired_stub_copied_into_default_hooks(tmp_path):
    """A stub already copied into .git/hooks is reported and removed."""
    _git(tmp_path, "init", "-q")
    hook = _hooks_dir(tmp_path) / "pre-commit"
    hook.write_text(_retired_stub("pre-commit"), encoding="utf-8")
    assert retire_beads_hooks.find_problems(tmp_path) == [
        "pre-commit: is a retired Beads stub"
    ]
    retire_beads_hooks.migrate(tmp_path)
    assert not hook.exists()


def test_migrate_keeps_stub_with_custom_lines(repo):
    """A stub someone extended is not a stub: its content is preserved."""
    (repo / ".beads" / "hooks" / "pre-commit").write_text(
        _retired_stub("pre-commit") + "echo-free-custom-check\n", encoding="utf-8"
    )
    retire_beads_hooks.migrate(repo)
    kept = (_hooks_dir(repo) / "pre-commit").read_text(encoding="utf-8")
    assert "echo-free-custom-check" in kept
