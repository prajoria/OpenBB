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
    """BYO DataFrame violated the section 3.1 schema."""

    code: str = "PineDataValidationError"


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
