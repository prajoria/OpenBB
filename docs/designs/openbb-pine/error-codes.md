# openbb-pine error codes

This document is the user-facing reference for every error code the Pine
compiler + runtime can raise. It is the source-of-truth companion to
[`openbb_pine/error_codes.py`](../../../openbb_platform/extensions/pine/openbb_pine/error_codes.py),
which carries the same catalog machine-readably. **CI enforces sync**: the
AST-walking test
`openbb_pine/tests/unit/test_error_model.py::TestErrorCodeEnforcement`
walks every `raise Pine*Error(rule=…)` in the codebase and verifies the
literal code is present in `ERROR_CODES`.

Adding a new code:

1. Add an `ErrorCodeSpec(...)` row to `openbb_pine/error_codes.py`. Give it
   the next unused three-digit suffix in its prefix's range — **never
   renumber** existing codes.
2. Add a `##` section here with the same fields.
3. Land the raise site that uses the new code — the enforcement test
   verifies the round trip.

Prefix ownership (D1 §5.2):

| Prefix   | Class                              | Range     | Owner              |
|----------|------------------------------------|-----------|--------------------|
| `PS`     | `PineSyntaxError`                  | PS001+    | Lexer / parser     |
| `PT`     | `PineTypeError`                    | PT001-008 | Type checker (D1 §4.4) |
| `PU`     | `PineUnsupportedBuiltinError`      | PU001+    | Stdlib bridge      |
| `PF`     | `PineUnsupportedFeatureError`      | PF001+    | Feature owner      |
| `CG`     | `PineCodegenError`                 | CG001-006 | Codegen (D1 §3.2)  |
| `IC`     | `PineInternalCompilerError`        | IC001+    | Compiler           |
| `CACHE`  | `PineCacheError`                   | CACHE001+ | Cache              |
| `RT`     | `PineRuntimeError`                 | RT001+    | Runtime            |
| `SEC`    | `PineSecurityError`                | SEC001+   | Security           |
| `PROV`   | `PineProviderError` family         | PROV001+  | Data provider      |

Each section below follows a fixed shape so the ADR-style skim stays
predictable:

- **Class** — the exception class raised (subclass of `PineError`, which is
  the platform's `OpenBBError`).
- **Short** — one-line summary matching `ErrorCodeSpec.short_description`.
- **Detailed** — what the code means, what triggered it, and any nuance
  (like "reserved but doesn't fire yet").
- **Fix** — the operator / user workaround.
- **Tracking** — GitHub label filter for related issues (see also the
  `tracking_label` field in `ErrorCodeSpec`).

---

## Syntax errors (PS###)

### PS001 — Unexpected token

- **Class**: `PineSyntaxError`
- **Short**: Unexpected token.
- **Detailed**: The lexer or parser hit a token that no grammar production
  accepts at the current position. Typically caused by typos, unbalanced
  parens, or missing operators between operands. The message includes a hint
  sourced from lark's `match_examples()` when the failure matches a known
  pattern (see D1 §1.3).
- **Fix**: Read the source position + column in the error, look at the
  offending token, and re-check the surrounding syntax against
  [Pine v6's reference](https://www.tradingview.com/pine-script-reference/v6/).
- **Tracking**: `pine-syntax`

### PS002 — Malformed version pragma

- **Class**: `PineSyntaxError`
- **Short**: Malformed `//@version=` pragma.
- **Detailed**: The `//@version=N` pragma at line 1 is missing the version
  number or has non-digit characters after the `=` sign.
- **Fix**: Ensure the first line is `//@version=6` (or `=5` for v5→v6
  auto-migration).
- **Tracking**: `pine-syntax`

### PS003 — Mismatched indentation

- **Class**: `PineSyntaxError`
- **Short**: Dedent doesn't match any outer indent level.
- **Detailed**: A dedent doesn't line up with any previously-seen indent
  level. Pine uses Python-style significant indentation; mixed tabs + spaces
  or an unexpected outdent trigger this.
- **Fix**: Convert tabs to spaces (or vice-versa) — do not mix — and
  re-indent the block to match its opening.
- **Tracking**: `pine-syntax`

### PS004 — Unexpected character

- **Class**: `PineSyntaxError`
- **Short**: The lexer hit an unexpected character.
- **Detailed**: The lexer hit a character not part of any valid token —
  typically stray unicode punctuation, or an ASCII character outside the
  alphabet Pine accepts at the current position.
- **Fix**: Retype the offending character; some editors auto-substitute
  curly quotes / long dashes.
- **Tracking**: `pine-syntax`

### PS005 — Unterminated string literal

- **Class**: `PineSyntaxError`
- **Short**: String literal reached EOF/EOL without a closing quote.
- **Detailed**: A string literal (`"..."` or `'...'`) did not reach its
  closing quote before EOF or end-of-line.
- **Fix**: Close the string, or use `\"` inside `"…"` if the string
  contains a quote character.
- **Tracking**: `pine-syntax`

### PS006 — Unsupported `pine_version`

- **Class**: `PineSyntaxError`
- **Short**: `compile_pine(pine_version=N)` given an N outside {5, 6}.
- **Detailed**: `compile_pine(pine_version=N)` was called with an N outside
  the supported {5, 6} set. v5 is auto-migrated to v6 by C7.
- **Fix**: Use `pine_version=5` or `pine_version=6`.
- **Tracking**: `pine-syntax`

### PS007 — Missing grammar file

- **Class**: `PineSyntaxError`
- **Short**: Lark grammar file for this Pine version is not present.
- **Detailed**: The lark grammar file for the requested Pine version is not
  present in `compiler/grammar/`. Package integrity issue — pip install
  probably dropped a data file.
- **Fix**: Reinstall openbb-pine.
- **Tracking**: `pine-syntax`

---

## Type errors (PT001-PT008 reserved by D1 §4.4)

### PT001 — Function parameter qualifier mismatch

- **Class**: `PineTypeError`
- **Short**: `simple<T>` parameter cannot receive `series<T>` argument.
- **Detailed**: A function parameter declared `simple<T>` cannot receive a
  `series<T>` argument (e.g. `ta.sma(close, length)` where `length` is
  `simple<int>`, not `series<int>`). Pine's qualifier lattice is
  `const → input → simple → series` — promotion is one-way and cannot be
  reversed.
- **Fix**: Use a `simple<int>` for length (e.g. an `input.int` result).
  If you need a dynamic-length calculation, use a builtin that accepts
  `series<int>` explicitly.
- **Tracking**: `pine-type`

### PT002 — `var` initializer must be simple

- **Class**: `PineTypeError`
- **Short**: `var x = e` requires `e: simple<T>`.
- **Detailed**: `var x = e` requires `e: simple<T>` (Pine spec: `var`
  initializers run once at bar 0).
- **Fix**: Move the series-dependent computation out of the `var` init and
  assign to `x` normally on later bars via `:=`.
- **Tracking**: `pine-type`

### PT003 — `if`/`while` condition must be boolean

- **Class**: `PineTypeError`
- **Short**: Non-boolean condition rejected.
- **Detailed**: `if cond` requires `cond: series<bool>` or `simple<bool>`;
  implicit truthiness on `int`/`float` is rejected.
- **Fix**: Add an explicit comparison: `if x > 0` instead of `if x`.
- **Tracking**: `pine-type`

### PT004 — History access requires `series<T>` + integer offset

- **Class**: `PineTypeError`
- **Short**: `x[n]` history access with wrong operand types.
- **Detailed**: `x[n]` history access requires `x: series<T>` and `n` must
  be `simple<int>` or `const<int>`.
- **Fix**: For array indexing, use `array.get(x, n)` explicitly. For history
  access, ensure `x` is series and `n` is a simple int (e.g. an
  `input.int()` or literal).
- **Tracking**: `pine-type`

### PT005 — `:=` reassign qualifier violation

- **Class**: `PineTypeError`
- **Short**: `:=` target's qualifier must be ≥ RHS qualifier.
- **Detailed**: `:=` reassign target must already be declared, and the RHS
  qualifier must be ≤ LHS qualifier per the lattice.
- **Fix**: Either widen the declared qualifier of the target, or narrow the
  RHS by pre-computing it into a `simple` local first.
- **Tracking**: `pine-type`

### PT006 — `na` propagation

- **Class**: `PineTypeError`
- **Short**: `na` operand yields `na` of the inferred type.
- **Detailed**: Any non-`na` op with an `na` operand yields `na` of the
  inferred type (`NaT.unify(T) → T`). This is the normal Pine behavior;
  PT006 fires when the type checker cannot infer the target type from
  surrounding context.
- **Fix**: Annotate the `na` with a type ascription: `na(float)` or
  `na(int)`.
- **Tracking**: `pine-type`

### PT007 — v6 type argument mismatch (reserved)

- **Class**: `PineTypeError`
- **Short**: v6 type argument doesn't satisfy the builtin's signature.
- **Detailed**: v6 type arguments (e.g. `array.new<float>(0)`) must satisfy
  the builtin's signature; mismatch names both expected and received. This
  code is reserved for the v6 type-argument checker (may not fire yet).
- **Fix**: Read the builtin signature and use the type argument it
  documents.
- **Tracking**: `pine-type`

### PT008 — UDT field not found

- **Class**: `PineTypeError`
- **Short**: `obj.field` — `field` not in UDT.
- **Detailed**: `obj.field` access requires `field` to exist on the UDT;
  suggestions via Levenshtein distance.
- **Fix**: Check the UDT declaration; the error message includes the
  closest suggested field name.
- **Tracking**: `pine-type`

---

## Unsupported features (PF###)

### PF001 — Pine v1-v4 not supported

- **Class**: `PineUnsupportedFeatureError`
- **Short**: Pine v1-v4 is an explicit non-goal.
- **Detailed**: The migration shim covers v5→v6 only; v1-v4 is an explicit
  PRD §3.3 non-goal. See the tracking issue to request a specific script
  be re-evaluated.
- **Fix**: Manually port the script forward to v5 or v6.
- **Tracking**: `pine-v5-migration`

### PF002 — Typed decl in body / future-version pragma

- **Class**: `PineUnsupportedFeatureError`
- **Short**: Two distinct cases; see detail.
- **Detailed**: Two distinct cases share this code: (a) the C3 type checker
  rejects typed variable declarations in function bodies (they land later),
  (b) the compiler refuses to speculate on a Pine version above v6.
- **Fix**: (a) Move the type declaration to module scope, or drop the
  explicit type annotation on the body-local. (b) Downgrade the version
  pragma to `//@version=6`.
- **Tracking**: `pine-feature`

### PF003 — v5 construct not migrated

- **Class**: `PineUnsupportedFeatureError`
- **Short**: v5 construct not migrated by `V5_REWRITES`.
- **Detailed**: The v5 → v6 regex rewrite in `V5_REWRITES` did not match
  this call (likely a multi-line or deeply-nested form). File a rewrite
  request with a minimal repro.
- **Fix**: Manually port the offending construct to v6 syntax, or open an
  issue with the multi-line snippet.
- **Tracking**: `pine-v5-migration`

### PF010 — `strategy()` decl — deferred to M2

- **Class**: `PineUnsupportedFeatureError`
- **Short**: Strategy compilation lands at M2.
- **Detailed**: Strategy compilation lands at M2 per PRD §3.2 (bead
  0e9.5.6). Indicator scripts compile today; strategy scripts are
  scaffolded but fast-fail here.
- **Fix**: Convert the script to an `indicator()` script, or wait for the
  M2 strategy work.
- **Tracking**: `pine-feature`

### PF011 — `library()` decl — deferred

- **Class**: `PineUnsupportedFeatureError`
- **Short**: Library scripts have no Phase-1 use-case.
- **Detailed**: `library()` scripts define reusable functions for import
  by other Pine scripts. No Phase-1 use-case; deferred until someone files
  a request.
- **Fix**: Inline the library into the caller, or open a tracking issue.
- **Tracking**: `pine-feature`

---

## Codegen errors (CG###) — ALL are compiler bugs (P0)

Any CG### firing in production is a compiler bug. File an issue with the
minimal Pine source that triggered it.

### CG001 — Disallowed AST node type

- **Class**: `PineCodegenError`
- **Short**: Codegen emitted an ast.* node outside NODE_TYPE_ALLOWLIST.
- **Detailed**: Codegen emitted an `ast.*` node outside
  `NODE_TYPE_ALLOWLIST` per D1 §3.2. Always a compiler bug; a fresh CG001
  in production is a P0.
- **Fix**: File a compiler bug with the source. As a workaround, avoid the
  offending Pine construct.
- **Tracking**: `pine-codegen`

### CG002 — Disallowed ImportFrom module

- **Class**: `PineCodegenError`
- **Short**: Codegen emitted an import outside MODULE_ALLOWLIST.
- **Detailed**: Codegen emitted an `ast.ImportFrom` whose `.module` is
  outside `MODULE_ALLOWLIST`. All `ast.Import` nodes are rejected as a
  category. Always a compiler bug.
- **Fix**: File a compiler bug with the source.
- **Tracking**: `pine-codegen`

### CG003 — Disallowed top-level free name

- **Class**: `PineCodegenError`
- **Short**: Codegen emitted a top-level name outside GLOBAL_NAME_ALLOWLIST.
- **Detailed**: Codegen emitted a top-level `ast.Name` outside
  `GLOBAL_NAME_ALLOWLIST` per D1 §3.2. Always a compiler bug.
- **Fix**: File a compiler bug with the source.
- **Tracking**: `pine-codegen`

### CG004 — Unhandled IR statement kind

- **Class**: `PineCodegenError`
- **Short**: `_visit_stmt` doesn't know how to lower this IR node.
- **Detailed**: `_visit_stmt` hit an `ir.*` statement node the visitor
  does not know how to lower. Compiler-invariant; means a new IR node was
  added without a corresponding visit method.
- **Fix**: File a compiler bug.
- **Tracking**: `pine-codegen`

### CG005 — Unhandled assignment-target kind

- **Class**: `PineCodegenError`
- **Short**: `_visit_assign_target` given a non-{Name/Attribute/Subscript/TupleExpr}.
- **Detailed**: `_visit_assign_target` was given a target that is not one
  of Name / Attribute / Subscript / TupleExpr.
- **Fix**: File a compiler bug.
- **Tracking**: `pine-codegen`

### CG006 — Unhandled IR expression kind

- **Class**: `PineCodegenError`
- **Short**: `_visit_expr` doesn't know how to lower this IR node.
- **Detailed**: `_visit_expr` hit an `ir.*` expression node the visitor
  does not know how to lower.
- **Fix**: File a compiler bug.
- **Tracking**: `pine-codegen`

---

## Internal compiler errors (IC###)

### IC001 — Unregistered error code raised

- **Class**: `PineInternalCompilerError`
- **Short**: `raise Pine*Error(rule=X)` where X is not in `ERROR_CODES`.
- **Detailed**: A `raise Pine*Error(rule=…)` used a code that is not
  present in `ERROR_CODES`. The AST-walking enforcement test catches this
  at CI time; this class exists so a runtime invocation of
  `assert_code_registered` also raises structurally when the code is
  missing.
- **Fix**: Register the code in
  [`openbb_pine/error_codes.py`](../../../openbb_platform/extensions/pine/openbb_pine/error_codes.py),
  or fix the typo at the raise site.
- **Tracking**: `pine-internal`

---

## Security errors (SEC###)

### SEC001 — Forbidden import (T3 sandbox violation)

- **Class**: `PineSecurityError`
- **Short**: Runtime scan found a forbidden module import in compiled source.
- **Detailed**: The runtime's `scan_for_forbidden_imports` (T3 second line
  of defense) found an import of a disallowed module in the compiled
  source. Ordinarily impossible because the T1 compiler-side allowlist
  gate should have blocked it; this code firing in production means either
  the allowlist has a hole or the compiled source was tampered with.
- **Fix**: Do NOT dismiss — audit whether the compiled source came from
  the trusted compiler path. Then file a compiler bug.
- **Tracking**: `pine-security`

---

## How to add a new code

1. Pick the right prefix (from the table above); use the next unused
   three-digit suffix in that prefix's range.
2. Add an `ErrorCodeSpec(...)` row to
   [`openbb_pine/error_codes.py`](../../../openbb_platform/extensions/pine/openbb_pine/error_codes.py).
3. Add a `## PS009 — Short description` section here matching the template.
4. Land the raise site (typically `raise PineFooError(rule="PS009", ...)`).
5. Run the enforcement test:

    ```
    pytest openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_model.py::TestErrorCodeEnforcement
    ```

    If it fails, either register the code (step 2) or fix the raise site.
