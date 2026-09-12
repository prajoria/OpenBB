# PI Configuration and Editable Packaging Design

**Issues:** #1972 (centralized typed `PI_*` configuration) and #1973
(editable `openbb-techtrade` install clobbering)

## Gap analysis

The accepted snapshot-alignment design already establishes
`openbb_techtrade` as the lower-layer owner of shared `PI_*` configuration,
but no `openbb_techtrade/config.py` exists. The paper engine, order sink, and
snapshot-store selector still parse their environment variables independently.
Their defaults and normalization rules overlap, while their validation behavior
can drift.

`openbb-portfolio-intel` correctly declares its sibling runtime dependency as a
Poetry path dependency with `develop = true`. Pip does not preserve that
Poetry-only editable flag when resolving the dependency of
`pip install -e openbb_platform/extensions/portfolio_intel`, so it replaces an
editable `openbb-techtrade` installation with a regular direct-URL install.
Documentation currently asks developers to repair the environment manually
afterward; there is no executable invariant or verification.

## Considered approaches

### 1. Central getters plus a guarded installer (recommended)

Add pure, typed configuration getters in `openbb_techtrade.config`, migrate only
the selectors named by #1972, and add a small installer that installs
portfolio-intel and then restores techtrade as an explicit editable requirement.
The installer verifies both distributions' `direct_url.json` metadata before
returning success.

This preserves the runtime dependency contract, makes the supported developer
workflow deterministic, and is independently testable. It cannot change pip's
behavior for an arbitrary raw command, so documentation must make the guarded
installer the canonical command.

### 2. Move techtrade into a Poetry development group

Pip would stop resolving techtrade through portfolio-intel, but production
installs could then omit a package imported at runtime. This reintroduces the
undeclared-runtime-dependency defect fixed by #1971 and is rejected.

### 3. Customize package metadata or the Poetry build backend

A custom backend could attempt to communicate editable dependency intent to
pip, but editable transitive dependencies are not part of standard wheel
metadata. The approach would be fragile, surprising, and much larger than the
developer-workflow problem. It is rejected.

## Architecture

### Typed configuration boundary

`openbb_techtrade.config` exposes six side-effect-free functions:

- `paper_engine(default="mysql")`
- `paper_db_path(default=None)`
- `order_sink(default="paper")`
- `order_sink_paper_dir(default=None)`
- `snapshot_engine(default="mysql")`
- `snapshot_db_path(default=None)`

Engine getters normalize with `strip().lower()`, return literals, and reject
unsupported values with an error that names the environment variable. Path
getters preserve the existing empty-value fallback and return `Path` objects.
Each function reads the environment at call time so tests and long-running
processes can change configuration without reloading a module.

Only the paper-engine, order-sink, and snapshot-store selector seams migrate in
this cycle. Explicit function arguments retain precedence over environment
values. Existing path creation, normalization, MySQL fallback, logging, and
PII-boundary behavior remain in their current owners.

### Editable-install guard

`scripts/pi_install.py` runs under the invoking interpreter and performs two
ordered pip operations:

1. install portfolio-intel editable with normal dependency resolution;
2. install techtrade editable explicitly, making the final resolver state
   deterministic.

It then reads installed distribution metadata and fails unless both packages
have `dir_info.editable == true`. Paths are derived from the repository root;
no machine-specific paths are embedded. A `--dry-run` mode exposes the exact
commands without mutating an environment.

The repository setup instructions use this helper rather than a raw
portfolio-intel editable install. The Poetry runtime dependency remains intact.

## Error handling

Invalid enumerated configuration values fail before a backend is selected.
Path values are not over-validated because previously accepted relative,
absolute, and tilde-containing paths must remain valid. Pip subprocess failures
propagate as non-zero exits. Missing or malformed editable metadata produces a
clear package-specific error after installation.

## Testing and verification

- Unit-test every getter for unset and overridden environment values.
- Unit-test invalid values for the enumerated getters and default parameters.
- Preserve and run existing paper-engine, order-sink, and snapshot-selector
  tests unchanged.
- Unit-test installer command order, dry-run behavior, metadata validation, and
  failure reporting without invoking pip.
- Harness-verify getters in a real interpreter and run the installer against
  an isolated project venv, then assert both distributions report editable
  metadata.
- Run Black and Ruff on touched Python files.

## Scope boundaries

This cycle does not alter execution semantics, FMP database code, widget/viewer
code, risk calculations, snapshot consumers, or the snapshot path safety guard.
It changes only configuration acquisition at existing selector seams and the
developer installation workflow.
