"""Tests for the dual-MCP lock replay asserter (#2245)."""

import sys
from pathlib import Path

from packaging.markers import default_environment

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "mcp_locks"))

import assert_lock_replay  # noqa: E402  pylint: disable=wrong-import-position

LOCK = (
    "# locked-at: 2026-10-25T05:00:00Z\n"
    "colorama==0.4.6 ; sys_platform == 'win32' \\\n"
    "    --hash=sha256:00\n"
    "    # via click\n"
    "UVLoop==0.21.0 ; sys_platform != 'win32' \\\n"
    "    --hash=sha256:11\n"
    "idna==3.11 \\\n"
    "    --hash=sha256:22\n"
)


def test_expected_honors_markers():
    """Linux replays expect only pins whose markers apply to Linux."""
    environment = {**default_environment(), "sys_platform": "linux"}
    assert assert_lock_replay.expected_from_lock(LOCK, environment) == {
        "uvloop": "0.21.0",
        "idna": "3.11",
    }


def test_expected_honors_markers_on_windows():
    """Windows replays expect only pins whose markers apply to Windows."""
    environment = {**default_environment(), "sys_platform": "win32"}
    assert assert_lock_replay.expected_from_lock(LOCK, environment) == {
        "colorama": "0.4.6",
        "idna": "3.11",
    }


def test_compare_reports_missing_unexpected_and_version():
    """Every kind of divergence is reported once."""
    messages = assert_lock_replay.compare({"a": "1", "b": "2"}, {"b": "3", "c": "1"})
    assert sorted(messages) == [
        "missing a==1",
        "unexpected c==1",
        "version b: lock 2 installed 3",
    ]


class _FakeDistribution:  # pylint: disable=too-few-public-methods
    """Minimal stand-in for importlib.metadata.Distribution."""

    def __init__(self, name, version, location, direct_url=None):
        self.metadata = {"Name": name}
        self.version = version
        self._location = Path(location)
        self._direct_url = direct_url

    def read_text(self, filename):
        return self._direct_url if filename == "direct_url.json" else None

    def locate_file(self, path):
        return self._location / path


def test_installed_ignores_interpreter_bundled_and_editable_distributions(tmp_path):
    """Interpreter-bundled and editable packages are not judged against the lock."""
    base, env = tmp_path / "python", tmp_path / "env"
    distributions = [
        _FakeDistribution("pip", "26.1.2", base / "Lib" / "site-packages"),
        _FakeDistribution("FastMCP", "3.4.0", env / "Lib" / "site-packages"),
        _FakeDistribution(
            "openbb-core",
            "1.0",
            env / "Lib" / "site-packages",
            direct_url='{"url": "file:///x", "dir_info": {"editable": true}}',
        ),
    ]
    assert assert_lock_replay.installed(
        distributions, base_prefix=str(base), prefix=str(env)
    ) == {"fastmcp": "3.4.0"}


def test_installed_keeps_everything_outside_a_virtual_environment(tmp_path):
    """Without a venv, base-prefix packages are still judged."""
    distributions = [_FakeDistribution("pip", "26.1.2", tmp_path / "site-packages")]
    assert assert_lock_replay.installed(
        distributions, base_prefix=str(tmp_path), prefix=str(tmp_path)
    ) == {"pip": "26.1.2"}


def test_compare_clean():
    """Identical lock and environment produce no messages."""
    assert assert_lock_replay.compare({"a": "1"}, {"a": "1"}) == []
