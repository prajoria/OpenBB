# 02 — Conventions

[← design/](./README.md) · Prev: [01 Decisions](./01-decisions.md) · Next: [03 Recipes →](./03-recipes.md)

> The rules below are **enforced or assumed** by the engine, the code generator, or the
> pre-commit gates. Following them is what makes a new provider/command/model "just work."
> Last verified: 2026-06-02.

> **Upstream reference:** standardization rules (lower_snake_case, `__alias_dict__`, null/
> decimal normalization) are documented canonically in
> `third_party/openbb-docs/content/odp/python/developer/standardization.mdx`; validators in
> `developer/how-to/validators.mdx`.

---

## Naming & layout

### Provider package

A provider lives in `providers/<name>/openbb_<name>/` and registers through an entry point.

```
providers/<name>/
├── openbb_<name>/
│   ├── __init__.py              # exposes `<name>_provider = Provider(...)`
│   ├── models/                  # one file per standard model implemented
│   │   └── equity_historical.py #   defines QueryParams + Data + Fetcher subclasses
│   └── utils/                   # shared helpers (lazy-imported)
├── tests/
│   ├── record/                  # VCR cassettes (*.yaml)
│   └── test_<name>_fetchers.py
└── pyproject.toml               # entry point under [tool.poetry.plugins."openbb_provider_extension"]
```

- Package dir `<name>` is the provider's lowercase id; it becomes the credential prefix
  (`<name>_api_key`) and the `Literal` value in `ProviderChoices`.
- Each model file holds the three subclasses for **one** standard model:
  `<Model>QueryParams`, `<Model>Data`, `<Model>Fetcher`.

→ [Provider Framework](../architecture/core/provider-framework.md) · [ADR-8 lazy imports](./01-decisions.md#adr-8--lazy-in-function-imports-in-providers)

### Extension package

```
extensions/<name>/
├── openbb_<name>/
│   ├── __init__.py
│   └── <name>_router.py         # module-level `router = Router(prefix="")`
├── integration/                 # API + Python integration tests
└── pyproject.toml               # entry point under [tool.poetry.plugins."openbb_core_extension"]
```

- The router object **must** be named `router` and be importable at module top-level —
  the entry point points at `openbb_<name>:router` (or the router module).

→ [extensions/ design](./extensions/README.md)

---

## Standard models & provider models

| Rule | Why |
|---|---|
| Standard model = a `QueryParams` subclass **and** a `Data` subclass, same prefix (`EquityHistoricalQueryParams` / `EquityHistoricalData`). | The pair is the command contract. → [P1](./00-principles.md#p1--standardize-the-contract-not-the-source) |
| A field belongs in the **standard** model only if **2+ providers** share it. | Keeps the neutral contract honest. (`CONTRIBUTING.md`) |
| Provider-unique fields are added by **subclassing** in the provider's model, typed `Optional`. | Interchangeability; no core PR needed. → [ADR-3](./01-decisions.md#adr-3--standard-models-owned-by-core-providers-subclass) |
| Field descriptions are required and go in the **standard** model; reuse via `Field(description=QUERY_DESCRIPTIONS.get(...))`. | Docstrings & OpenAPI are generated from them. |
| Use `__alias_dict__` for vendor field-name remaps, not renamed Python attributes. | Keeps the standard attribute name stable for consumers. |

**`__alias_dict__` direction (easy to get backwards):**

- On **`QueryParams`** → applied **outbound** in `model_dump()` (our field name → vendor param name).
- On **`Data`** → applied **inbound** as a validation alias (vendor column → our field name).

→ [GLOSSARY `__alias_dict__`](../GLOSSARY.md) · [Gotchas G3](./04-gotchas.md)

---

## Command signatures

### Model-backed (data router) command — **exact shape required**

```python
@router.command(model="EquityHistorical")
async def historical(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get historical price data."""
    return await OBBject.from_query(Query(**locals()))
```

- The four parameter **names** are matched by `SignatureInspector`; do not rename them.
- The body is always `return await OBBject.from_query(Query(**locals()))`.
- `model=` must name an existing standard model, else the command **silently vanishes**
  (warns only in `DEBUG_MODE`). → [Gotchas G1](./04-gotchas.md#g1-a-command-silently-disappears)

### Toolkit (data-in) command — different shape on purpose

```python
@router.command(methods=["POST"])
async def rsi(
    data: list[Data],
    target: str = "close",
    length: int = 14,
) -> OBBject[list[Data]]:
    """Compute RSI on input data."""
    ...
```

- No `model=`, no provider injection; takes `data: list[Data]` + scalars; `methods=["POST"]`.
- → [ADR-9](./01-decisions.md#adr-9--toolkits-are-data-in-commands-not-providers) · [Toolkit vs Data Routers](../architecture/extensions/toolkit-vs-data-routers.md)

### Examples & metadata

- Attach runnable examples with `examples=[APIEx(...), PythonEx(...)]` in the decorator —
  they render in both the docstring and OpenAPI. → [GLOSSARY APIEx/PythonEx](../GLOSSARY.md)

---

## Model config conventions (don't override blindly)

| Base | Config | Consequence |
|---|---|---|
| `QueryParams` | `extra="allow"`, `populate_by_name=True` | Unknown params **warn & drop**; aliases work both ways. |
| `Data` | `extra="allow"` + camelCase-in/snake_case-out `AliasGenerator` | Vendor camelCase validates in; output is snake_case. |
| `Fetcher` | `require_credentials=True` (default) | Set `False` for free sources to skip the cred check. |

→ [ADR-5 extra=allow](./01-decisions.md#adr-5--extraallow-on-queryparams-and-data) · [Models & Settings](../architecture/core/models-and-settings.md)

---

## Style rules enforced by gates

- **Lazy imports**: import heavy deps **inside** fetcher methods (`PLC0415` is globally
  ignored to allow this). → [ADR-8](./01-decisions.md#adr-8--lazy-in-function-imports-in-providers)
- **Line length 122**; Black formats; Ruff rule sets `E/W/F/Q/S/UP/I/PLC/PLE/PLR/PLW/SIM/T20`.
- **Docstrings**: numpy convention (pydocstyle); every command and model field documented.
- **No `print`** (`T20`); use warnings/loggers.
- Never commit `core/openbb/package/*` except `__init__.py` (pre-commit hard-fails).

→ Full gate details: [05 — Quality & Testing](./05-quality-and-testing.md)

---

→ Next: [03 — Recipes](./03-recipes.md) for step-by-step "add a thing."
