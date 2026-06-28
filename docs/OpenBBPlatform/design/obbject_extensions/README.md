# obbject_extensions/ — Design

[← design/](../README.md) · Architecture counterpart: [obbject_extensions/ architecture](../../architecture/obbject_extensions/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The *why* behind OBBject accessor plugins in `openbb_platform/obbject_extensions/`.
> Last verified: 2026-06-02.

---

## What an OBBject extension is

A third plugin type (alongside providers and router extensions): it **attaches an accessor**
to every `OBBject` result instead of adding commands or data sources. The reference
implementation is `charting`, which adds `.charting` to every result so you can do
`obb.equity.price.historical(...).charting.show()`.

→ [P3 three plugin types](../00-principles.md#p3--plugins-via-entry-points-discovered-at-runtime) · [System Overview § plugin types](../../architecture/01-system-overview.md#the-three-plugin-types)

## Design rules

1. Register via the `openbb_obbject_extension` entry-point group (the third group).
2. The accessor is **lazily attached** — it appears on results only when the package is
   installed, and its absence never breaks core. → [ADR-7](../01-decisions.md#adr-7--tolerate-plugin-load-failures-except-in-debug_mode)
3. An accessor operates on an **already-built** `OBBject` (its `results`, `provider`,
   `extra`); it does not fetch or define commands. This keeps it orthogonal to the router
   and provider systems.

## Why a separate plugin type

Charting and similar concerns are **cross-cutting** — they apply to the output of *any*
command regardless of provider or extension. Modeling them as accessors keeps that behavior
in one installable package instead of duplicated across every command. → [P2](../00-principles.md#p2--two-surfaces-one-engine)

## Architecture deep-dive

The accessor mechanism (`app/model/extension.py::Extension`, registration, the `.charting`
pattern) is documented in the architecture counterpart.
→ [obbject_extensions/ architecture](../../architecture/obbject_extensions/README.md)

→ Related design: [00 Principles](../00-principles.md) · [01 Decisions](../01-decisions.md)
→ Upstream: `third_party/openbb-docs/content/odp/python/developer/extension_types/{obbject,charting,plugins}.md`
