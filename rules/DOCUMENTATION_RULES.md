# Documentation Organization Rules

> **Purpose:** Defines where each kind of project document lives so that
> requirements, specifications, and designs are never mixed. Follow these
> when creating or moving any document under `docs/`.

---

## 1. Top-level split: `specs/` vs `designs/`

| Document kind | Goes in | Answers |
|---|---|---|
| Product Requirements Document (PRD) | `docs/Specs/` | **Why** + **what** the product must do |
| Functional specification | `docs/Specs/` | **What** the system does (behavior, I/O, acceptance) |
| Requirements (functional & non-functional) | `docs/Specs/` | **What** constraints must hold |
| Proposals / RFCs (pre-approval) | `docs/Specs/` | **What** is being proposed |
| Technical / engineering design | `docs/designs/` | **How** it will be built |
| Architecture / component design | `docs/designs/` | **How** the pieces fit |
| API / data-model / interface design | `docs/designs/` | **How** contracts are shaped |

**Rule of thumb:** if it describes *what/why* (the problem, behavior,
acceptance), it is a **spec**. If it describes *how* (implementation,
structure, contracts), it is a **design**.

---

## 2. Logical sub-folder organization

Organize both `Specs/` and `designs/` by **feature / subsystem**, not by date
or author. Each multi-component feature gets its own sub-folder.

```
docs/
  Specs/
    <feature>-PRD.md                  # single-file spec
    <feature>-Proposal.md
    <feature>/                        # multi-file spec set
      requirements.md
      functional-spec.md
      acceptance-criteria.md
  designs/
    <Feature>-Design.md               # index / overview design doc
    <feature>-design/                 # per-component design files
      NN-<component>.md               # zero-padded ordering prefix
```

- Use a **zero-padded numeric prefix** (`01-`, `02-`, …) on per-component
  design files so they sort in implementation/dependency order.
- The feature's **index design doc** (`<Feature>-Design.md`) lives directly in
  `designs/` and links to its `<feature>-design/` sub-folder.
- Keep `kebab-case` for folder names; match the feature slug between the
  spec and the design (e.g. `Backtesting-Engine-PRD.md` ↔
  `Backtesting-Engine-Design.md` ↔ `backtest-design/`).

---

## 3. Cross-linking

- A design index doc **must** link back to its source spec/PRD
  (`[PRD](../Specs/<feature>-PRD.md)`).
- A spec **may** link forward to its design once the design exists.
- Each per-component design file ends with an **Acceptance mapping** table
  tracing back to the spec's acceptance criteria (or the tracking issue).

---

## 4. What does NOT go here

- Session notes, planning scratch, and evolving research → `docs/planning/`.
- Tool/script operational docs → `docs/Tools/`.
- Platform/usage docs → `docs/OpenBBPlatform/`.
- Do not place implementation code, exports, or generated artifacts under
  `Specs/` or `designs/`.

---

## 5. PII & secrets

- These docs are committed: never include real account numbers, owner names,
  paths containing usernames, DB passwords, or API keys. Use placeholders
  (`<OWNER>`, `<DB_PASSWORD>`, `<ACCOUNT_NUMBER>`).
