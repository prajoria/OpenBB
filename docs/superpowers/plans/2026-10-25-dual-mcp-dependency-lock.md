# Dual-MCP Dependency Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **This cycle:** executed inline (superpowers:executing-plans). Subagents are blocked because the repo-mandated model `gpt-5.6-sol` is unavailable.

**Goal:** Make `scripts/start-dual-mcp.ps1` launch both MCP servers from committed, complete dependency locks instead of re-resolving transitive dependencies (#2245 (Lock complete dual-MCP transitive dependency graphs)).

**Architecture:** `.in` files hold the direct pins. `scripts/lock_mcp_envs.py` compiles them with `uv pip compile --universal` into `.txt` locks carrying a `locked-at` header. The launcher builds both `uv run` invocations through shared lifecycle-module functions that add `--with-requirements <lock>` and `--exclude-newer <locked-at>`. A replay script proves a clean cache reproduces each lock exactly, and a CI workflow runs check + replay plus a weekly refresh report.

**Tech Stack:** uv 0.11.26, Python 3.13 (envs) / `.venv_portfolio` (tests), PowerShell 7 + Pester (3.4 local, 4.10.1 CI), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-dual-mcp-dependency-lock-design.md`

## Global Constraints

- Envs use `--python 3.13`. Locks are compiled with `--universal --python-version 3.13 --no-header` (hashes dropped in final review; see spec section 7).
- Direct pins, verbatim. Platform: `fastmcp==3.4.0`. Workspace: `fastmcp==3.4.6`, `openbb-ai==2.1.0`, `pydantic==2.12.5`, `starlette==1.6.0`, `uvicorn==0.52.3`.
- Platform editables (unchanged, #2159): `openbb_platform`, `openbb_platform\core`, `openbb_platform\extensions\platform_api`, `openbb_platform\extensions\mcp_server`. Excluded from the lock via `--no-emit-package openbb openbb-core openbb-platform-api openbb-mcp-server`.
- `locked-at` header line format: `# locked-at: <YYYY-MM-DDTHH:MM:SSZ>`, set to the UTC compile time, never a date.
- Committed lock files contain no absolute paths, `file:` URLs, or operator usernames.
- Do not use `UV_CONSTRAINT`/constraints files. `uv run` ignores them.
- New Python passes black (88 cols), ruff, mypy, and pylint (CI General Linting).
- Pester tests stay v3/v4 syntax (`Should Be`, `Should Throw`).
- Commits/push follow the conservative git profile: the change set is proposed and executed only with the user's approval (Phase 8).

## Review Focus

1. A missing lock file, or one without a `locked-at` line, must stop the launcher with a clear error **before any process starts**. Test: Task 2, `Get-McpLockTimestamp` throw cases.
2. An editable `pyproject.toml` gaining a dependency not in the lock must make `--check` fail with a diff. Test: Task 1, `test_check_reports_drift_when_compile_output_differs`.
3. `runtime_profiles.json` `required_versions.fastmcp` drifting from the Platform lock pin must fail `--check`. Test: Task 1, `test_required_versions_mismatch_is_reported`.
4. A regenerated lock must not leak a local path. Test: Task 1, `test_committed_locks_contain_no_local_paths`.
5. A Workspace checkout path containing spaces must survive as one argument. Test: Task 2, `Get-WorkspaceUvArguments` spaced-path case.

---

### Task 1: Lock inputs, generator, and committed locks

**Files:**
- Create: `scripts/mcp_locks/platform-mcp.in`, `scripts/mcp_locks/workspace-mcp.in`
- Create: `scripts/lock_mcp_envs.py`
- Create (generated): `scripts/mcp_locks/platform-mcp.txt`, `scripts/mcp_locks/workspace-mcp.txt`
- Test: `scripts/tests/test_lock_mcp_envs.py`

**Interfaces:**
- Produces:
  - `LOCK_DIR: Path` (= `scripts/mcp_locks`)
  - `@dataclass(frozen=True) class LockSpec: name: str; no_emit: tuple[str, ...]`, with properties `in_path` and `out_path`
  - `ENVIRONMENTS: tuple[LockSpec, ...]` (`platform-mcp`, `workspace-mcp`)
  - `parse_locked_at(text: str) -> datetime` (raises `ValueError("missing locked-at header")`)
  - `lock_body(text: str) -> str` (text minus the generator header lines)
  - `render(spec: LockSpec, body: str, locked_at: datetime) -> str`
  - `read_pins(text: str) -> dict[str, str]` (PEP 503-normalized name → version)
  - `compile_lock(spec: LockSpec, output: Path, *, upgrade: bool) -> None` (runs uv with `cwd=LOCK_DIR`)
  - `sync(spec, *, upgrade: bool, compile_fn=compile_lock, now=None) -> bool` (True if written)
  - `check(spec, *, compile_fn=compile_lock) -> list[str]` (unified-diff lines; empty = clean)
  - `check_required_versions(manifest: Path, platform_lock_text: str) -> list[str]`
  - `main(argv: list[str] | None = None) -> int` (flags `--upgrade`, `--check`)
  - The `platform-mcp.in` `-e` lines are what Task 2's Pester test compares against.

- [ ] **Step 1: Write the `.in` files.** Each starts with a comment block explaining the FastMCP split (3.4.6 needs Starlette ≥ 1.0.1, which conflicts with Platform FastAPI; separate envs never share an interpreter). Platform holds `fastmcp==3.4.0` + four `-e ../../openbb_platform…` lines (forward slashes). Workspace holds the 5 pins.
- [ ] **Step 2: Write failing tests** in `scripts/tests/test_lock_mcp_envs.py` (import via `sys.path.insert(0, str(ROOT / "scripts"))`, one module identity):
  - `test_parse_locked_at_reads_header`: `render(spec, "a==1\n", datetime(2026,10,25,5,0,tzinfo=UTC))` → `parse_locked_at` returns that datetime.
  - `test_parse_locked_at_rejects_missing_header`: `pytest.raises(ValueError, match="missing locked-at header")`.
  - `test_lock_body_strips_only_generator_header`: `lock_body(render(spec, body, t)) == body`.
  - `test_read_pins_normalizes_and_ignores_hash_and_marker_lines`: input with `Typing_Extensions==4.15.0 ; python_version < '3.14' \` + hash continuation → `{"typing-extensions": "4.15.0"}`.
  - `test_check_reports_drift_when_compile_output_differs`: `tmp_path` lock + `compile_fn` that writes committed body + `"newdep==1.0\n"` → non-empty, contains `+newdep==1.0`.
  - `test_check_is_clean_when_compile_preserves_body`: `compile_fn` writes the committed body unchanged → `[]`.
  - `test_sync_keeps_locked_at_when_body_unchanged` / `test_sync_bumps_locked_at_when_body_changes` (inject `now`).
  - `test_required_versions_mismatch_is_reported`: manifest with `required_versions.fastmcp = "3.4.0"` vs lock text `fastmcp==3.4.6` → one message naming both versions. A matching pair → `[]`.
  - `test_committed_locks_contain_no_local_paths`: for each `ENVIRONMENTS` out_path, no `file:`, no `:\\`, no `/Users/`, no `/home/`, and `parse_locked_at` succeeds.
  - `test_committed_locks_pin_direct_requirements`: platform `read_pins` has `fastmcp == "3.4.0"`; workspace has the 5 exact pins.
  - Tests needing `LockSpec` paths use a `monkeypatch` of `LOCK_DIR` → `tmp_path`.
- [ ] **Step 3: Run** `$PY -m pytest scripts/tests/test_lock_mcp_envs.py -q`. Expected: collection error / FAIL (module missing).
- [ ] **Step 4: Implement `scripts/lock_mcp_envs.py`.** `compile_lock` runs `["uv","pip","compile", spec.in_path.name, "--universal","--python-version","3.13","--no-header","--quiet", *(--no-emit-package n for n in no_emit), *(["--upgrade"] if upgrade), "-o", str(output)]` with `cwd=LOCK_DIR`, `check=True`. `sync`/`check` copy `lock_body(committed)` into a temp file inside `LOCK_DIR` (keeps pins; relative annotations), compile into it, and compare bodies. `check` additionally appends `check_required_versions` messages for the platform spec in `main`. The manifest path is `openbb_platform/extensions/mcp_server/openbb_mcp_server/assets/runtime_profiles.json`. Missing committed lock in `check` → message `"<name>: lock file missing; run python scripts/lock_mcp_envs.py"`.
- [ ] **Step 5: Run the unit tests.** Expected: all pass except the two `committed_locks` tests (locks not generated yet).
- [ ] **Step 6: Generate the locks** with `$PY scripts/lock_mcp_envs.py --upgrade` (live uv call). Expected: two files written, then `$PY scripts/lock_mcp_envs.py --check` exits 0.
- [ ] **Step 7: Reverse-verify** (rule 7). Temporarily change `read_pins` normalization to identity → `test_read_pins…` fails. Make `check` return `[]` unconditionally → the drift test fails. Restore both. Run the full file: all pass.
- [ ] **Step 8: Heartbeat** `pi_claim.py 2245 heartbeat`.

### Task 2: Launcher consumes the locks

**Files:**
- Modify: `scripts/mcp_stack_lifecycle.psm1` (add 3 exported functions)
- Modify: `scripts/start-dual-mcp.ps1:234-247` (platform args), `:312-326` (workspace args)
- Test: `scripts/tests/Start-DualMcp.Tests.ps1`

**Interfaces:**
- Consumes: `scripts/mcp_locks/*.txt` header format from Task 1.
- Produces (exported from `mcp_stack_lifecycle.psm1`):
  - `Get-McpLockTimestamp -LockPath <string>` → `string` (the `locked-at` value). Throws `"Dependency lock '<path>' is missing. Run python scripts/lock_mcp_envs.py."` and `"Dependency lock '<path>' has no locked-at header."`.
  - `Get-PlatformUvArguments -OpenBBRoot <string>` → `string[]`: `run --no-project --python 3.13 --exclude-newer <ts> --with-requirements <root>\scripts\mcp_locks\platform-mcp.txt` + 4 × `--with-editable <root>\<editable>`.
  - `Get-WorkspaceUvArguments -OpenBBRoot <string> -WorkspaceBackend <string>` → `string[]`: `run --no-project --python 3.13 --exclude-newer <ts> --with-requirements <root>\scripts\mcp_locks\workspace-mcp.txt --directory <backend>`.

- [ ] **Step 1: Write failing Pester tests** (replace the `"pins Workspace external dependencies exactly"` and `"uses only checkout-local editable Platform packages"` blocks):
  - `"keeps direct pins in the lock inputs"`: `platform-mcp.in` contains `fastmcp==3.4.0`. `workspace-mcp.in` contains the 5 pins. The manifest `required_versions.fastmcp` is `"3.4.0"`. Script text `Should Not Match '"(fastmcp|openbb-ai|pydantic|starlette|uvicorn)=='`.
  - `"launches both servers from the committed locks"`: script text matches `Get-PlatformUvArguments` and `Get-WorkspaceUvArguments`. The platform args contain `--with-requirements` followed by a path ending `mcp_locks\platform-mcp.txt`, and `--exclude-newer` followed by the value `Get-McpLockTimestamp` returns.
  - `"uses only checkout-local editable Platform packages"`: the `--with-editable` values from `Get-PlatformUvArguments -OpenBBRoot $root`, made relative to `$root` with `/`, equal the `-e ../../` paths in `platform-mcp.in` (order-insensitive), and there are exactly 4.
  - `"fails before startup when a lock is missing or unstamped"`: `Get-McpLockTimestamp` on a `$TestDrive` missing path throws the missing message. On a file without the header, it throws the header message.
  - `"keeps a spaced Workspace path as one argument"`: `Get-WorkspaceUvArguments -WorkspaceBackend "C:\Work Space\backend"`, the element after `--directory` equals that exact string.
- [ ] **Step 2: Run** `pwsh -NoProfile -c "Invoke-Pester scripts/tests/Start-DualMcp.Tests.ps1"`. Expected: the new tests FAIL (functions not found).
- [ ] **Step 3: Implement the three functions** in the psm1 (parse with regex `(?m)^# locked-at: (\S+)\s*$`), add them to the module's export list, and replace the inline arrays in `start-dual-mcp.ps1` with calls. Keep the trailing `python -m workspace_mcp …` arguments in the launcher. The resolution step and the server start both reuse `$platformEnvironmentArgs`.
- [ ] **Step 4: Run Pester.** Expected: all pass (the existing lifecycle tests unchanged).
- [ ] **Step 5: Reverse-verify.** Drop one `--with-editable` from the function → the editable test fails. Restore.
- [ ] **Step 6: Heartbeat.**

### Task 3: Clean-env replay

**Files:**
- Create: `scripts/mcp_locks/assert_lock_replay.py`
- Create: `scripts/test_mcp_lock_replay.ps1`
- Test: `scripts/tests/test_assert_lock_replay.py`

**Interfaces:**
- Consumes: `Get-PlatformUvArguments`, `Get-WorkspaceUvArguments` (Task 2). Lock format (Task 1).
- Produces:
  - `assert_lock_replay.py`: `expected_from_lock(text: str, environment: dict[str, str]) -> dict[str, str]` (markers evaluated with `packaging.markers.Marker`), `installed(skip_editable: bool = True) -> dict[str, str]` (via `importlib.metadata`; editable = `direct_url.json` `dir_info.editable`), and `compare(expected, actual) -> list[str]` (messages `missing <name>==<v>`, `unexpected <name>==<v>`, `version <name>: lock <a> installed <b>`). The CLI `python assert_lock_replay.py <lock>` exits 1 and prints the messages.
  - `test_mcp_lock_replay.ps1 [-WorkspaceRoot <string>]`: sets `UV_CACHE_DIR` to a fresh temp dir, runs each env's args + `python <abs asserter> <abs lock>`, throws `"<env> replay diverged from its lock."` on nonzero, deletes the cache dir in `finally`.

- [ ] **Step 1: Write failing tests** `scripts/tests/test_assert_lock_replay.py`:
  - `test_expected_honors_markers`: lock lines `colorama==0.4.6 ; sys_platform == 'win32'` and `uvloop==0.21.0 ; sys_platform != 'win32'` with env `{"sys_platform": "linux", …default_environment()}` → `{"uvloop": "0.21.0"}`.
  - `test_compare_reports_missing_unexpected_and_version`: expected `{a:1,b:2}`, actual `{b:3,c:1}` → exactly the three messages.
  - `test_compare_clean`: equal dicts → `[]`.
- [ ] **Step 2: Run** `$PY -m pytest scripts/tests/test_assert_lock_replay.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `assert_lock_replay.py`, reusing the pin-line parsing rule from Task 1 (duplicate it locally: the asserter runs inside the bare env, where `scripts/` is not importable), and the replay `.ps1`.
- [ ] **Step 4: Run the pytest.** Expected: PASS. Reverse-verify `compare` (return `[]`) → the version test fails. Restore.
- [ ] **Step 5: Live replay** `pwsh -NoProfile -File scripts/test_mcp_lock_replay.ps1`. Expected: both envs print OK, exit 0. Set a `ScheduleWakeup 540` heartbeat first (cold-cache install).
- [ ] **Step 6: Heartbeat.**

### Task 4: CI workflow and operator docs

**Files:**
- Create: `.github/workflows/dual-mcp-lock.yml`
- Modify: `docs/operations/portfolio-mcp.md` (new "Dependency locks" section)
- Test: `scripts/tests/test_dual_mcp_lock_workflow.py`

**Interfaces:**
- Consumes: `lock_mcp_envs.py --check/--upgrade` (Task 1), `test_mcp_lock_replay.ps1` (Task 3), `Start-DualMcp.Tests.ps1` (Task 2).

- [ ] **Step 1: Write failing tests** `test_dual_mcp_lock_workflow.py` (text assertions on the YAML, same style as `test_general_linting_workflow.py`):
  - `test_check_job_runs_lock_check`: contains `python scripts/lock_mcp_envs.py --check`.
  - `test_replay_job_runs_on_windows_with_pinned_pester`: contains `windows-latest`, `RequiredVersion 4.10.1`, `Start-DualMcp.Tests.ps1`, `test_mcp_lock_replay.ps1`, and `submodules:`.
  - `test_refresh_is_report_only`: contains `schedule:` and `workflow_dispatch:` and `--upgrade`. Contains none of `git push`, `gh pr create`, `contents: write`.
  - `test_triggers_cover_lock_inputs`: `paths:` includes `scripts/mcp_locks/**`, `scripts/lock_mcp_envs.py`, `scripts/start-dual-mcp.ps1`, `scripts/mcp_stack_lifecycle.psm1`, and `openbb_platform/extensions/mcp_server/**`.
- [ ] **Step 2: Run them.** Expected: FAIL (file missing).
- [ ] **Step 3: Write the workflow.** Jobs `lock-check` (ubuntu, setup-uv, setup-python 3.13), `replay` (windows-latest, `actions/checkout@v6` with `submodules: true`, setup-uv, `Install-Module Pester -RequiredVersion 4.10.1 -Force -SkipPublisherCheck`, Pester, replay), and `refresh-report` (`if: github.event_name != 'pull_request'`, runs `--upgrade`, writes `git diff -- scripts/mcp_locks` to `$GITHUB_STEP_SUMMARY`, uploads the locks as an artifact). `permissions: contents: read`. Follow the existing workflow's action versions (`actions/checkout@v6`, `actions/setup-python@v6`).
- [ ] **Step 4: Write the docs section**: what is locked, `lock_mcp_envs.py` modes, why not `UV_CONSTRAINT`, the FastMCP split, and the `--exclude-newer` failure meaning ("re-run `python scripts/lock_mcp_envs.py`"). Repo-relative paths only.
- [ ] **Step 5: Run** all new pytests + Pester. Expected: PASS.
- [ ] **Step 6: Heartbeat.** Hand off to Phase 5 (simplify/diagnostics) → Phase 6 `/verify` (real `start-dual-mcp.ps1` Start → Status → Stop against the locks).
