# core/ — Design

[← design/](../README.md) · Architecture counterpart: [core/ architecture](../../architecture/core/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The *why* behind the engine in `openbb_platform/core/openbb_core/`. For *what exists and
> how it flows*, read the [architecture core docs](../../architecture/core/README.md).
> Last verified: 2026-06-02.

---

## What the core owns

The core is the only thing that must be present for the platform to run. It owns:

- the **router system** and the **single tree** both surfaces are built from ([ADR-2](../01-decisions.md#adr-2--one-router-tree-feeds-both-the-sdk-and-the-rest-api)),
- the **code generator** (`PackageBuilder`) that writes the SDK ([ADR-1](../01-decisions.md#adr-1--generate-the-sdk-instead-of-writing-it)),
- the **provider framework** (`Fetcher`/`QueryParams`/`Data`/`Provider`) and TET contract ([P4](../00-principles.md#p4--the-fetcher-is-a-fixed-three-step-pipeline-tet)),
- the **standard models** — the vendor-neutral contracts ([ADR-3](../01-decisions.md#adr-3--standard-models-owned-by-core-providers-subclass)),
- the **ProviderInterface** aggregation that synthesizes the typed surface ([P5](../00-principles.md#p5--generate-the-typed-surface-from-provider-metadata)),
- **settings, credentials, OBBject**, and the **FastAPI** assembly.

## Design rules specific to core

| Rule | Decision |
|---|---|
| Standard models are core-owned; adding a shared field is a core PR. | [ADR-3](../01-decisions.md#adr-3--standard-models-owned-by-core-providers-subclass) |
| The router tree is assembled once (`RouterLoader.from_extensions`, lru_cache) and reused. | [P2](../00-principles.md#p2--two-surfaces-one-engine) |
| Credentials validated late, stored as `SecretStr`. | [ADR-6](../01-decisions.md#adr-6--late-credential-validation-with-secretstr) |
| Plugin load failures tolerated unless `DEBUG_MODE`. | [ADR-7](../01-decisions.md#adr-7--tolerate-plugin-load-failures-except-in-debug_mode) |
| Permissive edges (`extra="allow"`), strict middle (typed standard fields, enforced Fetcher contract). | [P6](../00-principles.md#p6--be-permissive-at-the-edges-strict-in-the-middle) |

## When you change core

- Editing a **standard model** → rebuild the SDK and expect provider subclasses to inherit
  the change. → [Recipes B](../03-recipes.md#recipe-b--add-a-brand-new-standard-model--command)
- Editing the **Fetcher base / runner** → you affect every provider; run the full provider
  test tier. → [05 Quality & Testing](../05-quality-and-testing.md)
- Never commit generated `openbb/package/*`. → [Gotchas G2](../04-gotchas.md#g2--stale-generated-sdk-after-a-change)

## Architecture deep-dives

| Topic | Architecture doc |
|---|---|
| Static build, Container, CommandRunner, Router, ProviderInterface | [App Runtime](../../architecture/core/app-runtime.md) |
| Fetcher / QueryParams / Data / Provider / standard models | [Provider Framework](../../architecture/core/provider-framework.md) |
| OBBject, credentials, settings, Env | [Models & Settings](../../architecture/core/models-and-settings.md) |
| FastAPI assembly, REST↔Python sharing | [API Server](../../architecture/core/api-server.md) |

→ Related design: [02 Conventions](../02-conventions.md) · [03 Recipes](../03-recipes.md) · [04 Gotchas](../04-gotchas.md)
