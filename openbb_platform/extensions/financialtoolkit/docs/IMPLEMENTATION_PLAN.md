# OpenBB FinancialToolkit Extension: Detailed Design & Systematic Implementation Plan

## 1) Goal and Scope

Build a first-class OpenBB extension under `openbb_platform/extensions/financialtoolkit` that wraps FinanceToolkit capabilities in OpenBB-native commands, data models, and response patterns.

This extension should:
- Follow OpenBB extension architecture, packaging, routing, and testing standards.
- Expose FinanceToolkit functionality as OpenBB commands (Python + API compatible patterns).
- Keep FinanceToolkit as the computation backend (wrapper/adaptor design), not duplicate formulas.
- Assume FinanceToolkit is available as a PyPI dependency (`financetoolkit ^2.1.2`).

Out of scope for initial implementation:
- Re-implementing provider fetchers inside this extension.
- Rewriting FinanceToolkit internals.
- One-shot parity with all FinanceToolkit methods.

---

## 2) Correct Placement in OpenBB Architecture

### Where this belongs
- **Extension layer** (`openbb_platform/extensions/financialtoolkit`) is the correct place.
- Why: FinanceToolkit mostly provides analytics/modeling workflows. In OpenBB, analytics should live in extension routers and models.

### Where this does *not* belong
- **Provider layer** should only be used for source-specific data ingestion connectors.
- If FinanceToolkit internally fetches data using its own mechanisms, this extension still remains an extension-level wrapper, with optional adapter utilities for credentials and data handoff.

### High-level architecture
- OpenBB command -> `financialtoolkit` router -> adapter/service -> FinanceToolkit controller/model -> normalize to OpenBB `OBBject` + Pydantic response model.

---

## 3) Proposed Extension Structure

Create the following structure:

```text
openbb_platform/extensions/financialtoolkit/
  pyproject.toml
  README.md
  openbb_financialtoolkit/
    __init__.py
    financialtoolkit_router.py
    settings.py
    exceptions.py

    adapters/
      __init__.py
      toolkit_factory.py
      mapper.py

    common/
      __init__.py
      enums.py
      validators.py
      transform.py

    models/
      __init__.py
      models_router.py
      models_models.py
      models_service.py

    options/
      __init__.py
      options_router.py
      options_models.py
      options_service.py

    risk/
      __init__.py
      risk_router.py
      risk_models.py
      risk_service.py

    performance/
      __init__.py
      performance_router.py
      performance_models.py
      performance_service.py

    discovery/
      __init__.py
      discovery_router.py
      discovery_models.py
      discovery_service.py

  integration/
    test_financialtoolkit_api.py
    test_financialtoolkit_python.py

  tests/
    test_mapper.py
    test_validators.py
    test_services.py

  docs/
    IMPLEMENTATION_PLAN.md
    COMMAND_COVERAGE_MATRIX.md
```

Design notes:
- Keep one top-level router (`financialtoolkit_router.py`) and include sub-routers per domain.
- Keep wrappers in `*_service.py`; routers stay thin.
- Keep transformation and schema-normalization centralized in `common/transform.py` + `adapters/mapper.py`.

---

## 4) Packaging and Plugin Registration

Use existing extension conventions (`technical`, `quantitative`, etc.) as template.

### `pyproject.toml` design
- Package name: `openbb-financialtoolkit`
- Python: aligned with platform (`>=3.10,<3.14`)
- Dependencies:
  - `openbb-core` (aligned platform version)
  - `financetoolkit` from PyPI (`^2.1.2`)

> **Historical note (#19):** an earlier iteration used a local path
> dependency on a `FinanceToolkit` git submodule (`prajoria/FinanceToolkit`
> fork). That coupling was removed so the extension is PyPI-installable.

Current dependency strategy:

```toml
[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-core = "^1.5.8"
financetoolkit = "^2.1.2"
```

Plugin registration:

```toml
[tool.poetry.plugins."openbb_core_extension"]
financialtoolkit = "openbb_financialtoolkit.financialtoolkit_router:router"
```

---

## 5) Command Namespace and Domain Mapping

Expose under:
- `obb.financialtoolkit.models.*`
- `obb.financialtoolkit.options.*`
- `obb.financialtoolkit.risk.*`
- `obb.financialtoolkit.performance.*`
- `obb.financialtoolkit.discovery.*`

### Initial priority commands (Phase 1 + 2)

#### A) Models
- `altman_z_score`
- `piotroski_score`
- `dupont`
- `extended_dupont`
- `wacc`
- `intrinsic_value`

#### B) Options
- `greeks` (base + advanced/higher-order where available)
- Optional split endpoints for grouped Greeks if response size is too large.

#### C) Risk
- `var`
- `cvar`
- `evar`
- `garch`

#### D) Performance
- Risk-adjusted performance wrappers where FinanceToolkit provides richer variants.

#### E) Discovery
- Lightweight discovery/screener methods that are stable and low-friction.

---

## 6) Router and Service Contract Design

### Router responsibilities
- Define command metadata (`@router.command`, `PythonEx`, `APIEx`).
- Validate user parameters (types/defaults/min constraints).
- Delegate to service layer.
- Return `OBBject[ResultModel | list[Data]]`.

### Service responsibilities
- Instantiate/obtain FinanceToolkit context through factory.
- Call FinanceToolkit methods.
- Normalize outputs to OpenBB-compatible schemas.
- Handle FinanceToolkit exceptions and map to OpenBB-friendly messages.

### Adapter responsibilities (`adapters/toolkit_factory.py`)
- Build FinanceToolkit Toolkit/controller instance from input:
  - symbol(s)
  - date range
  - frequency/period
  - optional API key/env passthrough
- Ensure deterministic creation flow used by all domains.

---

## 7) Data Models and Output Standardization

Create Pydantic models per domain in `*_models.py`.

Principles:
- Prefer explicit typed fields for stable scalar outputs.
- For matrix/table outputs, normalize to list-of-records where possible.
- Preserve traceability fields:
  - `symbol`
  - `date` (when applicable)
  - `period` / `window` / `frequency`
  - method metadata (`model_name`, `assumptions`) when useful.

Normalization rules:
- Convert pandas DataFrame -> list of dict rows (or dedicated Data models).
- Convert index to `date`/`period` field (never hidden index in final API response).
- Use consistent numeric precision handling without aggressive rounding.

---

## 8) Settings, Credentials, and Runtime Behavior

Implement `settings.py` for extension-level runtime parameters.

Required settings:
- `default_provider` (optional; used only when bridging with OpenBB datasets)
- `financialtoolkit_mode` (e.g., strict/compat)
- `allow_internal_fetch` (bool; whether Toolkit can fetch directly)
- `api_key_env_var` mapping hints (if needed)

Credential strategy:
- Respect existing OpenBB credential patterns.
- Do not hardcode secrets.
- Read from env/config and pass through to FinanceToolkit factory when required.

---

## 9) Error Handling and Observability

Create `exceptions.py` with mapped exception classes:
- `FinancialToolkitConfigurationError`
- `FinancialToolkitDataError`
- `FinancialToolkitExecutionError`

Guidelines:
- Map low-level exceptions to clear user-facing messages.
- Include actionable remediation text (missing symbol, invalid date window, unsupported method params).
- Keep stack details internal unless debug mode is enabled.

---

## 10) Testing Strategy (OpenBB-standard)

### Unit tests (`tests/`)
- `test_mapper.py`: conversion correctness for DataFrame/Series outputs.
- `test_validators.py`: parameter and input validation.
- `test_services.py`: service behavior with mocked FinanceToolkit methods.

### Integration tests (`integration/`)
- `test_financialtoolkit_python.py`: Python interface command behavior.
- `test_financialtoolkit_api.py`: API endpoint behavior and schema shape.

Testing principles:
- Start with deterministic fixtures and mocked toolkit outputs.
- Add optional real-integration tests gated behind marker/env flag.
- Avoid brittle tests tied to remote live data in core CI path.

---

## 11) Coding Standards and Build Compliance

Must align with repo standards:
- Type hints everywhere.
- Pydantic models for responses.
- Thin routers; logic in services.
- Lint/format/type-check compatibility with project config (`ruff`, `pyright`).
- Keep extension self-contained and modular.

Definition of done for each command:
- Command added to router with examples.
- Service wrapper implemented.
- Model schema defined.
- Unit + integration tests added.
- README snippet/documentation updated.

---

## 12) Phased Implementation Roadmap

### Phase 0: Scaffolding (1 PR)
1. Add `pyproject.toml`, package skeleton, top-level router.
2. Register plugin entrypoint.
3. Add minimal smoke command (`health` or `version`).
4. Add baseline tests and CI wiring.

### Phase 1: Core Models (1–2 PRs)
1. Implement `models_router.py` + `models_service.py`.
2. Add: `altman_z_score`, `piotroski_score`, `dupont`, `wacc`, `intrinsic_value`.
3. Add schemas and tests.

### Phase 2: Options + Risk (2 PRs)
1. Implement `options_router.py` advanced Greeks wrapper.
2. Implement `risk_router.py` with `var`, `cvar`, `evar`, `garch`.
3. Ensure robust shape normalization and parameter validation.

### Phase 3: Performance + Discovery (1–2 PRs)
1. Add stable high-value endpoints from FinanceToolkit performance/discovery domains.
2. Add coverage matrix updates and docs.

### Phase 4: Hardening and Parity Expansion (ongoing)
1. Expand command coverage incrementally.
2. Add benchmark tests and reliability checks.
3. Improve caching and optional parallel execution where safe.

---

## 13) Capability-to-OpenBB Surface Mapping (Initial)

| FinanceToolkit Capability | OpenBB Namespace | Implementation Type | Priority |
|---|---|---|---|
| Altman Z Score | `financialtoolkit.models.altman_z_score` | Wrapper service + typed model | P1 |
| Piotroski | `financialtoolkit.models.piotroski_score` | Wrapper service + typed model | P1 |
| Dupont | `financialtoolkit.models.dupont` | Wrapper service + table normalization | P1 |
| WACC | `financialtoolkit.models.wacc` | Wrapper service + typed model | P1 |
| Intrinsic Value | `financialtoolkit.models.intrinsic_value` | Wrapper service + typed model | P1 |
| Advanced Greeks | `financialtoolkit.options.greeks` | Wrapper service + multi-field schema | P2 |
| VaR/CVaR/EVaR | `financialtoolkit.risk.*` | Wrapper service + percentile/config params | P2 |
| GARCH | `financialtoolkit.risk.garch` | Wrapper service + model output schema | P2 |
| Performance Metrics | `financialtoolkit.performance.*` | Wrapper service + standardized outputs | P3 |
| Discovery/Screener | `financialtoolkit.discovery.*` | Wrapper service + lightweight schemas | P3 |

---

## 14) PR Breakdown Recommendation

- **PR-1**: Extension scaffold + plugin registration + smoke route + docs.
- **PR-2**: Models domain (high-value fundamentals).
- **PR-3**: Options domain (advanced Greeks).
- **PR-4**: Risk domain (VaR/CVaR/EVaR/GARCH).
- **PR-5**: Performance + discovery + final docs.

Each PR should be mergeable independently and include tests.

---

## 15) Risks and Mitigations

1. **Output shape variability from FinanceToolkit**
   - Mitigation: central mapper + contract tests on representative outputs.
2. **Dependency/version drift between OpenBB and FinanceToolkit**
   - Mitigation: pin compatible versions and add startup compatibility check.
3. **Live-data fragility in tests**
   - Mitigation: mocked deterministic tests for CI; optional live marker tests.
4. **Performance for large symbol universes**
   - Mitigation: enforce limits, paging, and optional async batching where safe.

---

## 16) Immediate Next Actions

1. Create scaffolding files listed in Section 3.
2. Implement `financialtoolkit_router.py` with sub-router includes.
3. Build `models` domain first (highest ROI and clear parity gap coverage).
4. Add `COMMAND_COVERAGE_MATRIX.md` and keep it updated each PR.

This plan provides a standards-compliant path to a robust OpenBB-native FinancialToolkit extension while preserving FinanceToolkit as the analytics backend.
