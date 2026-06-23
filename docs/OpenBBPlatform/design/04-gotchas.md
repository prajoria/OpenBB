# 04 — Gotchas

[← design/](./README.md) · Prev: [03 Recipes](./03-recipes.md) · Next: [05 Quality & Testing →](./05-quality-and-testing.md)

> The platform's permissiveness (P6) and code-generation (P5) buy ergonomics at the cost of
> **silent** failure modes. Each gotcha lists the **symptom**, the **cause**, and the **fix**.
> Last verified: 2026-06-02.

---

## G1 — A command silently disappears

**Symptom.** You added `@router.command(model="FooBar")` but `obb.equity.foo.bar` doesn't
exist (or `404` on REST).

**Cause.** `SignatureInspector.complete()` returns `None` when **no installed provider**
implements the named model — there are no params/return types to inject, so the command is
dropped. The warning only prints under `OPENBB_DEBUG_MODE=1`.

**Fix.** Implement at least one provider Fetcher for that model (Recipe A), rebuild, and
check with `OPENBB_DEBUG_MODE=1`. Also verify the `model=` string matches the standard
model class prefix exactly. → [P5](./00-principles.md#p5--generate-the-typed-surface-from-provider-metadata)

---

## G2 — Stale generated SDK after a change

**Symptom.** New provider/field/command not reflected in `obb`; old signature persists;
`import` shows the previous surface.

**Cause.** `openbb/package/*.py` are **build artifacts**. They're regenerated on `auto_build`
import or `openbb.build()`, but an outdated cache or a skipped rebuild leaves them stale.

**Fix.** `python -c "import openbb; openbb.build()"`. If still stale, delete the generated
`core/openbb/package/` contents (except `__init__.py`) and rebuild. → [ADR-1](./01-decisions.md#adr-1--generate-the-sdk-instead-of-writing-it)

---

## G3 — `__alias_dict__` mapped the wrong direction

**Symptom.** Query params don't reach the vendor, or vendor columns land as `extra`
instead of typed fields.

**Cause.** Direction confusion:
- On **`QueryParams`** the alias is **outbound** (our name → vendor param), applied in `model_dump()`.
- On **`Data`** the alias is **inbound** (vendor column → our field), a validation alias.

**Fix.** Put the remap on the right class for the right direction. → [Conventions § alias](./02-conventions.md#standard-models--provider-models)

---

## G4 — Typo'd params are silently accepted

**Symptom.** You pass `inteval="1d"` (typo) and get default behavior with **no error**.

**Cause.** `extra="allow"` + `Query.filter_extra_params` **warn and drop** unknown params
rather than rejecting them.

**Fix.** Double-check spelling; watch for the warning in logs. Treat unexpected defaults as
a possible silent-drop. → [ADR-5](./01-decisions.md#adr-5--extraallow-on-queryparams-and-data)

---

## G5 — Load failures are swallowed

**Symptom.** A provider/extension "isn't there"; `obb.<x>` missing; no traceback.

**Cause.** `Registry`/`ExtensionLoader` catch plugin import errors and only **warn**, so one
broken optional dependency can't take down the platform.

**Fix.** `OPENBB_DEBUG_MODE=1` then re-import to get the real traceback. Check the entry
point string and that the package installed editable. → [ADR-7](./01-decisions.md#adr-7--tolerate-plugin-load-failures-except-in-debug_mode)

---

## G6 — Returning `Data` from `extract_data`

**Symptom.** Double validation, alias confusion, or `transform_data` receiving already-typed
objects.

**Cause.** `extract_data`/`aextract_data` must return **raw** I/O (dicts/lists/text), not
`Data` objects. Validation belongs in `transform_data`.

**Fix.** Keep extract pure-I/O; build `Data` only in `transform_data`. → [P4](./00-principles.md#p4--the-fetcher-is-a-fixed-three-step-pipeline-tet)

---

## G7 — Implementing both `extract_data` and `aextract_data`

**Symptom.** Your sync `extract_data` never runs.

**Cause.** `Fetcher.__init_subclass__` binds the async version onto `extract_data` when both
exist — async silently wins.

**Fix.** Implement **exactly one**. Prefer async for HTTP. → [ADR-4](./01-decisions.md#adr-4--fetcher-implements-either-sync-or-async-extract-never-forced)

---

## G8 — Credential errors surface late

**Symptom.** A command runs, then throws an `OpenBBError` about a missing key partway in.

**Cause.** Credentials are validated **just before fetch** (`QueryExecutor.filter_credentials`),
not at the SDK boundary — this is what enables clean provider fallback.

**Fix.** Expect cred errors at execution time; set `require_credentials=False` for free
sources so they don't trigger at all. → [ADR-6](./01-decisions.md#adr-6--late-credential-validation-with-secretstr)

---

## G9 — Two FMP credentials (fork-local)

**Symptom.** `fmp_cached` calls fail auth even though `fmp_api_key` is set.

**Cause.** The fork-local `fmp_cached` provider has its **own** credential
`fmp_cached_api_key`, distinct from `fmp_api_key`, plus a MySQL config requirement.

**Fix.** Set both keys in `user_settings.json` and configure MySQL. The Analysis module uses
`fmp_cached` exclusively. → [ADR-10](./01-decisions.md#adr-10-fork-local--fmp_cached-is-the-canonical-provider) · [fmp_cached](../architecture/providers/fmp-cached.md)

---

## Quick triage table

| You see… | Suspect | Jump to |
|---|---|---|
| Command missing | no provider for model **or** stale build | G1, G2 |
| Param ignored | typo silently dropped | G4 |
| Provider missing | swallowed load error | G5 |
| Wrong/empty columns | alias direction | G3, G6 |
| Late key error | late cred validation | G8 |
| fmp_cached auth fail | wrong credential | G9 |

→ Next: [05 — Quality & Testing](./05-quality-and-testing.md).
