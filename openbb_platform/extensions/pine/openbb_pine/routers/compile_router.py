"""Compile sub-router: ``POST /pine/compile`` (D3 §4.2).

Translates Pine source to Python *without executing*. Per PRD §13.4 — the
explicit "view transpiled Python" affordance for users debugging compile
output.

M1 reality: the codegen pipeline (C5, bead 0e9.5.5) has not landed, so
the response's ``python_source`` field carries a stub message that says
so. We DO run the lexer (C1, Wave 1A) + parser (C2, Wave 2A) here because
those are shipped — they catch syntax errors with the same hints the
runtime will surface once it lands, and they recover the
``//@version=`` integer for the typed response. The parse tree itself is
discarded; this endpoint is the user's compile-time error surface, not a
public IR dump.

If a sibling C3 type checker becomes importable later, the endpoint
opportunistically uses it to populate ``builtins_used``. The
import-or-skip pattern means the surface tightens automatically as Wave 3
beads land — no second deploy required.
"""

from __future__ import annotations

import hashlib
from importlib import import_module
from typing import Any

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import Field
from typing_extensions import Annotated

from openbb_pine import __version__ as _pine_version
from openbb_pine.errors import PineSyntaxError  # noqa: F401  - re-exported error class
from openbb_pine.routers._models import PineCompileRequest, PineCompileResponse

router = Router(
    prefix="",
    description="Translate Pine source to Python without executing it (PRD §13.4).",
)


# Module-level stub message for the not-yet-compiled state. Constant
# rather than an f-string in the command body so tests can pin the exact
# wording (and so a future C5 lander only has to delete one file's
# constant rather than chase string literals).
_STUB_PYTHON_SOURCE = (
    "# PineComp not yet implemented (C5 bead 0e9.5.5 — Phase 1 in flight).\n"
    "# Source lexed + parsed successfully; codegen lands in a sibling wave.\n"
    "# Until then, use /pine/compile to validate syntax and /pine/run will\n"
    "# return 503 with a structured pointer to the same tracking bead.\n"
)


def _blake2b_sha(source: str, pine_version: int) -> str:
    """Cache-key digest matching the D1 §6 sketch (source + version)."""
    h = hashlib.blake2b(digest_size=16)
    h.update(source.encode("utf-8"))
    h.update(b"|")
    h.update(str(pine_version).encode("ascii"))
    h.update(b"|")
    h.update(_pine_version.encode("ascii"))
    return h.hexdigest()


def _detect_version_pragma(source: str) -> int | None:
    """Pull the ``//@version=N`` integer out of the source's first line.

    Returns None if no pragma is present — the caller's ``target_version``
    is the fallback. We do not run the lexer just to find this; a string
    inspection of the first line is enough and avoids redundant tokenization
    when the caller already knows.
    """
    first_line = source.split("\n", 1)[0].strip()
    prefix = "//@version="
    if first_line.startswith(prefix):
        digits = first_line[len(prefix):]
        # Stop at first non-digit (handles trailing whitespace / comments).
        n = 0
        while n < len(digits) and digits[n].isdigit():
            n += 1
        if n > 0:
            try:
                return int(digits[:n])
            except ValueError:  # pragma: no cover - defensive
                return None
    return None


def _maybe_typecheck_builtins(parsed_program: Any) -> list[str]:
    """Opportunistically run C3 type-checker if importable; return builtins_used.

    Wave-3 C3 is a sibling subagent in flight. We import-or-skip rather
    than hard-depend so a not-yet-merged C3 doesn't break this router.
    The expected entry point is ``openbb_pine.compiler.checker.check`` ->
    returns an object exposing ``.builtins_used`` (frozenset[str]); if
    the surface differs we silently fall back to [].
    """
    try:
        checker_mod = import_module("openbb_pine.compiler.checker")
    except ImportError:
        return []
    check_fn = getattr(checker_mod, "check", None)
    if check_fn is None:
        return []
    try:
        result = check_fn(parsed_program)
    except Exception:  # noqa: BLE001 - opportunistic; C3's errors should not break /compile
        return []
    builtins = getattr(result, "builtins_used", None)
    if builtins is None:
        return []
    try:
        return sorted(str(b) for b in builtins)
    except TypeError:  # pragma: no cover - defensive
        return []


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Compile a v6 indicator source (codegen returns a stub at M1).",
            code=[
                'src = """//@version=6\\nindicator(\\"BB\\")\\nplot(close)"""',
                "obb.pine.compile(source=src)",
            ],
        ),
    ],
)
def compile(  # noqa: A001 - public name is the API contract
    source: Annotated[str, Field(min_length=1, description="Pine v5 or v6 source.")],
    target_version: Annotated[int, Field(ge=5, le=6, description="Pine version (5 or 6).")] = 6,
) -> OBBject[PineCompileResponse]:
    """Translate Pine source to Python without executing it.

    Lexes + parses ``source`` via the Wave-1A / Wave-2A pipeline; on
    success returns a :class:`PineCompileResponse` whose ``python_source``
    is a stub message pointing at the codegen bead (C5, 0e9.5.5). On
    syntax/parse failure the platform middleware serializes the raised
    :class:`PineSyntaxError` to the §4.1 error envelope.

    Parameters
    ----------
    source : str
        Pine source text. Detected ``//@version=`` pragma overrides
        ``target_version`` when present.
    target_version : int
        Pine version (5 or 6). Used as the parser dispatch when the
        source has no ``//@version=`` pragma.

    Returns
    -------
    OBBject[PineCompileResponse]
        Typed response per D3 §4.2.
    """
    # Heavy imports lazy: parser pulls lark (heavy) — keep import-time of
    # the router module itself light per PRD §16.5.
    from openbb_pine.compiler.lexer import tokenize  # noqa: PLC0415
    from openbb_pine.compiler.parser import parse  # noqa: PLC0415

    pragma_version = _detect_version_pragma(source)
    parser_version = pragma_version if pragma_version in (5, 6) else target_version

    # Lex + parse. Errors propagate (PineSyntaxError) and the middleware
    # serializes them to the §4.1 error envelope.
    tokens = tokenize(source)
    program = parse(tokens, pine_version=parser_version)

    # `program.version` is the parser's final integer (pragma if found,
    # else parser_version). The response field carries the detected pragma
    # for downstream tooling that wants the "what the user wrote" view.
    detected_version: int = int(program.version)

    builtins_used = _maybe_typecheck_builtins(program)

    payload = PineCompileResponse(
        python_source=_STUB_PYTHON_SOURCE,
        sha=_blake2b_sha(source, detected_version),
        pine_version=detected_version,
        compiler_version=_pine_version,
        builtins_used=builtins_used,
        warnings=[],
    )
    return OBBject(results=payload)
