"""Shared Pine error hierarchy + Diagnostic dataclass.

Owned here per D3 section 4.7 (post-D1/D2/D3 cross-doc consolidation, commit
``af08128d3``): runtime and compiler modules import from this single module
rather than defining their own ``PineError`` roots. This avoids the
three-``PineError``-classes-with-different-bases bug the cross-doc reviewer
flagged.

Every class subclasses ``openbb_core.app.model.abstract.error.OpenBBError`` so
the platform's standard error middleware can intercept and serialize them
uniformly. Each class carries a ``code`` class attribute matching its name,
used by the REST error envelope (D3 section 4.1).

**Diagnostic** (D1 §5.1) is a first-class per-diagnostic carrier — every
error surface can carry ``tuple[Diagnostic, ...]`` so users see every defect
in one pass rather than first-error-wins. The dataclass is frozen + slotted
so it's cheap to construct and hash-stable (safe to shove into a ``set`` or
a dict key for dedup).

The **structured-init pattern** (kw-only-with-backwards-compat-positional-string)
was proven across the post-R2 / post-R6 / Wave-3A / Wave-4 pre-empt-fix
cycle. Every ``PineError`` subclass in this module follows the same shape:

* Positional ``str`` → treated as pre-stitched ``message=`` (backwards-compat).
* kw-only ``message=`` → wins over structured rendering, useful for callers
  that want to fully control the string.
* Otherwise → structured attrs are combined into a default rendering.
* ``code`` / ``tracking_url`` class attributes provide REST-envelope
  defaults; instance attrs shadow them on a per-raise basis (never mutated
  on the class).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openbb_core.app.model.abstract.error import OpenBBError


# ---------------------------------------------------------------------------
# Diagnostic — D1 §5.1 per-diagnostic carrier.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single diagnostic emitted by any compile-time or runtime layer.

    Errors carry ``tuple[Diagnostic, ...]`` so multiple defects surface in one
    raise (mirroring :class:`PineDataValidationError`'s ``defects`` list but
    structured, per-diagnostic). Warnings surface via
    :class:`openbb_pine.compiler.type_checker.TypeCheckResult`'s diagnostics
    field too.

    Fields map 1:1 to the D1 §5.4 REST-envelope shape — the serialization
    contract is ``dataclasses.asdict(diag)``.

    Rendering: :meth:`render` produces a Pine-style diagnostic with a caret
    line beneath the offending column when ``source`` is provided (see
    D1 §5.3 for the intended UX).
    """

    severity: Literal["error", "warning", "info", "hint"]
    code: str
    """Three-letter prefix + three-digit code — see
    :mod:`openbb_pine.error_codes` for the registry."""

    message: str
    location: tuple[str, int, int] | None = None
    """``(file, line, col)`` — 1-based line/col per Pine convention."""

    span: tuple[int, int] | None = None
    """Byte offsets in the source, if the front-end tracked them."""

    hint: str | None = None
    tracking_url: str | None = None
    related: tuple[str, ...] = ()
    """Cross-reference to related codes (e.g. ``("PT001",)`` on a PT005 that
    the operator should also read about)."""

    def render(self, source: str | None = None) -> str:
        """Render a Pine-style diagnostic string.

        Format (matches D1 §5.3)::

            {severity} [{code}] — {message}
              {source-file}:{line}:{col}
              {line} │ <source line>
                     │       ^^ (caret under the offending column)
              hint: {hint}
              → {tracking_url}

        When ``source`` is passed, the offending source line is rendered
        with a caret pointing at ``location[2]`` (1-based column).
        """
        parts: list[str] = []
        header = f"{self.severity} [{self.code}] — {self.message}"
        parts.append(header)
        if self.location is not None:
            file, line, col = self.location
            parts.append(f"  {file}:{line}:{col}")
            if source is not None:
                # Extract the offending line (1-based) and build the caret.
                lines = source.splitlines()
                if 1 <= line <= len(lines):
                    src_line = lines[line - 1]
                    gutter = f"  {line} │ "
                    parts.append(f"{gutter}{src_line}")
                    # Caret column is (col - 1) inside the source-line prefix
                    # of ``gutter``-many spaces. Guard against col outside
                    # the line so a stray span offset can't blow up render.
                    caret_col = max(col - 1, 0)
                    parts.append(f"  {' ' * len(str(line))} │ {' ' * caret_col}^^")
        if self.hint:
            parts.append(f"  hint: {self.hint}")
        if self.tracking_url:
            parts.append(f"  → {self.tracking_url}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class PineError(OpenBBError):
    """Root for every Pine-extension error."""

    code: str = "PineError"
    tracking_url: str | None = None


# --- Compiler-side errors (D1 territory) ---------------------------------


class PineCompileError(PineError):
    """A compile-time failure in the Pine -> Python translator."""

    code: str = "PineCompileError"


class PineSyntaxError(PineCompileError):
    """The Pine source did not parse.

    Structured init added in bead 0e9.5.8 C8 — matches the D1 §5.1 shape
    (rule, source_line, line, col, hint). Backwards-compat: existing
    positional-string raises in the lexer + parser continue to work, so this
    bead doesn't require lock-step edits across the compiler front-end.

    Example::

        raise PineSyntaxError(
            rule="PS001",
            source_line="length = input.int(=20)",
            line=7,
            col=18,
            hint="input.int's first arg is the default value.",
        )
    """

    code: str = "PineSyntaxError"

    def __init__(
        self,
        *args: object,
        rule: str | None = None,
        source_line: str | None = None,
        line: int | None = None,
        col: int | None = None,
        hint: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.rule = rule
        self.source_line = source_line
        self.line = line
        self.col = col
        self.hint = hint
        if tracking_url is not None:
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        else:
            rule_s = f" [{rule}]" if rule else ""
            loc = ""
            if line is not None and col is not None:
                loc = f" at line {line}, col {col}"
            elif line is not None:
                loc = f" at line {line}"
            text = f"PineSyntaxError{rule_s}{loc}"
            if source_line:
                text += f"\n  in: {source_line}"
            if hint:
                text += f"\n  hint: {hint}"
        super().__init__(text)


class PineTypeError(PineCompileError):
    """A static type check failed during compilation.

    Carries the structured diagnostic shape D1 §5.1 specifies, so downstream
    (REST envelope D3 §4.1, CLI rendering D3 §10.5) can surface the rule
    code, expected/got types, source location, and the optional hint
    uniformly. Init signature mirrors the post-R2/R6 consolidation pattern
    (commits 3c6bb0a81 + d4b294da5) — added preemptively rather than after
    review since the pattern is now proven across PineDataValidationError +
    PineFMPUnreachableError.

    Backward compatible: pass a positional string OR ``message=`` to wrap a
    pre-stitched string (e.g. ``raise PineTypeError("cannot unify ...")`` in
    ``compiler.types.unify``).

    Example::

        raise PineTypeError(
            rule="PT001",
            expected="simple<int>",
            got="series<int>",
            expr_text="ta.sma(close, dyn_len)",
            location=("<inline>", 5, 12),
            hint="Pine's ta.sma requires a non-series length.",
        )
    """

    code: str = "PineTypeError"

    def __init__(
        self,
        *args: object,
        expected: object | None = None,
        got: object | None = None,
        expr_text: str | None = None,
        location: tuple[str, int, int] | None = None,
        rule: str | None = None,
        hint: str | None = None,
        message: str | None = None,
    ) -> None:
        # Backwards-compat: callers may still raise PineTypeError("msg") with a
        # single positional string (e.g. compiler.types.unify). Promote it into
        # the message slot when no explicit message= was given.
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.expected = expected
        self.got = got
        self.expr_text = expr_text
        self.location = location
        self.rule = rule
        self.hint = hint
        if message is not None:
            text = message
        else:
            loc = (
                f" at {location[0]}:{location[1]}:{location[2]}"
                if location is not None
                else ""
            )
            rule_s = f" [{rule}]" if rule else ""
            text = (
                f"PineTypeError{rule_s}{loc}: expected {expected!r}, got {got!r}"
            )
            if expr_text:
                text += f"\n  in: {expr_text}"
            if hint:
                text += f"\n  hint: {hint}"
        super().__init__(text)


class PineUnsupportedBuiltinError(PineError):
    """The script references a builtin that the compiler does not yet emit.

    Carries the structured diagnostic shape D1 §5.1 specifies — ``builtin``
    names the qualified Pine identifier (e.g. ``"ta.ichimoku"``), and the
    optional ``suggested_alternative`` / ``tracking_url`` flow through into
    the REST error envelope per PRD §4.8. The C3 type checker still adds the
    name to ``CompiledModule.builtins_used`` even when raising this — so the
    wild-corpus coverage metric (PRD §3.4 L0.5) can attribute the shortfall.

    Example::

        raise PineUnsupportedBuiltinError(
            "ta.ichimoku",
            suggested_alternative="Implement via ta.donchian + ta.sma composition.",
            tracking_url="https://github.com/<repo>/issues?label=pine-builtin&q=ta.ichimoku",
        )
    """

    code: str = "PineUnsupportedBuiltinError"

    def __init__(
        self,
        builtin: str | None = None,
        *,
        suggested_alternative: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        self.builtin: str | None = builtin
        self.suggested_alternative: str | None = suggested_alternative
        # PineError class-level ``tracking_url`` is None; we shadow per-instance
        # so the REST envelope (D3 §4.1) and CLI both see the actual link.
        self.tracking_url: str | None = tracking_url
        if message is not None:
            text = message
        elif builtin is not None:
            suffix = ""
            if suggested_alternative:
                suffix += f"\n  alternative: {suggested_alternative}"
            if tracking_url:
                suffix += f"\n  tracking: {tracking_url}"
            text = f"Pine builtin {builtin!r} is not yet implemented{suffix}"
        else:
            text = "Unsupported Pine builtin (no structured detail attached)"
        super().__init__(text)


class PineUnsupportedFeatureError(PineCompileError):
    """A Pine source feature is recognised but not yet shipped.

    Originally introduced for the C7 v5→v6 auto-migration shim. The C3 type
    checker reuses it for typed-decl-in-body (PF002) and other deferred Pine
    constructs. ``tracking_url`` points at the GitHub label used to file new
    requests so the long-tail workstream stays addressable.

    The error code prefix ``PF`` ("Pine Feature") is reserved for this class
    so REST callers can branch on the prefix without parsing the message:
    ``PF001`` v4-or-earlier pragma, ``PF002`` typed decl in body /
    future-version pragma we won't speculate on, ``PF003`` v5 source uses a
    construct no V5_REWRITES entry handles.

    Example::

        raise PineUnsupportedFeatureError(
            "PF002 typed decl in body",
            tracking_url="https://github.com/<repo>/issues?label=pine-feature",
        )
    """

    code: str = "PineUnsupportedFeatureError"
    # Default class-level tracking URL is retained for the v5-migration use
    # case; instance attribute may override per-raise.
    tracking_url: str = (
        "https://github.com/OpenBB-finance/OpenBBTerminal/issues/"
        "?labels=pine-v5-migration"
    )

    def __init__(
        self,
        feature: str | None = None,
        *,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        self.feature: str | None = feature
        if tracking_url is not None:
            # Shadow the class-level default per-instance.
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        elif feature is not None:
            url = tracking_url or type(self).tracking_url
            trail = f"\n  tracking: {url}" if url else ""
            text = f"Pine feature {feature!r} is not yet supported{trail}"
        else:
            text = "Unsupported Pine feature (no structured detail attached)"
        super().__init__(text)


class PineCodegenError(PineCompileError):
    """Codegen produced invalid output (defense-in-depth; should be unreachable
    if D1 §3.3 allowlist gate is intact).

    Carries the structured diagnostic shape D1 §5.2 enumerates for ``CG###``:

    * ``rule`` — one of ``"CG001"`` (disallowed ast node type), ``"CG002"``
      (disallowed import-from module), ``"CG003"`` (disallowed top-level
      free name), or any future ``"CGNNN"`` the gate adds.
    * ``node_kind`` — short label for the offending construct, e.g.
      ``"ast.Subscript"`` or ``"ImportFrom('os')"``.
    * ``allowlist_member`` — the human-friendly description of what the
      violator would have had to be to pass the gate, so the operator sees
      both halves of the contract in one message.
    * ``tracking_url`` — GitHub label search URL for filing the underlying
      compiler bug (these errors are ALWAYS compiler bugs, never user
      errors, per D1 §3.5; a fresh CG### in production is a P0).

    Init signature mirrors the post-R2/R6/Wave-3A consolidation pattern
    (commits ``3c6bb0a81`` + ``d4b294da5`` + ``03b6b69ee``) — added
    preemptively rather than after the C5 review cycle since the pattern is
    now proven across PineDataValidationError + PineFMPUnreachableError +
    PineTypeError + PineUnsupportedBuiltinError + PineUnsupportedFeatureError.

    Backward compatible: pass a positional string OR ``message=`` to wrap a
    pre-stitched string (e.g. defensive raises that don't yet thread
    structured data through).

    Subclasses :class:`PineCompileError` (not the bare :class:`PineError`)
    so existing ``except PineCompileError`` handlers — including the REST
    error envelope mapper in D3 §4.1 — catch codegen failures uniformly with
    type-checker rejections. Codegen failures are still a compile-pipeline
    fault, not a runtime / data fault.

    Example::

        raise PineCodegenError(
            rule="CG001",
            node_kind="ast.Lambda",
            allowlist_member="any of NODE_TYPE_ALLOWLIST per D1 §3.2",
            tracking_url="https://github.com/<repo>/issues?label=pine-codegen",
        )
    """

    code: str = "PineCodegenError"

    def __init__(
        self,
        *args: object,
        rule: str | None = None,
        node_kind: str | None = None,
        allowlist_member: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        # Backwards-compat: callers may still raise ``PineCodegenError("msg")``
        # with a single positional string. Promote it into the message slot
        # when no explicit ``message=`` was given. Same pattern as
        # PineTypeError (post-R2/R6/Wave-3A).
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.rule = rule
        self.node_kind = node_kind
        self.allowlist_member = allowlist_member
        if tracking_url is not None:
            # Shadow the class-level default (PineError sets ``tracking_url``
            # to None on the class).
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        else:
            r = f"[{rule}] " if rule else ""
            kind = node_kind or "ast node"
            text = f"{r}codegen produced disallowed {kind}"
            if allowlist_member:
                text += f" (expected: {allowlist_member})"
            if tracking_url:
                text += f"\n  tracking: {tracking_url}"
        super().__init__(text)


class PineInternalCompilerError(PineCompileError):
    """A compiler invariant was violated — always a bug, never user-facing.

    D1 §5.2 reserves the ``IC###`` prefix for these. When one fires in
    production, page on-call: the compiler emitted output that contradicts
    its own contract (e.g. type-checked IR reached codegen with an
    unexpected node kind, an unregistered error code was raised, etc.).

    Structured init added in bead 0e9.5.8 C8. The ``invariant`` text
    describes what was violated ("error code raised but not registered");
    ``node_kind`` optionally names the offending IR / AST node so the
    on-call responder has enough context to start debugging without
    round-tripping through logs.

    Example::

        raise PineInternalCompilerError(
            rule="IC001",
            invariant="error code raised but not registered in ERROR_CODES",
            hint="add the code to openbb_pine/error_codes.py",
        )
    """

    code: str = "PineInternalCompilerError"

    def __init__(
        self,
        *args: object,
        rule: str | None = None,
        invariant: str | None = None,
        node_kind: str | None = None,
        hint: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.rule = rule
        self.invariant = invariant
        self.node_kind = node_kind
        self.hint = hint
        if tracking_url is not None:
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        else:
            r = f"[{rule}] " if rule else ""
            inv = invariant or "compiler invariant violated"
            text = f"{r}{inv}"
            if node_kind:
                text += f" (node: {node_kind})"
            if hint:
                text += f"\n  hint: {hint}"
        super().__init__(text)


# --- Provider / data errors (D2 territory) -------------------------------


class PineProviderError(PineError):
    """A non-FMP provider was requested (PRD section 13.8).

    Structured init added in bead 0e9.5.8 C8 — carries ``requested``,
    ``supported``, and ``tracking_url`` structured. Backwards-compat with
    positional-string raises retained (``provider_selection.py`` originally
    raised with a plain string + monkey-patched the fields on the instance
    after; now callers can pass them directly).

    Example::

        raise PineProviderError(
            requested="yfinance",
            supported=("fmp", "fmp_cached"),
            tracking_url="https://github.com/<repo>/issues/?label=pine-provider",
        )
    """

    code: str = "PineProviderError"

    def __init__(
        self,
        *args: object,
        requested: str | None = None,
        supported: tuple[str, ...] | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.requested = requested
        self.supported = supported
        if tracking_url is not None:
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        elif requested is not None:
            sup = f" (supported: {list(supported)})" if supported else ""
            trail = f"\n  tracking: {tracking_url}" if tracking_url else ""
            text = f"Provider {requested!r} is not supported{sup}{trail}"
        else:
            text = "Unsupported provider (no structured detail attached)"
        # Bypass any PineProviderError subclass init logic by going straight
        # to OpenBBError (subclasses call OpenBBError.__init__ directly if
        # they need to skip us).
        OpenBBError.__init__(self, text)


class PineFMPRequiredError(PineProviderError):
    """BYO mode without FMP key, and the script touched an FMP-only builtin.

    Structured init added in bead 0e9.5.8 C8 — carries ``builtin`` (the
    Pine identifier that requires FMP, e.g. ``"request.dividends"``) and
    ``mode`` (typically ``"byo_only"``). PRD §13.8's error-body shape
    surfaces both so callers see which builtin needs upgrading and why.

    Example::

        raise PineFMPRequiredError(
            builtin="request.security",
            mode="byo_only",
        )
    """

    code: str = "PineFMPRequiredError"

    def __init__(
        self,
        *args: object,
        builtin: str | None = None,
        mode: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.builtin = builtin
        self.mode = mode
        if tracking_url is not None:
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        elif builtin is not None:
            mode_s = f" (mode: {mode})" if mode else ""
            text = (
                f"Builtin {builtin!r} requires FMP but no FMP key is "
                f"configured{mode_s}"
            )
        else:
            text = "FMP required but not configured (no structured detail attached)"
        # Skip PineProviderError.__init__'s requested/supported rendering —
        # this class has its own structured fields.
        OpenBBError.__init__(self, text)


class PineFMPUnreachableError(PineProviderError):
    """All retry attempts to FMP / fmp_cached failed (PRD section 10 R13).

    Carries the per-attempt diagnostic state (provider, attempts, last_error,
    label) as structured attributes so the REST error envelope (D3 §4.1) and
    the CLI both surface the same information. Init signature matches D2 §7.1.

    Example::

        raise PineFMPUnreachableError(
            provider="fmp_cached",
            attempts=5,
            last_error=httpx_timeout_exc,
            label="historical price AAPL 1d",
        )
    """

    code: str = "PineFMPUnreachableError"

    def __init__(
        self,
        *,
        provider: str | None = None,
        attempts: int | None = None,
        last_error: BaseException | None = None,
        label: str | None = None,
        message: str | None = None,
    ) -> None:
        self.provider: str | None = provider
        self.attempts: int | None = attempts
        self.last_error: BaseException | None = last_error
        self.label: str | None = label
        if message is not None:
            text = message
        elif provider is not None and attempts is not None:
            lbl = f" (label={label!r})" if label else ""
            last = f"; last error: {last_error!r}" if last_error is not None else ""
            text = f"FMP provider {provider!r} unreachable after {attempts} attempt(s){lbl}{last}"
        else:
            text = "FMP provider unreachable (no structured detail attached)"
        # Skip PineProviderError.__init__ — this class predates the structured
        # init on the parent and has its own field set. Go straight to
        # OpenBBError so no rendering logic in the middle mangles our text.
        OpenBBError.__init__(self, text)


class PineDataResolverError(PineError):
    """A user-supplied ``data_resolver`` callable raised while fetching a
    secondary series (D5 §4.2 / §4.3 — Python-API BYO escape hatch).

    Runtime wraps the underlying exception so callers see a single
    Pine-typed error rather than an arbitrary user-callable failure mode.
    Preserves the original via ``__cause__`` (chained ``raise ... from``)
    and stores structured fields for the REST error envelope (D3 §4.1) and
    the CLI. This isn't a PineProviderError subclass because
    ``data_resolver`` is not a provider — it's a bring-your-own hook.

    Example::

        raise PineDataResolverError(
            symbol="MYPRIVATE",
            timeframe="1D",
            context_id="ctx_0",
        ) from original_exc
    """

    code: str = "PineDataResolverError"

    def __init__(
        self,
        *args: object,
        symbol: str | None = None,
        timeframe: str | None = None,
        context_id: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.symbol: str | None = symbol
        self.timeframe: str | None = timeframe
        self.context_id: str | None = context_id
        if tracking_url is not None:
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        else:
            ctx = f" (context_id={context_id!r})" if context_id else ""
            sym = f" symbol={symbol!r}" if symbol else ""
            tf = f" timeframe={timeframe!r}" if timeframe else ""
            text = f"user data_resolver failed{ctx}:{sym}{tf}"
        super().__init__(text)


class PineDataValidationError(PineError):
    """BYO DataFrame violated the section 3.1 schema.

    Carries the full defect list as a structured attribute so the REST error
    envelope (D3 section 4.1) and the CLI both surface every defect in one
    response, not first-error-wins. Init signature matches D2 section 7.1.

    Example::

        raise PineDataValidationError(
            defects=["missing column: volume", "index is not tz-aware"],
            context="symbol=PRIVATE_SYM",
        )
    """

    code: str = "PineDataValidationError"

    def __init__(
        self,
        defects: list[str] | None = None,
        *,
        context: str | None = None,
        message: str | None = None,
    ) -> None:
        # Type-guard: a `str` is iterable, so `list(str)` produces per-character
        # garbage. Catch the str-as-positional bug at the source rather than at
        # ``str(exc)`` time. Callers with a pre-stitched message MUST use the
        # ``message=`` kwarg explicitly.
        if isinstance(defects, str):
            raise TypeError(
                "PineDataValidationError(defects=...) must be list[str], not str. "
                "Use the `message=` keyword for a pre-stitched single-string error."
            )
        self.defects: list[str] = list(defects or [])
        self.context: str | None = context
        if message is not None:
            text = message
        else:
            ctx = f" (context: {context})" if context else ""
            joined = "; ".join(self.defects) if self.defects else "(no defects listed)"
            text = f"BYO data validation failed{ctx}: {joined}"
        super().__init__(text)


class PineCacheError(PineError):
    """Compile cache could not be read or written.

    Carries the structured diagnostic shape D1 §5 + PRD §4.8 specify for cache
    corruption / atomicity violations:

    * ``sha`` — the 64-char hex cache key of the offending entry, so operators
      can inspect / remove the corrupted directory without grepping logs.
    * ``defect`` — short label naming the corruption class, e.g.
      ``"missing meta.json"`` / ``"meta.json parse failed"`` /
      ``"os.replace failed"``. Machine-comparable so the REST envelope
      (D3 §4.1) can branch without regexing free text.
    * ``path`` — the on-disk :class:`pathlib.Path` of the offending file or
      directory, threaded through so the operator can act on it.

    Init signature mirrors the post-R2/R6/Wave-3A/Wave-4 consolidation pattern
    (commits ``3c6bb0a81`` + ``d4b294da5`` + ``03b6b69ee`` + ``41edda954``) —
    added preemptively rather than after the C6 review cycle since the pattern
    is now proven across PineDataValidationError + PineFMPUnreachableError +
    PineTypeError + PineUnsupportedBuiltinError + PineUnsupportedFeatureError +
    PineCodegenError.

    Backward compatible: pass a positional string OR ``message=`` to wrap a
    pre-stitched string. In practice C6's cache-corruption code path DOES NOT
    raise this — it logs a warning and degrades to a cache miss (corruption
    must never break compilation, per D1 §6). The structured init exists for
    the rarer atomicity failure paths (e.g. a mid-write ENOSPC that leaves
    tempfiles behind) where surfacing the defect is preferable to silence.

    Example::

        raise PineCacheError(
            sha="abcd1234...",
            defect="os.replace failed after tempfile write",
            path=cache_dir / sha[:2] / f"{sha}.py",
        )
    """

    code: str = "PineCacheError"

    def __init__(
        self,
        *args: object,
        sha: str | None = None,
        defect: str | None = None,
        path: Path | None = None,
        message: str | None = None,
    ) -> None:
        # Backwards-compat: callers may still raise ``PineCacheError("msg")``
        # with a single positional string. Promote it into the message slot
        # when no explicit ``message=`` was given. Same pattern as
        # PineCodegenError / PineTypeError.
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.sha: str | None = sha
        self.defect: str | None = defect
        self.path: Path | None = path
        if message is not None:
            text = message
        else:
            sha_s = f" (sha={sha[:12]}…)" if sha else ""
            path_s = f" at {path}" if path is not None else ""
            defect_s = defect or "cache access failed"
            text = f"PineCacheError{sha_s}: {defect_s}{path_s}"
        super().__init__(text)


# --- Runtime / execution errors (D2 territory) ---------------------------


class PineRuntimeError(PineError):
    """An error raised during execution of a compiled @pyne module."""

    code: str = "PineRuntimeError"


class PineStrategyNotYetImplementedError(PineError):
    """``/pine/strategies/run`` is scaffolded at M1, live at M2 (PRD section 3.2)."""

    code: str = "PineStrategyNotYetImplementedError"


class PineSecurityError(PineError):
    """A sandbox / security invariant was violated (PRD section 5 T1/T3).

    Structured init added in bead 0e9.5.8 C8. Carries ``rule`` (a ``SEC###``
    code — see :mod:`openbb_pine.error_codes`, currently ``SEC001`` for the
    T3 forbidden-import scan) and ``node_kind`` (short label for the
    offending construct — typically the AST node or module name that
    triggered).

    Example::

        raise PineSecurityError(
            rule="SEC001",
            node_kind="ImportFrom('subprocess')",
        )
    """

    code: str = "PineSecurityError"

    def __init__(
        self,
        *args: object,
        rule: str | None = None,
        node_kind: str | None = None,
        hint: str | None = None,
        tracking_url: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.rule = rule
        self.node_kind = node_kind
        self.hint = hint
        if tracking_url is not None:
            self.tracking_url = tracking_url
        if message is not None:
            text = message
        else:
            r = f"[{rule}] " if rule else ""
            kind = node_kind or "sandbox violation"
            text = f"{r}Pine sandbox violation: {kind}"
            if hint:
                text += f"\n  hint: {hint}"
        super().__init__(text)


class PineExecTimeoutError(PineRuntimeError):
    """A Pine script exceeded its wall-clock budget (PRD section 5.2 T2).

    Structured init added in bead 0e9.5.8 C8. Carries ``timeout_s`` (the
    budget), ``elapsed_s`` (how long the run actually took, if measurable),
    and ``script_hash`` (compiled-module identity for post-hoc lookup in
    the compile cache).

    Backwards-compat: the SIGALRM signal handler in ``runtime/limits.py``
    raises with a positional string; that call site keeps working. When
    calling from user code, prefer the structured form.

    Example::

        raise PineExecTimeoutError(
            timeout_s=5,
            elapsed_s=5.4,
            script_hash=compiled.sha,
        )
    """

    code: str = "PineExecTimeoutError"

    def __init__(
        self,
        *args: object,
        timeout_s: int | None = None,
        elapsed_s: float | None = None,
        script_hash: str | None = None,
        message: str | None = None,
    ) -> None:
        if args and message is None:
            if len(args) == 1 and isinstance(args[0], str):
                message = args[0]
            else:
                message = " ".join(str(a) for a in args)
        self.timeout_s = timeout_s
        self.elapsed_s = elapsed_s
        self.script_hash = script_hash
        if message is not None:
            text = message
        elif timeout_s is not None:
            elapsed_str = f" (elapsed {elapsed_s:.2f}s)" if elapsed_s else ""
            hash_s = f" [{script_hash[:12]}]" if script_hash else ""
            text = (
                f"Pine script{hash_s} exceeded {timeout_s}s wall-clock "
                f"budget{elapsed_str}"
            )
        else:
            text = "Pine script exceeded its wall-clock budget"
        super().__init__(text)


__all__ = [
    "Diagnostic",
    "PineError",
    "PineCompileError",
    "PineSyntaxError",
    "PineTypeError",
    "PineUnsupportedBuiltinError",
    "PineUnsupportedFeatureError",
    "PineCodegenError",
    "PineInternalCompilerError",
    "PineProviderError",
    "PineFMPRequiredError",
    "PineFMPUnreachableError",
    "PineDataResolverError",
    "PineDataValidationError",
    "PineCacheError",
    "PineRuntimeError",
    "PineStrategyNotYetImplementedError",
    "PineSecurityError",
    "PineExecTimeoutError",
]
