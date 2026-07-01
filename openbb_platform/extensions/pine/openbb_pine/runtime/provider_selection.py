"""Provider precedence for the Pine runtime.

Implements D2 section 4 + PRD section 13.8. Single source of truth for which
OpenBB provider ``FMPOHLCVProvider`` (D2 section 2) and the doctor CLI
(D2 section 8.3 / P4) hand to ``obb.<asset>.price.historical``.

Order of resolution:

1. If the caller passed ``"fmp"`` or ``"fmp_cached"`` explicitly, return it
   verbatim. (Even if ``openbb-fmp-cached`` is not installed -- the downstream
   ``obb`` call will surface the real error after the FMP retry budget.)
2. If the caller passed ``None`` and a user-settings preference exists, honor
   that preference. Non-FMP preferences fail fast (PRD section 13.8 rationale:
   silently overriding the user's deliberate setting is worse than a structured
   error pointing at the FMP-only constraint).
3. Otherwise prefer ``"fmp_cached"`` when the ``openbb_fmp_cached`` package is
   importable, falling back to ``"fmp"``.
4. Any other ``requested`` value raises ``PineProviderError`` with the section
   13.8 message shape (supported tuple + tracking URL).
"""

from __future__ import annotations

import importlib.util
from typing import Any, Literal

from openbb_pine.errors import PineProviderError

ProviderName = Literal["fmp", "fmp_cached"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("fmp", "fmp_cached")

# Tracking issue for the FMP-only constraint, per D2 section 7.2 / PRD section 13.8.
TRACKING_URL = (
    "https://github.com/prajoria/OpenBB/issues?"
    "q=is%3Aissue+label%3Aproject%3Apine+multi-provider"
)

# Normalized key (``Defaults.validate_before`` strips a leading ``/`` and
# replaces ``/`` with ``.``, so the canonical form here is dotted).
_PREF_COMMAND_KEY = "equity.price.historical"


def _read_user_preference(settings: Any | None) -> str | None:
    """Return the ``provider`` preference from user settings, if set.

    ``Defaults.validate_before`` wraps a string provider into a single-element
    list, so callers should normally see a list -- but defensively unwrap a
    bare string too.
    """
    if settings is None:
        return None
    try:
        commands = settings.defaults.commands
    except AttributeError:
        return None
    entry = commands.get(_PREF_COMMAND_KEY) if isinstance(commands, dict) else None
    if not entry:
        return None
    provider = entry.get("provider") if isinstance(entry, dict) else None
    if isinstance(provider, list) and provider:
        return str(provider[0])
    if isinstance(provider, str):
        return provider
    return None


def _raise_non_fmp(requested: str) -> None:
    """Raise ``PineProviderError`` with the PRD section 13.8 message shape.

    Uses the structured init (added by bead 0e9.5.8 C8) so the ``requested``,
    ``supported``, and ``tracking_url`` fields are populated at construction
    time — no more post-hoc monkey-patching on the exception instance.
    """
    raise PineProviderError(
        requested=requested,
        supported=SUPPORTED_PROVIDERS,
        tracking_url=TRACKING_URL,
    )


def resolve_provider(
    requested: str | None,
    *,
    settings: Any | None = None,
) -> ProviderName:
    """Resolve which FMP-family provider to hand to OpenBB.

    See module docstring for the full precedence ladder. Returns ``"fmp"`` or
    ``"fmp_cached"``; raises ``PineProviderError`` for any other value.
    """
    # 1. Explicit caller request wins, after validation.
    if requested is not None:
        if requested in SUPPORTED_PROVIDERS:
            return requested  # type: ignore[return-value]
        _raise_non_fmp(requested)

    # 2. User-settings preference, if set, must also be in SUPPORTED_PROVIDERS.
    preference = _read_user_preference(settings)
    if preference is not None:
        if preference in SUPPORTED_PROVIDERS:
            return preference  # type: ignore[return-value]
        _raise_non_fmp(preference)

    # 3. Default precedence: fmp_cached if installed, else fmp.
    if importlib.util.find_spec("openbb_fmp_cached") is not None:
        return "fmp_cached"
    return "fmp"


__all__ = ["resolve_provider", "ProviderName", "SUPPORTED_PROVIDERS", "TRACKING_URL"]
