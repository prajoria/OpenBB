# 01 — Design Decisions (ADR-style)

[← design/](./README.md) · Prev: [00 Principles](./00-principles.md) · Next: [02 Conventions →](./02-conventions.md)

Each decision records the **context**, the **choice**, the **trade-off**, and the
**agent implication** (what it means for you when changing code). These are reconstructed
from the codebase, not a formal ADR log.

---

## ADR-1 — Generate the SDK instead of writing it

**Context.** Users want a typed, discoverable `obb.equity.price.historical(...)` with
per-provider parameters in the signature and docstring.

**Decision.** Generate `openbb/package/*.py` from the live router tree + `ProviderInterface`
via `PackageBuilder`, on `import openbb` (`auto_build`) and on demand (`openbb.build()`).

**Trade-off.** ✅ Always-correct typed surface reflecting installed providers. ❌ Generated
files are build artifacts (not committed except `__init__.py`); a rebuild step is required
after structural changes; stale caches bite (see [Gotchas](./04-gotchas.md)).

**Agent implication.** After editing a provider/extension/standard model, run
`python -c "import openbb; openbb.build()"`. Never commit `core/openbb/package/*` (a
pre-commit hook hard-fails it). → [App Runtime § build](../architecture/core/app-runtime.md#2-the-package-build-process)

---

## ADR-2 — One router tree feeds both the SDK and the REST API

**Context.** Two consumption surfaces, but command logic should exist once.

**Decision.** `RouterLoader.from_extensions()` builds a single nested `Router` tree;
`PackageBuilder` generates the SDK from it and `api/router/commands.py` wraps it for FastAPI.

**Trade-off.** ✅ Zero duplication; identical behavior across surfaces. ❌ The surfaces
diverge subtly (provider selection differs; auth only on REST), which can confuse debugging.

**Agent implication.** Fix a command once in its extension router. Remember the two
surfaces choose the provider differently. → [Request Lifecycle § divergence](../architecture/02-request-lifecycle.md#provider-selection)

---

## ADR-3 — Standard models owned by core; providers subclass

**Context.** 34 vendors with overlapping but inconsistent schemas.

**Decision.** Core defines thin, vendor-neutral standard models; providers subclass to add
fields and aliases. Standardizing a new shared field requires a core PR.

**Trade-off.** ✅ Interchangeable providers; stable consumer contract; works with toolkits.
❌ Provider authors can't standardize unilaterally; some genuinely-shared fields stay in
`Optional` extras until promoted.

**Agent implication.** To add a *provider-specific* field, subclass in the provider model.
To add a *cross-provider* field, you must edit the standard model in core (and rebuild).
→ [Conventions § models](./02-conventions.md#standard-models--provider-models)

---

## ADR-4 — Fetcher implements either sync or async extract, never forced

**Context.** Some sources are HTTP-async-friendly (aiohttp), others are sync libraries
(yfinance, requests-based scrapers).

**Decision.** `Fetcher.__init_subclass__` lets a subclass implement **either**
`extract_data` (sync) **or** `aextract_data` (async); async is bound onto `extract_data`,
and `maybe_coroutine` calls whichever correctly. Implementing neither fails at class creation.

**Trade-off.** ✅ Providers pick the natural style; engine stays uniform. ❌ Implementing
*both* silently uses async; the magic is non-obvious to newcomers.

**Agent implication.** Implement exactly one extract method. Async is preferred for HTTP.
→ [Provider Framework § TET](../architecture/core/provider-framework.md#2-the-fetcher-tet-lifecycle)

---

## ADR-5 — `extra="allow"` on QueryParams and Data

**Context.** Vendors return extra columns and accept extra params the standard model
doesn't name.

**Decision.** Both base models use `extra="allow"`. Extra result columns survive onto
`Data`; unsupported query params are **warned and dropped** (`Query.filter_extra_params`),
not rejected.

**Trade-off.** ✅ Maximum flexibility; toolkits accept any `list[Data]`. ❌ **Typo'd
parameters are silently accepted** (only a warning), a real footgun.

**Agent implication.** Double-check param spelling; a typo won't raise. → [Gotchas](./04-gotchas.md#g4-typod-params-are-silently-accepted)

---

## ADR-6 — Late credential validation with SecretStr

**Context.** A command may fall back across providers; credentials shouldn't block
construction.

**Decision.** Credentials are validated inside `QueryExecutor.filter_credentials`, right
before `fetch_data`, and stored as `SecretStr`. Missing required cred → `OpenBBError`
pointing at the provider website (only if `require_credentials` is True).

**Trade-off.** ✅ Clean provider fallback; secrets aren't leaked in logs. ❌ A credential
error surfaces late in the call, not at the SDK boundary.

**Agent implication.** Set `require_credentials=False` for free sources. Expect cred
errors at execution time. → [Models & Settings § credentials](../architecture/core/models-and-settings.md#2-credentials)

---

## ADR-7 — Tolerate plugin load failures (except in DEBUG_MODE)

**Context.** Optional providers have heavy/optional dependencies.

**Decision.** `Registry`/`ExtensionLoader` swallow load errors with a warning so one bad
plugin can't break the platform. `OPENBB_DEBUG_MODE=1` makes them raise with tracebacks.

**Trade-off.** ✅ Robust default experience. ❌ A broken provider **silently disappears**;
you may not notice it failed to load.

**Agent implication.** When a provider "isn't there," set `OPENBB_DEBUG_MODE=1` and
re-import to see the real error. → [Gotchas](./04-gotchas.md#g5-load-failures-are-swallowed)

---

## ADR-8 — Lazy, in-function imports in providers

**Context.** Import time matters (measured with `tuna`); providers pull heavy deps.

**Decision.** Providers import heavy modules **inside** fetcher methods, not at module top.
Ruff's `PLC0415` (import-not-top-level) is globally ignored to allow this.

**Trade-off.** ✅ Fast `import openbb`. ❌ Imports scattered in function bodies; unusual style.

**Agent implication.** Follow the pattern — import provider helpers inside
`extract_data`/`aextract_data`. → [Conventions § providers](./02-conventions.md#provider-package)

---

## ADR-9 — Toolkits are data-in commands, not providers

**Context.** TA/quant/econometrics operate on already-fetched data, not a vendor.

**Decision.** Toolkit commands take `data: list[Data]` + scalars, use `methods=["POST"]`,
and have **no** `model=`/provider injection. They compute locally and return `OBBject`.

**Trade-off.** ✅ Composable (`historical(...).to_df()` → `technical.rsi(data=...)`).
❌ A different command shape that newcomers may copy incorrectly.

**Agent implication.** Don't give toolkit commands the 4-param provider signature.
→ [Toolkit vs Data Routers](../architecture/extensions/toolkit-vs-data-routers.md)

---

## ADR-10 (fork-local) — `fmp_cached` is the canonical provider

**Context.** This fork's Analysis module needs reproducible, low-cost FMP access.

**Decision.** A fork-local `fmp_cached` provider wraps `fmp` with a MySQL gap-detection
cache and is used **exclusively** by `Analysis/` (`PRIMARY_PROVIDER = "fmp_cached"`).

**Trade-off.** ✅ Caching, fewer API calls, deterministic tests. ❌ Requires MySQL config;
diverges from upstream; two FMP credentials exist (`fmp_api_key`, `fmp_cached_api_key`).

**Agent implication.** For Analysis work, use `fmp_cached`; configure MySQL in
`user_settings.json`. → [fmp_cached](../architecture/providers/fmp-cached.md)

---

→ Next: [02 — Conventions](./02-conventions.md).
