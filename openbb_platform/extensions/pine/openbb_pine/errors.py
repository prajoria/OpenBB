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
    """A static type check failed during compilation."""

    code: str = "PineTypeError"


class PineUnsupportedBuiltinError(PineError):
    """The script references a builtin that the compiler does not yet emit."""

    code: str = "PineUnsupportedBuiltinError"


class PineCodegenError(PineError):
    """Codegen produced invalid output (defense-in-depth; should be unreachable)."""

    code: str = "PineCodegenError"


# --- Provider / data errors (D2 territory) -------------------------------


class PineProviderError(PineError):
    """A non-FMP provider was requested (PRD section 13.8)."""

    code: str = "PineProviderError"


class PineFMPRequiredError(PineProviderError):
    """BYO mode without FMP key, and the script touched an FMP-only builtin."""

    code: str = "PineFMPRequiredError"


class PineFMPUnreachableError(PineProviderError):
    """All retry attempts to FMP / fmp_cached failed (PRD section 10 R13)."""

    code: str = "PineFMPUnreachableError"


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
