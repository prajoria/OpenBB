"""Security tests for the quant-scraper CLI.

Regression tests for OpenBBTechnical-1uie / 55mp — the git argv
construction and the target-path resolution in
``Tools/quant_scraper/scrape_quant_strategies.py``.

Two attack vectors are covered:

1. **Git argv injection via target-path starting with ``-``.**
   Lines 122-127 build ``['git', 'clone', ..., url, str(local)]`` and
   ``['git', '-C', str(local), 'pull', '--ff-only']``. If the operator
   supplies ``--target -evil`` (or ``QUANT_REPO_PATH=-evil`` in ``.env``,
   or ``clone.target_dir = "-evil"`` in ``config.toml``), the positional
   ``-evil`` path gets interpreted as a ``git`` flag rather than a
   destination path. The classic ``git``/``ssh`` argv-injection surface.

2. **Missing timeout on subprocess.run.** A hung ``git`` (network or
   local hook) freezes the executor indefinitely. Adding a ``timeout=``
   argument bounds the wait.

Both defenses tested here as REGRESSION LOCKS: any refactor that
drops the ``--`` separator, the target validation, or the timeout
should fail these tests loudly.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure quant_scraper is importable — it's a script-style module under Tools/.
_SCRAPER_DIR = Path(__file__).resolve().parents[1] / "quant_scraper"
if str(_SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_DIR))

import scrape_quant_strategies as mod  # noqa: E402

# ---------------------------------------------------------------------------
# Git argv-injection defenses
# ---------------------------------------------------------------------------


def test_run_git_clone_argv_includes_double_dash_separator(tmp_path):
    """``git clone`` argv must contain ``--`` before the positional path args.

    Regression test for OpenBBTechnical-55mp — without ``--`` a target
    path starting with ``-`` (from ``--target -evil``, ``.env`` value, or
    ``config.toml`` clone.target_dir) would be interpreted as a git flag.
    """
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch.object(subprocess, "run", side_effect=fake_run):
        mod.run_git(
            action="clone",
            slug="foo/bar",
            local=tmp_path / "foo__bar",
            shallow=False,
        )

    cmd = captured["cmd"]
    assert "clone" in cmd, f"expected clone argv, got: {cmd!r}"
    # -- must appear BEFORE the last two positional args (url + path).
    assert "--" in cmd, f"clone argv missing '--' separator: {cmd!r}"
    dash_idx = cmd.index("--")
    # Positional args must follow the --
    assert dash_idx < len(cmd) - 2, f"'--' must be followed by url + path, got: {cmd!r}"
    # And the two args after -- are the url + the destination.
    assert cmd[dash_idx + 1].startswith("https://github.com/"), cmd
    assert cmd[dash_idx + 2] == str(tmp_path / "foo__bar"), cmd


def test_run_git_pull_argv_includes_double_dash_separator(tmp_path):
    """``git -C <path> pull`` argv also gets a ``--`` before positional args.

    The pull path uses ``-C <path>`` (a git option that takes a path
    operand) rather than a bare positional path, so this variant is
    less exposed. Still, adding ``--`` after ``pull --ff-only`` locks
    in that any future refactor introducing positional args is safe.
    """
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    (tmp_path / "foo__bar").mkdir()
    with patch.object(subprocess, "run", side_effect=fake_run):
        mod.run_git(
            action="pull",
            slug="foo/bar",
            local=tmp_path / "foo__bar",
            shallow=False,
        )

    cmd = captured["cmd"]
    assert "pull" in cmd, f"expected pull argv, got: {cmd!r}"
    assert "--" in cmd, f"pull argv missing '--' separator: {cmd!r}"


def test_run_git_subprocess_call_has_timeout(tmp_path):
    """``subprocess.run`` must be called with a ``timeout=`` kwarg.

    A hung ``git`` (network or local hook) would freeze the executor
    indefinitely without a timeout. bd-1uie flags this as part of the
    fix scope.
    """
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["kwargs"] = kwargs

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch.object(subprocess, "run", side_effect=fake_run):
        mod.run_git(
            action="clone",
            slug="foo/bar",
            local=tmp_path / "foo__bar",
            shallow=False,
        )

    assert (
        "timeout" in captured["kwargs"]
    ), f"subprocess.run() called without timeout: kwargs={captured['kwargs']!r}"
    # Sanity-check the timeout is a reasonable positive number.
    assert isinstance(captured["kwargs"]["timeout"], (int, float))
    assert captured["kwargs"]["timeout"] > 0


# ---------------------------------------------------------------------------
# Target-path validation defenses
# ---------------------------------------------------------------------------


def test_resolve_target_rejects_paths_starting_with_dash(tmp_path):
    """Target paths that begin with ``-`` must be rejected up front.

    Belt-and-braces: even with ``--`` in the git argv, a target like
    ``-evil`` in the operator's ``.env`` is a signal of intentional
    tampering that should surface immediately, not be silently coerced.
    """
    import argparse

    args = argparse.Namespace(target=Path("-evil"))
    with pytest.raises(ValueError, match="dash"):
        mod.resolve_target(args, cfg={}, repo_root=tmp_path)


def test_resolve_target_rejects_env_paths_starting_with_dash(tmp_path, monkeypatch):
    """``QUANT_REPO_PATH=-evil`` from .env / environment is rejected."""
    import argparse

    monkeypatch.setenv("QUANT_REPO_PATH", "-evil")
    args = argparse.Namespace(target=None)
    with pytest.raises(ValueError, match="dash"):
        mod.resolve_target(args, cfg={}, repo_root=tmp_path)


def test_resolve_target_rejects_cfg_paths_starting_with_dash(tmp_path, monkeypatch):
    """``config.toml`` ``clone.target_dir = "-evil"`` is rejected."""
    import argparse

    # Ensure env doesn't shadow the cfg branch.
    monkeypatch.delenv("QUANT_REPO_PATH", raising=False)
    args = argparse.Namespace(target=None)
    cfg = {"clone": {"target_dir": "-evil"}}
    with pytest.raises(ValueError, match="dash"):
        mod.resolve_target(args, cfg, tmp_path)


def test_resolve_target_accepts_normal_paths(tmp_path, monkeypatch):
    """Non-dash-prefixed paths from all 3 sources still resolve correctly."""
    import argparse

    monkeypatch.delenv("QUANT_REPO_PATH", raising=False)

    # CLI arg wins
    args = argparse.Namespace(target=tmp_path / "repos")
    result = mod.resolve_target(args, cfg={}, repo_root=tmp_path)
    assert result == tmp_path / "repos"

    # Env wins over cfg
    monkeypatch.setenv("QUANT_REPO_PATH", str(tmp_path / "env_repos"))
    args = argparse.Namespace(target=None)
    result = mod.resolve_target(
        args, cfg={"clone": {"target_dir": "cfg"}}, repo_root=tmp_path
    )
    assert result == Path(str(tmp_path / "env_repos"))


def test_resolve_target_none_when_all_sources_empty(tmp_path, monkeypatch):
    """Unchanged behaviour: no target from any source returns None."""
    import argparse

    monkeypatch.delenv("QUANT_REPO_PATH", raising=False)
    args = argparse.Namespace(target=None)
    result = mod.resolve_target(args, cfg={}, repo_root=tmp_path)
    assert result is None


def test_run_git_timeout_expired_returns_failed_status(tmp_path):
    """subprocess.TimeoutExpired must be caught and mapped to ('failed', <detail>).

    Regression test for Round-1 review finding (both silent-failure-hunter
    and code-reviewer flagged). Without this, the first timing-out repo
    in a batch raises TimeoutExpired out of run_git → work() → ex.map()
    iteration, aborting the whole batch and skipping the ``.scrape_state
    .json`` write. Matches the existing ``failed`` status contract used
    for non-zero returncodes.
    """

    def fake_run(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    with patch.object(subprocess, "run", side_effect=fake_run):
        status, detail = mod.run_git(
            action="clone",
            slug="foo/bar",
            local=tmp_path / "foo__bar",
            shallow=False,
        )

    assert status == "failed", f"expected 'failed', got {status!r}"
    assert (
        "timed out" in detail.lower()
    ), f"detail should mention timeout, got: {detail!r}"
    # And it should NOT raise — that's the whole point.


def test_run_git_timeout_expired_pull_path(tmp_path):
    """Same TimeoutExpired handling on the pull path (parity check)."""

    def fake_run(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    (tmp_path / "foo__bar").mkdir()
    with patch.object(subprocess, "run", side_effect=fake_run):
        status, detail = mod.run_git(
            action="pull",
            slug="foo/bar",
            local=tmp_path / "foo__bar",
            shallow=False,
        )

    assert status == "failed"
    assert "timed out" in detail.lower()


def test_main_returns_2_on_dash_prefixed_target_from_cli(tmp_path, capsys):
    """``main()`` returns 2 (not tracebacks) when resolve_target raises ValueError.

    Regression test for Round-1 review MEDIUM finding — the
    ``ValueError`` from ``_reject_dash_prefixed_path`` used to bubble
    unhandled out of ``main`` with a full traceback. Now it prints a
    clean ERROR line and returns 2, matching the existing config-error
    contract.
    """
    # Note: use --target=-evil (equals syntax) so argparse accepts '-evil'
    # as a value rather than treating it as another option. In practice
    # operator CLI attackers also use =, or set QUANT_REPO_PATH/config.toml.
    argv = ["--target=-evil", "--config", str(tmp_path / "no_such_config.toml")]
    rc = mod.main(argv)
    assert rc == 2, f"main() should return 2 on dash-prefixed target, got {rc}"
    captured = capsys.readouterr()
    assert "ERROR" in captured.out or "ERROR" in captured.err
    assert "dash" in (captured.out + captured.err).lower()
