"""Brinson-Fachler test-data generator + reference oracle (#935).

This package ships the *testing-enablement* side of Brinson-Fachler
attribution:

- :mod:`.oracle` — a literal transcription of the single-period BF
  formulas. Trusted by construction (obviously-correct-by-inspection).
- :mod:`.generator` — deterministic synthetic input cases (Dirichlet
  weights that sum to 1, normal returns) with edge-case flags.
- :mod:`.fixtures` — golden JSON fixtures the attribution engine
  (#559) asserts against without importing this package at test time.

The attribution engine itself is out of scope here (that's #559).
See docs/superpowers/specs/2026-07-20-brinson-synthetic-test-data-generator.md
for the full spec.
"""

from openbb_portfolio_intel.analytics.brinson.generator import (
    BrinsonCase,
    make_case,
)
from openbb_portfolio_intel.analytics.brinson.oracle import (
    BrinsonEffects,
    brinson_reference,
)

__all__ = [
    "BrinsonCase",
    "BrinsonEffects",
    "brinson_reference",
    "make_case",
]
