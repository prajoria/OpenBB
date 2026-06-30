"""Shared Pine error hierarchy.

Owned here per D3 section 4.7 (post-D1/D2/D3 cross-doc consolidation, commit
``af08128d3``): runtime and compiler modules import from this single module
rather than defining their own ``PineError`` roots. This avoids the
three-``PineError``-classes-with-different-bases bug the cross-doc reviewer
flagged.

Every class subclasses ``openbb_core.app.model.abstract.error.OpenBBError`` so
the platform's standard error middleware can intercept and serialize them
uniformly. Each class carries a ``code`` class attribute matching its name,
used by the REST error envelope (D3 section 4.1).
"""

from __future__ import annotations

from openbb_core.app.model.abstract.error import OpenBBError


class PineError(OpenBBError):
    """Root for every Pine-extension error."""

    code: str = "PineError"
    tracking_url: str | None = None


# --- Compiler-side errors (D1 territory) ---------------------------------


class PineCompileError(PineError):
    """A compile-time failure in the Pine -> Python translator."""

    code: str = "PineCompileError"


class PineSyntaxError(PineCompileError):
    """The Pine source did not parse."""

    code: str = "PineSyntaxError"


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


# --- Provider / data errors (D2 territory) -------------------------------


class PineProviderError(PineError):
    """A non-FMP provider was requested (PRD section 13.8)."""

    code: str = "PineProviderError"


class PineFMPRequiredError(PineProviderError):
    """BYO mode without FMP key, and the script touched an FMP-only builtin."""

    code: str = "PineFMPRequiredError"


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
    """Compile cache could not be read or written."""

    code: str = "PineCacheError"


# --- Runtime / execution errors (D2 territory) ---------------------------


class PineRuntimeError(PineError):
    """An error raised during execution of a compiled @pyne module."""

    code: str = "PineRuntimeError"


class PineStrategyNotYetImplementedError(PineError):
    """``/pine/strategies/run`` is scaffolded at M1, live at M2 (PRD section 3.2)."""

    code: str = "PineStrategyNotYetImplementedError"


class PineSecurityError(PineError):
    """A sandbox / security invariant was violated (PRD section 5 T1/T3)."""

    code: str = "PineSecurityError"


class PineExecTimeoutError(PineRuntimeError):
    """A Pine script exceeded its wall-clock budget (PRD section 5.2 T2)."""

    code: str = "PineExecTimeoutError"


__all__ = [
    "PineError",
    "PineCompileError",
    "PineSyntaxError",
    "PineTypeError",
    "PineUnsupportedBuiltinError",
    "PineUnsupportedFeatureError",
    "PineCodegenError",
    "PineProviderError",
    "PineFMPRequiredError",
    "PineFMPUnreachableError",
    "PineDataValidationError",
    "PineCacheError",
    "PineRuntimeError",
    "PineStrategyNotYetImplementedError",
    "PineSecurityError",
    "PineExecTimeoutError",
]
