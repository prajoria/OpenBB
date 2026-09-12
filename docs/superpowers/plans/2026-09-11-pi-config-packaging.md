# PI Configuration and Editable Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize the existing paper, order-sink, and snapshot `PI_*`
environment contract behind typed getters and provide a verified installation
path that leaves both portfolio-intel and techtrade editable.

**Architecture:** A pure `openbb_techtrade.config` module owns environment
normalization and defaults while existing factories retain backend construction,
fallback, and path-policy responsibilities. A repository-root installer invokes
pip in deterministic order and verifies PEP 610 editable metadata.

**Tech Stack:** Python 3.12, `pathlib`, `typing.Literal`,
`importlib.metadata`, `subprocess`, pytest, Ruff, Black.

## Global Constraints

- Preserve all existing environment names, defaults, argument precedence, and
  backend fallback behavior.
- Keep the Poetry runtime dependency from portfolio-intel to techtrade.
- Do not alter FMP database code, widget/viewer code, risk code, snapshot
  consumers, execution semantics, or the snapshot path safety policy.
- Use the repository portfolio venv for every Python command.
- Follow RED → GREEN → REFACTOR and keep issue #1972 and issue #1973 claimed
  with `scripts/pi_claim.py`.

---

### Task 1: Typed PI configuration

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/config.py`
- Create: `openbb_platform/extensions/techtrade/tests/unit/test_config.py`

**Interfaces:**
- Produces: `Engine = Literal["mysql", "sqlite"]`
- Produces: `paper_engine(default: Engine = "mysql") -> Engine`
- Produces: `paper_db_path(default: Path | str | None = None) -> Path`
- Produces: `order_sink(default: str = "paper") -> str`
- Produces: `order_sink_paper_dir(default: Path | str | None = None) -> Path`
- Produces: `snapshot_engine(default: Engine = "mysql") -> Engine`
- Produces: `snapshot_db_path(default: Path | str | None = None) -> Path`

- [ ] **Step 1: Write failing getter tests**

Cover unset values, environment overrides, caller-supplied defaults, case and
whitespace normalization for enum values, and clear `ValueError` messages for
unsupported paper/snapshot engines and order sinks. Assert path getters preserve
relative and tilde-containing overrides as `Path` values and use the established
per-user defaults when unset or empty.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
$PYTHON -m pytest openbb_platform/extensions/techtrade/tests/unit/test_config.py -q
```

Expected: collection fails because `openbb_techtrade.config` does not exist.

- [ ] **Step 3: Implement the pure getters**

Read `os.environ` at call time. Use one private enum parser that normalizes the
selected environment value and emits
`"<ENV> must be one of '<a>' | '<b>'; got '<value>'"` for invalid values.
Use one private path parser that treats an unset or empty value as the supplied
default or the established `Path.home() / ".portfolio_intel" / ...` fallback.
Do not create directories or resolve paths in this module.

- [ ] **Step 4: Run the tests and verify GREEN**

Run the Task 1 pytest command. Expected: all `test_config.py` tests pass.

### Task 2: Migrate selector seams

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/paper_engine.py:1001-1060`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/execution/order_sink.py:635-688`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py:2747-2865`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_paper_engine.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_order_sink.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py`

**Interfaces:**
- Consumes: all getters from Task 1.
- Produces: unchanged `get_default_engine`, `get_default_sink`, and
  `get_default_snapshot_store` public behavior.

- [ ] **Step 1: Add regression assertions to the getter tests**

Monkeypatch each imported getter at its consumer module and assert the selector
uses the returned value/path while explicit `db_path` or `paper_dir` arguments
still take precedence.

- [ ] **Step 2: Run focused selector tests and verify RED**

```powershell
$PYTHON -m pytest `
  openbb_platform/extensions/techtrade/tests/unit/test_config.py `
  openbb_platform/extensions/techtrade/tests/unit/test_paper_engine.py `
  openbb_platform/extensions/techtrade/tests/unit/test_order_sink.py `
  openbb_platform/extensions/techtrade/tests/unit/test_snapshot_store.py -q
```

Expected: new monkeypatch assertions fail because selectors still read
`os.environ` directly.

- [ ] **Step 3: Replace direct reads**

Import the getters by module (`from openbb_techtrade import config`) so tests can
patch one stable seam. Replace only selector environment reads. Retain
`os.replace` in the order sink and remove `os` imports only where otherwise
unused.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 2 command. Expected: all selected tests pass.

### Task 3: Guarded editable installer

**Files:**
- Create: `scripts/pi_install.py`
- Create: `openbb_platform/tests/test_pi_install.py`
- Modify: `CLAUDE.md:570-620`

**Interfaces:**
- Produces: `install(repo_root: Path, *, dry_run: bool = False) -> None`
- Produces: `is_editable(distribution_name: str) -> bool`
- Produces: CLI `python scripts/pi_install.py [--dry-run]`

- [ ] **Step 1: Write failing installer tests**

Patch `subprocess.run` and assert two checked commands use `sys.executable`:

```text
python -m pip install -e <repo>/openbb_platform/extensions/portfolio_intel
python -m pip install -e <repo>/openbb_platform/extensions/techtrade
```

Assert portfolio-intel runs first, techtrade last, dry-run invokes neither, and
metadata verification rejects missing, malformed, or non-editable
`direct_url.json`.

- [ ] **Step 2: Run installer tests and verify RED**

```powershell
$PYTHON -m pytest openbb_platform/tests/test_pi_install.py -q
```

Expected: collection fails because `scripts.pi_install` does not exist.

- [ ] **Step 3: Implement installation and verification**

Use `argparse`, `importlib.metadata.distribution`, `json.loads`, and
`subprocess.run(..., check=True)`. Derive the repository root from
`Path(__file__).resolve().parents[1]`. Print commands and a final success line,
but never print package metadata URLs because they may contain local paths.

- [ ] **Step 4: Replace the manual workaround documentation**

Make `python scripts/pi_install.py` the canonical paired editable-install
command. Explain that raw pip cannot encode a transitive editable requirement
and that `--dry-run` previews the commands.

- [ ] **Step 5: Run installer tests and verify GREEN**

Run the Task 3 pytest command. Expected: all installer tests pass.

### Task 4: Quality gates and real-path verification

**Files:**
- Create (ignored evidence): `.dev-cycle/verify-phase6.log`

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: test, lint, formatting, and editable-metadata evidence.

- [ ] **Step 1: Run focused unit tests**

Run the combined Task 2 and Task 3 pytest paths. Expected: zero failures.

- [ ] **Step 2: Run diagnostics**

```powershell
$PYTHON -m ruff check scripts/pi_install.py `
  openbb_platform/tests/test_pi_install.py `
  openbb_platform/extensions/techtrade/openbb_techtrade/config.py `
  openbb_platform/extensions/techtrade/openbb_techtrade/execution/paper_engine.py `
  openbb_platform/extensions/techtrade/openbb_techtrade/execution/order_sink.py `
  openbb_platform/extensions/techtrade/openbb_techtrade/snapshot/store.py `
  openbb_platform/extensions/techtrade/tests/unit/test_config.py
$PYTHON -m black --check <same paths>
```

Expected: both commands exit zero.

- [ ] **Step 3: Drive the configuration path**

Run a fresh interpreter with explicit environment values and print the six
getter return values plus invalid-value rejection. Capture stdout in
`.dev-cycle/verify-phase6.log`.

- [ ] **Step 4: Drive the packaging path**

Run `scripts/pi_install.py` in the isolated portfolio venv. Query
`importlib.metadata` and append only package names plus editable booleans to the
evidence log. Expected: both booleans are `True`.

- [ ] **Step 5: Review, commit, push, and open one PR**

Review the complete diff, commit with both issue references and the Copilot
trailer, push `feat/pi-config-packaging-gh-1972`, and open one fork-internal PR
to `portfolio` whose body contains separate `Closes #1972.` and
`Closes #1973.` lines.
