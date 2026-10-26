"""Tests for the dual-MCP dependency lock generator (#2245)."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lock_mcp_envs  # noqa: E402  pylint: disable=wrong-import-position

PLATFORM = lock_mcp_envs.ENVIRONMENTS[0]
WORKSPACE = lock_mcp_envs.ENVIRONMENTS[1]
STAMP = datetime(2026, 10, 25, 5, 0, tzinfo=UTC)


def _writer(body: str):
    """Return a fake compile step that writes ``body`` to the output path."""

    def fake_compile(_spec, output: Path, *, upgrade: bool) -> None:
        del upgrade
        output.write_text(body, encoding="utf-8")

    return fake_compile


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    """Point LOCK_DIR at an isolated directory."""
    monkeypatch.setattr(lock_mcp_envs, "LOCK_DIR", tmp_path)
    return tmp_path


def test_parse_locked_at_reads_header():
    """The rendered header round-trips its compile timestamp."""
    text = lock_mcp_envs.render(PLATFORM, "a==1\n", STAMP)
    assert lock_mcp_envs.parse_locked_at(text) == STAMP


def test_parse_locked_at_rejects_missing_header():
    """A lock without a locked-at line is rejected, not defaulted."""
    with pytest.raises(ValueError, match="missing locked-at header"):
        lock_mcp_envs.parse_locked_at("a==1\n")


def test_lock_body_strips_only_generator_header():
    """Only generator header lines are removed; uv annotations survive."""
    body = "# via something\na==1 \\\n    --hash=sha256:00\n"
    assert lock_mcp_envs.lock_body(lock_mcp_envs.render(PLATFORM, body, STAMP)) == body


def test_read_pins_normalizes_and_ignores_hash_and_marker_lines():
    """Pins are PEP 503-normalized; markers and hash lines are skipped."""
    text = (
        "Typing_Extensions==4.15.0 ; python_version < '3.14' \\\n"
        "    --hash=sha256:abc\n"
        "    # via pydantic\n"
    )
    assert lock_mcp_envs.read_pins(text) == {"typing-extensions": "4.15.0"}


def test_check_reports_drift_when_compile_output_differs(lock_dir):
    """A recompile that adds a package is reported as a diff."""
    committed = "a==1\n"
    PLATFORM.out_path.write_text(
        lock_mcp_envs.render(PLATFORM, committed, STAMP), encoding="utf-8"
    )
    drift = lock_mcp_envs.check(
        PLATFORM, compile_fn=_writer(committed + "newdep==1.0\n")
    )
    assert any(line == "+newdep==1.0" for line in drift)


def test_check_is_clean_when_compile_preserves_body(lock_dir):
    """An unchanged recompile is clean and leaves no scratch files."""
    committed = "a==1\n"
    PLATFORM.out_path.write_text(
        lock_mcp_envs.render(PLATFORM, committed, STAMP), encoding="utf-8"
    )
    assert lock_mcp_envs.check(PLATFORM, compile_fn=_writer(committed)) == []
    leftovers = sorted(p.name for p in lock_dir.iterdir())
    assert leftovers == ["platform-mcp.txt"], "check must not leave temp files"


def test_check_reports_missing_lock(lock_dir):
    """A missing committed lock is a check failure with a fix hint."""
    messages = lock_mcp_envs.check(PLATFORM, compile_fn=_writer("a==1\n"))
    assert messages == [
        "platform-mcp: lock file missing; run python scripts/lock_mcp_envs.py"
    ]


def test_sync_keeps_locked_at_when_body_unchanged(lock_dir):
    """Re-syncing an unchanged lock keeps its original timestamp."""
    PLATFORM.out_path.write_text(
        lock_mcp_envs.render(PLATFORM, "a==1\n", STAMP), encoding="utf-8"
    )
    later = datetime(2026, 11, 1, tzinfo=UTC)
    written = lock_mcp_envs.sync(
        PLATFORM, upgrade=False, compile_fn=_writer("a==1\n"), now=later
    )
    assert written is False
    assert lock_mcp_envs.parse_locked_at(PLATFORM.out_path.read_text("utf-8")) == STAMP


def test_sync_bumps_locked_at_when_body_changes(lock_dir):
    """A changed lock body is written with a new timestamp."""
    PLATFORM.out_path.write_text(
        lock_mcp_envs.render(PLATFORM, "a==1\n", STAMP), encoding="utf-8"
    )
    later = datetime(2026, 11, 1, tzinfo=UTC)
    written = lock_mcp_envs.sync(
        PLATFORM, upgrade=True, compile_fn=_writer("a==2\n"), now=later
    )
    text = PLATFORM.out_path.read_text("utf-8")
    assert written is True
    assert lock_mcp_envs.parse_locked_at(text) == later
    assert lock_mcp_envs.lock_body(text) == "a==2\n"


def test_required_versions_mismatch_is_reported(tmp_path):
    """runtime_profiles.json must agree with the Platform lock pins."""
    manifest = tmp_path / "runtime_profiles.json"
    manifest.write_text(
        json.dumps(
            {
                "profiles": {
                    "platform-standard": {"required_versions": {"fastmcp": "3.4.0"}}
                }
            }
        ),
        encoding="utf-8",
    )
    messages = lock_mcp_envs.check_required_versions(manifest, "fastmcp==3.4.6 \\\n")
    assert len(messages) == 1
    assert "3.4.0" in messages[0] and "3.4.6" in messages[0]
    assert lock_mcp_envs.check_required_versions(manifest, "fastmcp==3.4.0\n") == []


@pytest.mark.parametrize("spec", lock_mcp_envs.ENVIRONMENTS, ids=lambda s: s.name)
def test_committed_locks_contain_no_local_paths(spec):
    """Committed locks carry no machine paths and are stamped."""
    text = spec.out_path.read_text(encoding="utf-8")
    for leak in ("file:", ":\\", ":/", "/Users/", "/home/"):
        assert leak not in text, f"{spec.out_path.name} leaks {leak!r}"
    lock_mcp_envs.parse_locked_at(text)


@pytest.mark.parametrize("spec", lock_mcp_envs.ENVIRONMENTS, ids=lambda s: s.name)
def test_committed_locks_hash_every_pin(spec):
    """Every pin carries a sha256 hash for the launcher's --require-hashes sync (#2282)."""
    text = lock_mcp_envs.lock_body(spec.out_path.read_text(encoding="utf-8"))
    blocks = re.split(r"\n(?=[^\s#])", text.strip())
    pinned = [block for block in blocks if "==" in block.splitlines()[0]]
    assert len(pinned) == len(lock_mcp_envs.read_pins(text)) > 0
    unhashed = [b.split()[0] for b in pinned if "--hash=sha256:" not in b]
    assert unhashed == []


def test_committed_locks_pin_direct_requirements():
    """Committed locks pin every direct input and exclude editables."""
    platform = lock_mcp_envs.read_pins(PLATFORM.out_path.read_text(encoding="utf-8"))
    workspace = lock_mcp_envs.read_pins(WORKSPACE.out_path.read_text(encoding="utf-8"))
    assert platform["fastmcp"] == "3.4.0"
    assert {
        k: workspace[k]
        for k in ("fastmcp", "openbb-ai", "pydantic", "starlette", "uvicorn")
    } == {
        "fastmcp": "3.4.6",
        "openbb-ai": "2.1.0",
        "pydantic": "2.12.5",
        "starlette": "1.6.0",
        "uvicorn": "0.52.3",
    }
    for editable in (
        "openbb",
        "openbb-core",
        "openbb-platform-api",
        "openbb-mcp-server",
    ):
        assert editable not in platform, f"editable {editable} leaked into the lock"
