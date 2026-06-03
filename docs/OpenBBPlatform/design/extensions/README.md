# extensions/ — Design

[← design/](../README.md) · Architecture counterpart: [extensions/ architecture](../../architecture/extensions/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The *why* and *how-to-add* for command-namespace plugins in
> `openbb_platform/extensions/`. Last verified: 2026-06-02.

---

## Two flavors of extension

| Flavor | Command shape | Provider? | Method | Example |
|---|---|---|---|---|
| **Data router** | 4-param `(cc, provider_choices, standard_params, extra_params)` | yes (injected) | GET | `equity`, `crypto`, `economy` |
| **Toolkit** | `data: list[Data]` + scalars | no | POST | `technical`, `quantitative`, `econometrics` |

This split is deliberate: data routers fetch from vendors; toolkits compute on already-fetched
data so results stay composable. → [ADR-9](../01-decisions.md#adr-9--toolkits-are-data-in-commands-not-providers) · [Toolkit vs Data Routers](../../architecture/extensions/toolkit-vs-data-routers.md)

## Design rules

1. A data-router command **must** use the exact 4-param signature and body
   `return await OBBject.from_query(Query(**locals()))`. → [Conventions § signatures](../02-conventions.md#command-signatures)
2. `model=` must name a real standard model, or the command silently vanishes. → [Gotchas G1](../04-gotchas.md#g1-a-command-silently-disappears)
3. A toolkit command must **not** take the provider signature; newcomers often copy the wrong
   shape. → [ADR-9](../01-decisions.md#adr-9--toolkits-are-data-in-commands-not-providers)
4. The router object is named `router` at module top-level; entry point under
   `openbb_core_extension`. → [Conventions § extension package](../02-conventions.md#extension-package)
5. Attach `examples=[APIEx(...), PythonEx(...)]` — they feed docstrings and OpenAPI.

## Add an extension / command

→ [Recipes C (toolkit)](../03-recipes.md#recipe-c--add-a-toolkit-data-in-command) ·
[Recipes D (extension)](../03-recipes.md#recipe-d--add-a-new-extension-command-namespace) ·
[Recipes B (new model + command)](../03-recipes.md#recipe-b--add-a-brand-new-standard-model--command)

## Catalog

The full list of 24 extensions lives in the architecture index.
→ [extensions/ architecture](../../architecture/extensions/README.md)

→ Related design: [02 Conventions](../02-conventions.md) · [03 Recipes](../03-recipes.md) · [04 Gotchas](../04-gotchas.md)
→ Upstream: `third_party/openbb-docs/content/odp/python/developer/extension_types/router.md`, `extensions/data-processing/{technical,quantitative,econometrics}.mdx`
