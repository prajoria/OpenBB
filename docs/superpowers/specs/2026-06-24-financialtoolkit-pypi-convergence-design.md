# Design — Drop FinanceToolkit fork/path dep; converge on PyPI `financetoolkit`

**Tracking:** GitHub issue [#19](https://github.com/prajoria/OpenBB/issues/19)
**Date:** 2026-06-24
**Phase:** 1 (Design) — approved 2026-06-24

## 1. Context

`openbb_platform/extensions/financialtoolkit/pyproject.toml` currently declares:

```toml
financetoolkit = { path = "../../../FinanceToolkit", develop = true }
```

against a submodule of `prajoria/FinanceToolkit` (pinned to `e51f1c8`, a fork
of `JerBouma/FinanceToolkit 2.0.6`). Two release blockers:

1. **Fork coupling.** Clones require `prajoria/FinanceToolkit` to stay
   available; divergence from canonical upstream is hard to audit.
2. **Non-distributable.** `path =` only resolves for editable installs from a
   submodule-initialized checkout; no wheel/sdist for `pip install
   openbb-financialtoolkit`.

### Findings from a fresh probe (2026-06-24)

| Probe | Result |
|---|---|
| Fork divergence from `JerBouma/FinanceToolkit main` | 5 commits ahead, 0 behind |
| Substantive fork code | `8b75664` adds 3-tier fallback (FMP cached → FMP direct → CBOE) in `financetoolkit/fmp_model.py` — ~311 LoC + 234 LoC tests + 265 LoC docs |
| Other fork commits | 4 notebook/example chrome commits |
| Extension dependency on the fallback | **None** — `openbb_financialtoolkit` never calls `get_historical_data`; uses Toolkit only for ratios / risk / performance |
| Defensive shim for `tickers` vs `symbols` | Already implemented in `adapters/toolkit_factory.create_toolkit` (lines 39–44) |
| Latest PyPI | `financetoolkit 2.1.2` (4 minor versions ahead of fork base) |
| Current venv state | `import financetoolkit` fails — editable install is broken anyway |

The 3-tier fallback is real value, but it lives in `fmp_model.py` and the
extension does not use it. The fallback can stay in `prajoria/FinanceToolkit`
or be relocated separately.

## 2. Goals

1. Make `openbb-financialtoolkit` install cleanly with `pip install` (no submodule).
2. Drop the path dependency and the FinanceToolkit submodule from this repo.
3. Track the orphaned 3-tier fallback in a follow-up.
4. Keep the extension's behaviour the same (signature-introspection factory
   already protects against `tickers`/`symbols` rename).

## 3. Non-goals

- Upstream the 3-tier fallback to `JerBouma/FinanceToolkit` (separate effort).
- Re-architect the fallback as an extension-level wrapper (separate effort).
- Delete `prajoria/FinanceToolkit` from GitHub.
- Delete the local `FinanceToolkit/` working tree.

## 4. Design decisions

### D1. PyPI dependency
Replace in `openbb_platform/extensions/financialtoolkit/pyproject.toml`:

```diff
- financetoolkit = { path = "../../../FinanceToolkit", develop = true }
+ financetoolkit = "^2.1.2"
```

Caret allows any 2.x compatible release. The factory's signature-introspection
absorbs API drift on `tickers`/`symbols`.

### D2. Submodule removal
- Delete the `[submodule "FinanceToolkit"]` block from `.gitmodules`.
- `git rm --cached -r FinanceToolkit` (untrack only; working tree preserved
  for the user's standalone 3-tier work).
- Add `/FinanceToolkit/` to `.gitignore`.
- Remove `.git/modules/FinanceToolkit/` (orphan submodule git dir) in a
  follow-up local-cleanup note; not committed.

### D3. 3-tier fallback follow-up
File a bd issue: "Decide disposition of 3-tier fallback in
`prajoria/FinanceToolkit:financetoolkit/fmp_model.py` — upstream to
JerBouma, port to openbb-financialtoolkit adapter layer, or keep
standalone." Link to `prajoria/FinanceToolkit@8b75664` for reference.

### D4. Verification
- `pip install -e openbb_platform/extensions/financialtoolkit` in `.venv_win`
  (will pull `financetoolkit==2.1.2` from PyPI).
- `pytest openbb_platform/extensions/financialtoolkit -v` — all tests pass.
- Smoke-test `create_toolkit(["AAPL"], api_key="X")` constructs without error.
- If 2.1.2 has breaking changes, pin downward to the highest compatible
  release (`^2.0.7` floor); update spec.

### D5. README + docs
- Rewrite Installation section of
  `openbb_platform/extensions/financialtoolkit/README.md` from
  submodule+editable to plain `pip install`.
- Grep-and-clean any other references to the submodule
  (`openbb_platform/providers/fmp_cached/docs/DATABASE_CONFIGURATION.md`
  and the two `IMPLEMENTATION_PLAN.md` files are known suspects).
- Don't touch `prajoria/FinanceToolkit`'s own README.

### D6. Acceptance criteria
1. `openbb_platform/extensions/financialtoolkit/pyproject.toml` has
   `financetoolkit = "^2.1.2"` and no `path =` line.
2. `.gitmodules` no longer lists `FinanceToolkit`.
3. `git ls-files FinanceToolkit/` returns empty.
4. `pytest openbb_platform/extensions/financialtoolkit -v` returns green
   against installed `financetoolkit 2.1.x`.
5. Extension README Installation section is PyPI-only.
6. Follow-up bd for 3-tier fallback disposition is filed and linked.

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| financetoolkit 2.1.x has a breaking change vs 2.0.6 | Run tests; pin down to highest passing 2.0.x and document |
| `dev_install.py` or other tooling hard-references `FinanceToolkit/` | Grep before D2; fix if found |
| User wants the 3-tier fallback back in-tree later | D3 follow-up bd is the place to decide; not gated on this issue |

## 6. Out-of-scope follow-ups

- File 3-tier fallback disposition issue (created in this cycle's Phase 2).
- Delete `.git/modules/FinanceToolkit/` from local clones (per-developer cleanup, no commit).
- Eventually evaluate whether `openbb-financialtoolkit` should hold a `Toolkit` wrapper that re-adds the 3-tier fallback at the adapter layer.
