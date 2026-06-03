# OpenBB Platform — Design Documentation

[← Memory Bank Index](../INDEX.md) · Sister tree: [architecture/](../architecture/README.md) · [GLOSSARY](../GLOSSARY.md)

> **Purpose:** the *why* and *how-to-change* of the OpenBB Platform — design principles,
> the key decisions and their trade-offs, the conventions you must follow, step-by-step
> recipes, and the gotchas that cause silent failures. For *what exists and how it flows*,
> see the sister [architecture/](../architecture/README.md) tree.
>
> **Last verified against code:** 2026-06-02.

This tree mirrors the source layout (`core/`, `providers/`, `extensions/`,
`obbject_extensions/`) symmetrically with the architecture tree.

> **Complementary upstream docs.** The official OpenBB developer guides live in the vendored
> submodule `third_party/openbb-docs/content/odp/python/developer/` (published at
> [docs.openbb.co](https://docs.openbb.co/platform/developer)). Where this tree gives
> fork-specific *why/how-to-change*, the upstream `how-to/` and `extension_types/` guides
> give the canonical public-API version. Map: [INDEX upstream section](../INDEX.md#third-tree--upstream-docs-as-a-complementary-memory-bank).

---

## Read order for a new agent

```mermaid
flowchart LR
    P["00 Principles<br/>(the core ideas)"] --> D["01 Decisions<br/>(trade-offs)"]
    D --> C["02 Conventions<br/>(rules to follow)"]
    C --> R["03 Recipes<br/>(how to add things)"]
    R --> G["04 Gotchas<br/>(what bites you)"]
    G --> A["per-area design pages"]
```

---

## Cross-cutting design docs

| Doc | Read it when you need to… |
|---|---|
| [00 — Principles](./00-principles.md) | understand the 6 ideas that explain every design choice |
| [01 — Decisions (ADR-style)](./01-decisions.md) | know *why* a trade-off was made before challenging it |
| [02 — Conventions](./02-conventions.md) | follow naming, structure, and signature rules exactly |
| [03 — Recipes](./03-recipes.md) | add a provider / command / standard model / extension |
| [04 — Gotchas](./04-gotchas.md) | avoid silent failures, stale caches, swallowed errors |
| [05 — Quality & Testing](./05-quality-and-testing.md) | pass pre-commit, write VCR tests, run integration tests |

## Per-area design pages (symmetric with architecture/)

| Area | Design page | Architecture counterpart |
|---|---|---|
| `core/` | [core/ design](./core/README.md) | [core/ architecture](../architecture/core/README.md) |
| `providers/` | [providers/ design](./providers/README.md) | [providers/ architecture](../architecture/providers/README.md) |
| `extensions/` | [extensions/ design](./extensions/README.md) | [extensions/ architecture](../architecture/extensions/README.md) |
| `obbject_extensions/` | [obbject_extensions/ design](./obbject_extensions/README.md) | [obbject_extensions/ architecture](../architecture/obbject_extensions/README.md) |

---

## The design thesis in one paragraph

OpenBB optimizes for **"connect once, consume everywhere."** The whole architecture
falls out of one decision: program against **vendor-neutral standard models**, and let
**providers** subclass them. Everything else — the `Fetcher` TET pipeline, the
`ProviderInterface` aggregation, the entry-point plugin system, the generated SDK, the
shared FastAPI surface — exists to make that standardization automatic, type-safe, and
extensible without touching core. The cost is **indirection and generated code**: you
edit a provider, then rebuild the SDK; you add a command, but it silently vanishes if no
provider implements its model. Knowing those trade-offs (captured here) is what lets you
work fast without surprises.

→ Start with [00 — Principles](./00-principles.md).
