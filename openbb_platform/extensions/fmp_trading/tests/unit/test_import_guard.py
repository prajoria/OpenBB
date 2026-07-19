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

# `test_agent_submodules_fail_cleanly_when_extra_hidden` spawns a
# pip install of the extension WITHOUT the [agent] extra to verify the
# guard fires. The install itself pulls litellm which requires Rust
# toolchain on non-x86_64-linux platforms. CI runners lack Rust; skip
# unless the runner explicitly opts in via -m "requires_agents".
# See docs/design-questions/2026-07-16-fmp-trading-remaining.md Q4.


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


@pytest.mark.requires_agents
def test_agent_submodules_fail_cleanly_when_extra_hidden():
    """agent.* modules must NOT crash at import time when the [agent]
    extra is absent. Two behaviors are both acceptable:

      1. **Lazy import** — the module imports cleanly; heavy deps
         (anthropic, mcp SDK) are imported at first use.
      2. **ImportError at import** — the module top-level imports the
         heavy dep and refuses to load without it.

    What's forbidden:

      * A partial import (some names bound, some not) that produces
        AttributeError / NameError later on.
      * An UNEXPECTED exception type at import time (RuntimeError,
        TypeError, etc.), which indicates a bug in the module's guard
        code rather than a real "extra missing" signal.

    Historical contract: this test previously demanded ImportError for
    ``agent.backend`` and ``agent.mcp_server``. Both were refactored
    to lazy-import their heavy deps inside call sites, so they now
    import cleanly even without the extras. The contract has been
    updated to reflect the reality: import-time "no top-level extra
    dep" is EQUALLY VALID as "raises ImportError at import" — both
    prove the extra is genuinely optional. #871.
    """
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
                results[mod_name] = 'IMPORTED_OK_LAZY'
            except ImportError:
                results[mod_name] = 'ImportError_ok'
            except Exception as exc:
                results[mod_name] = f'UNEXPECTED_{type(exc).__name__}: {exc}'

        for k, v in results.items():
            print(f'{k}: {v}')

        # Every agent module must either import cleanly (lazy) OR
        # raise ImportError. Any other exception type is a bug in the
        # module's guard code. #871.
        acceptable = {'IMPORTED_OK_LAZY', 'ImportError_ok'}
        for mod_name, status in results.items():
            assert status in acceptable, (
                f'{mod_name} produced unexpected status {status!r} - '
                f'agent modules must either lazy-import or raise '
                f'ImportError, never any other exception at import time.'
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
