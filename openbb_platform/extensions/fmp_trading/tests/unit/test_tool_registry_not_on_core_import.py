"""AC-agent-10 (A3, P0): tool_registry is NEVER on the core import path.

If ``tool_registry`` loaded at ``import openbb`` time, a router schema
drift could break OpenBB for every user — including those without the
``[agent]`` extra. This test proves the extra-gate holds.

Runs ``import openbb`` in a subprocess and asserts that no
``openbb_fmp_trading.agent.*`` module leaked into ``sys.modules``.
Subprocess isolation is required because the current pytest process may
already have agent modules loaded from other tests — that would give a
false negative here.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest


def test_agent_package_absent_after_core_import():
    """The gold-standard test for A3: fresh Python process, `import openbb`,
    then check sys.modules for any agent leakage.
    """
    script = textwrap.dedent(
        """
        import sys

        # Core imports — these are what a non-[agent] user would trigger
        import openbb
        import openbb_fmp_trading

        # These are the surfaces we explicitly allow at core-import time
        import openbb_fmp_trading.core.state_store

        offenders = sorted(
            m for m in sys.modules
            if m.startswith("openbb_fmp_trading.agent")
        )
        if offenders:
            print("LEAK: " + ", ".join(offenders))
            sys.exit(1)
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "tool_registry / agent modules leaked onto core import path.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    assert "OK" in result.stdout


def test_openbb_import_succeeds_without_agent_extra():
    """Belt-and-suspenders: even if ``anthropic`` / ``mcp`` are absent
    from the venv, ``import openbb_fmp_trading`` must still succeed.

    Simulated in-process by hiding the SDKs from sys.modules and
    importing the extension package fresh.
    """
    script = textwrap.dedent(
        """
        import sys

        # Simulate missing [agent] extra by pre-poisoning the SDKs
        sys.modules['anthropic'] = None
        sys.modules['mcp'] = None
        sys.modules['jinja2'] = None

        import openbb_fmp_trading
        import openbb_fmp_trading.core.state_store

        # is_agent_available should report False cleanly
        from openbb_fmp_trading.agent import is_agent_available
        assert is_agent_available() is False, "is_agent_available should be False"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "Core import failed with [agent] extra missing.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    assert "OK" in result.stdout
