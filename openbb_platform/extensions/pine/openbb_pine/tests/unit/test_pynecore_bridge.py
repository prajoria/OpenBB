"""E0.5 gate: pynecore_bridge module exists with install_pynecore_path +
is_pynecore_installed, and is idempotent (safe to call multiple times)."""


def test_bridge_module_exports_expected_functions() -> None:
    from openbb_pine.runtime import pynecore_bridge
    assert callable(pynecore_bridge.install_pynecore_path)
    assert callable(pynecore_bridge.is_pynecore_installed)


def test_bridge_is_idempotent() -> None:
    import sys
    from openbb_pine.runtime import pynecore_bridge

    before = list(sys.path)
    pynecore_bridge.install_pynecore_path()
    pynecore_bridge.install_pynecore_path()
    pynecore_bridge.install_pynecore_path()

    # The bridge's own insertion (if any) must appear at most once. In a dev
    # venv where pynecore is already importable via an editable/pip install,
    # the bridge is a pure no-op and sys.path is unchanged. Otherwise the
    # submodule src/ dir gets prepended exactly once, no matter how many
    # times install_pynecore_path() is called.
    src_dir = str(pynecore_bridge._submodule_src_dir())
    assert sys.path.count(src_dir) <= 1
    # No entries other than (optionally) the src_dir should have been added.
    extra = [p for p in sys.path if p not in before and p != src_dir]
    assert extra == [], f"bridge inserted unexpected paths: {extra}"


def test_bridge_is_noop_when_pynecore_already_installed() -> None:
    import sys
    from openbb_pine.runtime import pynecore_bridge

    # If pynecore is already importable, no path insertion should happen
    if pynecore_bridge.is_pynecore_installed():
        before = list(sys.path)
        pynecore_bridge.install_pynecore_path()
        assert sys.path == before, "bridge should be a no-op when pynecore is already installed"
