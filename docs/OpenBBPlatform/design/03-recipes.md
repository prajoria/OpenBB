# 03 — Recipes

[← design/](./README.md) · Prev: [02 Conventions](./02-conventions.md) · Next: [04 Gotchas →](./04-gotchas.md)

> Copy-paste-shaped, code-anchored procedures for the four things you'll add most.
> Each recipe ends with the **rebuild + verify** step that catches the silent failures.
> Last verified: 2026-06-02.

---

## Recipe A — Add a provider integration for an existing standard model

**Goal:** make `SomeProvider` implement `EquityHistorical`.

1. **Scaffold the package** (`providers/<name>/openbb_<name>/`) per [Conventions § provider package](./02-conventions.md#provider-package).

2. **Write the model file** `models/equity_historical.py` with three subclasses:

   ```python
   class SomeQueryParams(EquityHistoricalQueryParams):
       """SomeProvider Equity Historical query."""
       # provider-only knobs here, typed Optional, with descriptions

   class SomeData(EquityHistoricalData):
       """SomeProvider Equity Historical data."""
       __alias_dict__ = {"close": "c", "volume": "v"}  # vendor → our field (inbound)

   class SomeEquityHistoricalFetcher(
       Fetcher[SomeQueryParams, list[SomeData]]
   ):
       @staticmethod
       def transform_query(params: dict) -> SomeQueryParams:
           return SomeQueryParams(**params)

       @staticmethod
       async def aextract_data(query, credentials, **kwargs) -> list[dict]:
           # lazy import + raw I/O ONLY — never build Data here
           ...

       @staticmethod
       def transform_data(query, data, **kwargs) -> list[SomeData]:
           return [SomeData.model_validate(d) for d in data]
   ```

   - Implement **exactly one** of `extract_data` / `aextract_data`. → [ADR-4](./01-decisions.md#adr-4--fetcher-implements-either-sync-or-async-extract-never-forced)
   - Set `require_credentials = False` on the Fetcher for free sources.

3. **Register** in `openbb_<name>/__init__.py`:

   ```python
   some_provider = Provider(
       name="some",
       website="https://...",
       fetcher_dict={"EquityHistorical": SomeEquityHistoricalFetcher},
   )
   ```

   Credentials auto-prefix: declaring `credentials=["api_key"]` yields `some_api_key`.

4. **Add the entry point** in `pyproject.toml`:

   ```toml
   [tool.poetry.plugins."openbb_provider_extension"]
   some = "openbb_some:some_provider"
   ```

5. **Install + rebuild + verify**:

   ```bash
   cd openbb_platform && python dev_install.py -e
   python -c "import openbb; openbb.build()"
   python -c "from openbb import obb; print('some' in obb.equity.price.historical.__doc__)"
   ```

   If `some` doesn't appear: re-import with `OPENBB_DEBUG_MODE=1` to surface a swallowed
   load error. → [Gotchas G5](./04-gotchas.md#g5-load-failures-are-swallowed)

→ [Provider Framework](../architecture/core/provider-framework.md) · Test it: [05 § fetcher tests](./05-quality-and-testing.md)

---

## Recipe B — Add a brand-new standard model + command

**Goal:** a new command `obb.equity.foo.bar(...)` backed by providers.

1. **Define the standard model** in `core/openbb_core/provider/standard_models/foo_bar.py`:
   `FooBarQueryParams(QueryParams)` + `FooBarData(Data)`, fields typed & described, only
   **shared** fields. (This is a **core PR**. → [ADR-3](./01-decisions.md#adr-3--standard-models-owned-by-core-providers-subclass))

2. **Add the command** in the owning extension router with the **exact 4-param shape**:

   ```python
   @router.command(model="FooBar")
   async def bar(cc, provider_choices, standard_params, extra_params) -> OBBject:
       """..."""
       return await OBBject.from_query(Query(**locals()))
   ```

3. **Implement at least one provider** (Recipe A) — otherwise the command **won't exist**
   (no provider → nothing to inject → `SignatureInspector` drops it). → [Gotchas G1](./04-gotchas.md#g1-a-command-silently-disappears)

4. **Rebuild + verify** as in Recipe A step 5.

→ [Conventions § signatures](./02-conventions.md#command-signatures)

---

## Recipe C — Add a toolkit (data-in) command

1. In a toolkit extension (e.g. `technical`), add a **POST** command that takes
   `data: list[Data]` + scalars, **no** `model=`:

   ```python
   @router.command(methods=["POST"])
   async def foo(data: list[Data], length: int = 14) -> OBBject[list[Data]]:
       """..."""
       df = basemodel_to_df(data)
       ...
       return OBBject(results=df_to_basemodel(out))
   ```

2. Rebuild + verify; compose-test it: `obb.equity.price.historical(...).to_df()` →
   feed into your command.

→ [ADR-9](./01-decisions.md#adr-9--toolkits-are-data-in-commands-not-providers) · [Toolkit vs Data Routers](../architecture/extensions/toolkit-vs-data-routers.md)

---

## Recipe D — Add a new extension (command namespace)

1. Scaffold `extensions/<name>/openbb_<name>/<name>_router.py` with a module-level
   `router = Router(prefix="")`; add commands.
2. Entry point under `[tool.poetry.plugins."openbb_core_extension"]`: `<name> = "openbb_<name>:router"`.
3. `python dev_install.py -e` → `openbb.build()` → confirm `obb.<name>` exists.

→ [extensions/ design](./extensions/README.md)

---

## The universal closing step

After **any** structural change:

```bash
python -c "import openbb; openbb.build()"   # regenerate the SDK surface
```

Never commit the regenerated `core/openbb/package/*` (except `__init__.py`).
→ [ADR-1](./01-decisions.md#adr-1--generate-the-sdk-instead-of-writing-it) · [Gotchas](./04-gotchas.md)

---

→ Next: [04 — Gotchas](./04-gotchas.md) for the silent failures these recipes can trip.
