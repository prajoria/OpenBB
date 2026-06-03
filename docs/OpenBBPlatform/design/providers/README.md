# providers/ — Design

[← design/](../README.md) · Architecture counterpart: [providers/ architecture](../../architecture/providers/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The *why* and *how-to-add* for data-source integrations in `openbb_platform/providers/`.
> For the catalog of all 34 providers and the fmp_cached deep dive, see the
> [architecture providers docs](../../architecture/providers/README.md). Last verified: 2026-06-02.

---

## What a provider is (and isn't)

A provider is an **independently installable plugin** that maps standard-model names to
`Fetcher`s. It is **not** allowed to redefine the contract — it subclasses the core standard
models and adds vendor specifics. ([P1](../00-principles.md#p1--standardize-the-contract-not-the-source), [ADR-3](../01-decisions.md#adr-3--standard-models-owned-by-core-providers-subclass))

## The five design rules for providers

1. **Subclass, don't redefine.** Implement a standard model by subclassing its
   `QueryParams` + `Data`; add only provider-unique `Optional` fields. → [Conventions](../02-conventions.md#standard-models--provider-models)
2. **One extract style.** Implement either `extract_data` or `aextract_data`, never both;
   prefer async for HTTP. → [ADR-4](../01-decisions.md#adr-4--fetcher-implements-either-sync-or-async-extract-never-forced)
3. **Extract returns raw I/O.** Build `Data` only in `transform_data`. → [Gotchas G6](../04-gotchas.md#g6--returning-data-from-extract_data)
4. **Lazy imports.** Import heavy deps inside fetcher methods. → [ADR-8](../01-decisions.md#adr-8--lazy-in-function-imports-in-providers)
5. **Credentials auto-prefix.** Declared creds become `<name>_<cred>`; set
   `require_credentials=False` for free sources. → [ADR-6](../01-decisions.md#adr-6--late-credential-validation-with-secretstr)

## Add a provider

→ Full procedure: [Recipes A](../03-recipes.md#recipe-a--add-a-provider-integration-for-an-existing-standard-model).
Verify it appears with `OPENBB_DEBUG_MODE=1` if it's missing ([Gotchas G5](../04-gotchas.md#g5-load-failures-are-swallowed)).

## Test a provider

VCR cassettes + `Fetcher.test()`; **always sanitize the API key** out of recordings.
→ [05 § fetcher tests](../05-quality-and-testing.md#provider-fetcher-tests-vcr-cassettes)

## Fork-local: fmp_cached

The fork's canonical provider wraps `fmp` with a MySQL gap-detection cache and is used
exclusively by the Analysis module. It has its **own** credential (`fmp_cached_api_key`).
→ [ADR-10](../01-decisions.md#adr-10-fork-local--fmp_cached-is-the-canonical-provider) · [fmp_cached architecture](../../architecture/providers/fmp-cached.md) · [Gotchas G9](../04-gotchas.md#g9--two-fmp-credentials-fork-local)

## Catalog

The full 34-provider quick-ref table (auth, async/sync, models, notes) lives in the
architecture index. → [providers/ architecture](../../architecture/providers/README.md)

→ Related design: [02 Conventions](../02-conventions.md) · [03 Recipes](../03-recipes.md) · [04 Gotchas](../04-gotchas.md)
