---
applyTo: "docs/**"
---

# Documentation Placement Rules

Canonical reference: [rules/DOCUMENTATION_RULES.md](../../rules/DOCUMENTATION_RULES.md)

## Where each document goes

- **Specs** (`docs/Specs/`): PRDs, functional specifications, requirements
  (functional & non-functional), proposals/RFCs. These describe **what/why**.
- **Designs** (`docs/designs/`): technical/engineering, architecture,
  component, and API/interface designs. These describe **how**.

If unsure: *what/why → Specs*, *how → designs*.

## Organization

- Organize by **feature/subsystem**, not by date or author.
- Multi-component features get a sub-folder; per-component design files use a
  zero-padded numeric prefix (`01-`, `02-`, …) for dependency ordering.
- The feature index design doc (`<Feature>-Design.md`) sits in `designs/` and
  links its `<feature>-design/` sub-folder and back to the source PRD/spec.
- Keep `kebab-case` folder names; match the slug across spec ↔ design.

## Excluded from Specs/designs

- Session/planning notes → `docs/planning/`
- Tool/script docs → `docs/Tools/`
- No code, exports, or generated artifacts in `Specs/` or `designs/`.
