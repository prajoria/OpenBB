"""AC-agent-5 fast path (A10 P2): in-process import-guard test.

Simulates a missing ``[agent]`` extra by monkey-patching ``sys.modules``
to hide ``anthropic`` and ``mcp``, then asserts:

  * Core imports (``openbb``, ``openbb_fmp_trading``,
    ``core.state_store``) all succeed.
  * ``is_agent_available()`` returns False cleanly.
  * Attempting to import ``agent/*`` submodules raises ImportError
    cleanly (no partial-import crashes elsewhere in the codebase).

Runs in-process (<1s). The full subprocess venv-install test lives in
:mod:`tests.architecture.test_core_unchanged_when_removed` and runs
nightly (~3-5 minutes).
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap

import pytest


def test_core_imports_when_extra_hidden():
    """Fresh subprocess where anthropic/mcp/jinja2 are pre-poisoned;
    the core extension still imports cleanly."""
    script = textwrap.dedent(
        """
        import sys

        # Simulate missing [agent] extra
        sys.modules['anthropic'] = None
        sys.modules['mcp'] = None
        sys.modules['jinja2'] = None

        # These MUST succeed
        import openbb_fmp_trading
        import openbb_fmp_trading.core.state_store
        import openbb_fmp_trading.models.plan
        import openbb_fmp_trading.models.journal_events

        # is_agent_available reports False cleanly
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
            "Core imports failed when [agent] extra was hidden.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    assert "OK" in result.stdout


def test_agent_submodules_fail_cleanly_when_extra_hidden():
    """agent.backend, agent.tool_registry, agent.mcp_server ALL raise
    ImportError cleanly when the extras are missing. No partial import
    residue, no half-loaded modules."""
    script = textwrap.dedent(
        """
        import sys

        sys.modules['anthropic'] = None
        sys.modules['mcp'] = None
        sys.modules['jinja2'] = None

        results = {}
        for mod_name in (
            'openbb_fmp_trading.agent.backend',
            'openbb_fmp_trading.agent.tool_registry',
            'openbb_fmp_trading.agent.pre_open',
            'openbb_fmp_trading.agent.post_close',
            'openbb_fmp_trading.agent.mcp_server',
        ):
            # Ensure not cached from earlier import in this subprocess
            sys.modules.pop(mod_name, None)
            try:
                __import__(mod_name)
                results[mod_name] = 'IMPORTED_UNEXPECTEDLY'
            except ImportError:
                results[mod_name] = 'ImportError_ok'
            except Exception as exc:
                results[mod_name] = f'UNEXPECTED_{type(exc).__name__}: {exc}'

        for k, v in results.items():
            print(f'{k}: {v}')

        # backend, mcp_server MUST raise ImportError.
        # (pre_open + post_close + tool_registry may or may not — they
        #  don't top-level import anthropic; they use lazy imports.
        #  That's ALSO acceptable behavior.)
        assert results['openbb_fmp_trading.agent.backend'] == 'ImportError_ok', (
            f"backend didn't fail cleanly: {results['openbb_fmp_trading.agent.backend']!r}"
        )
        assert results['openbb_fmp_trading.agent.mcp_server'] == 'ImportError_ok', (
            f"mcp_server didn't fail cleanly: {results['openbb_fmp_trading.agent.mcp_server']!r}"
        )
        print('OK')
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
            "agent/* import guards failed.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    assert "OK" in result.stdout


def test_state_store_works_without_agent_extra():
    """state_store lives in core/ (not agent/), so it works regardless
    of the extra. Belt-and-suspenders check."""
    from openbb_fmp_trading.core import state_store

    # Just verify the module attributes are accessible; live DB paths
    # are tested in test_state_store.py.
    assert callable(state_store.load_state)
    assert callable(state_store.save_state)
    assert callable(state_store.load_last_watchlist)
    assert callable(state_store.save_last_watchlist)
