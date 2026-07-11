"""Provider-side Pine errors (STAY list post-split — bead ``OpenBBTechnical-3cf`` / E0.1).

Post-split, this module owns the *provider* + *BYO data* error classes that
never migrate to ``pyne_compiler`` in E2:

* :class:`PineProviderError` — non-FMP provider requested (PRD §13.8).
* :class:`PineFMPRequiredError` — BYO-only mode hit an FMP-required builtin.
* :class:`PineFMPUnreachableError` — retries exhausted against FMP.
* :class:`PineDataValidationError` — BYO DataFrame violated the schema.

**Backwards-compat shim (one release).** The MOVE-list (compiler + runtime)
errors now live in :mod:`openbb_pine.compiler_errors`. To keep existing
``from openbb_pine.errors import PineSyntaxError`` (and every other
compiler/runtime symbol) working without lock-step edits, we re-export every
MOVE-list symbol below via ``noqa: F401``. The shim is deliberately narrow:

* It is a **pure re-export** (``is`` identity holds — tests assert this).
* It carries every symbol that used to live in ``errors.py`` before the
  split, so no downstream caller sees a ``NameError``.
* MOVE-list symbols are intentionally **excluded from** ``__all__`` so
  ``from openbb_pine.errors import *`` only pulls in STAY symbols. This
  nudges wildcard-import callers to the new home
  (``from pyne_compiler.errors.base import PineSyntaxError``) without
  breaking explicit imports through the shim (PR #351 review).
* It is scheduled for removal in the release after Pine extraction ships
  (see Pine Extraction Design §13.5 in
  ``docs/superpowers/specs/2026-07-06-pine-extraction-to-pynecore-design.md``).

Every class subclasses ``openbb_core.app.model.abstract.error.OpenBBError`` so
the platform's standard error middleware can intercept and serialize them
uniformly. Each class carries a ``code`` class attribute matching its name,
used by the REST error envelope (D3 section 4.1).
"""

from __future__ import annotations

from openbb_core.app.model.abstract.error import OpenBBError

# One-release compatibility shim: MOVE-list classes now live in compiler_errors.py.
# Downstream imports like `from openbb_pine.errors import PineSyntaxError` keep working.
# Remove this re-export block in the release after Pine extraction ships.
from pyne_compiler.errors.base import (  # noqa: F401
    Diagnostic,
    PineCacheError,
    PineCodegenError,
    PineCompileError,
    PineDataResolverError,
    PineError,
    PineExecTimeoutError,
    PineInternalCompilerError,
    PineRuntimeError,
    PineSecurityContextNotFoundError,
    PineSecurityError,
    PineStrategyNotYetImplementedError,
    PineSyntaxError,
    PineTypeError,
    PineUnsupportedBuiltinError,
    PineUnsupportedFeatureError,
)


# ---------------------------------------------------------------------------
# STAY list — provider / BYO-data errors (D2 territory).
# These classes do not cross the E2 extraction boundary; they remain in
# openbb_pine because they describe openbb-fork provider concerns.
# ---------------------------------------------------------------------------


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


__all__ = [
    # STAY-list (provider-side) — new-canonical home is this module.
    # MOVE-list symbols (PineSyntaxError, PineTypeError, Diagnostic, …) are
    # deliberately excluded so that `from openbb_pine.errors import *` only
    # pulls in STAY symbols. This nudges wildcard-import callers toward the
    # new canonical home (`from pyne_compiler.errors.base import …`) while
    # explicit `from openbb_pine.errors import PineSyntaxError` still works
    # via the module-level re-exports above for the one-release shim window.
    # See PR #351 review + Pine Extraction Design §13.5 (bead OpenBBTechnical-3cf).
    "PineProviderError",
    "PineFMPRequiredError",
    "PineFMPUnreachableError",
    "PineDataValidationError",
]
