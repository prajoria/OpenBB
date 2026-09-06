# Project map — snapshot

**Do not treat this file as authoritative.** The live inventory is always:

```bash
ci/local-ci --list --json
```

This file is a periodically-refreshed snapshot for human browsing. When
the skill discovers projects at runtime it MUST use `--list --json`, not
this markdown.

## Current stacks

_As of the local-ci P5 skill wrapper landing (Refs #989):_

- **No production project stacks committed yet.**
  - P2 (#986) will add `ci/openbb/` (Python/nox stack — lint, unit,
    unit-cli, analysis tiers).
  - P3 (#987) will add the `mysql` tier + MySQL sidecar restored from
    `H:\DBBackup`.
  - P4 (#988) will add `ci/copilot-api/` (Bun stack — lint, test, build
    tiers).

Once those land, `ci/local-ci --list` will enumerate them; this file is
a hint, not the source of truth.

## Fixture

- `ci/_fixture/local-ci.yml` — hidden from `--list` (leading underscore).
  Used only by the CLI's unit tests to exercise schema validation and
  dry-run pipeline without a real Docker stack.
