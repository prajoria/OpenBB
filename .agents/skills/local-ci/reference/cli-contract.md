# local-ci CLI ↔ skill boundary contract

This document pins the exact interface the `local-ci` skill relies on. If
the CLI ever breaks any of the contracts below, the skill breaks too —
so any change to `ci/local_ci/cli.py` or the JSON schemas that alters
this surface is a breaking change and must bump the report schema tag
(`local-ci/v1` → `local-ci/v2`).

## Schemas

- **Config schema**: [`ci/local_ci/schema/local-ci.schema.json`](../../../ci/local_ci/schema/local-ci.schema.json)
  — every `ci/<project>/local-ci.yml` validates against this on load.
- **Report schema**: [`ci/local_ci/schema/report.schema.json`](../../../ci/local_ci/schema/report.schema.json)
  — every `--json` payload the skill parses validates against this.

## Discovery contract (`--list --json`)

The skill relies on:

```json
{
  "schema": "local-ci/v1",
  "projects": [
    {
      "project": "<id>",
      "description": "...",
      "yaml_path": "...",
      "default_tiers": ["lint", "unit"],
      "tiers": [
        {
          "name": "<tier>",
          "description": "...",
          "command": "<shell command>",
          "requires_services": ["<sidecar-name>", ...]
        }
      ],
      "sidecars": ["<sidecar-name>", ...]
    }
  ]
}
```

The skill uses:

- `projects[*].project` — for user disambiguation
- `projects[*].tiers[*].name` — for resolving user-named tiers
- `projects[*].tiers[*].requires_services` — to mention sidecar bring-up

## Run contract (`<project> [tiers...] --json`)

Stream layout on stdout:

```
<human-readable log lines from ComposeRunner>
<blank line>
local-ci: <project> — <STATUS>
  [<STATUS>] <tier1>       <duration>s  exit=<n>
  [<STATUS>] <tier2>       <duration>s  exit=<n>
  sidecar <name>: <state>[ (init triggered)]

---LOCAL-CI-JSON---
{
  "schema": "local-ci/v1",
  "project": "<id>",
  "tiers": [
    {"name": "<tier>", "status": "pass|fail|skipped",
     "duration_s": <float>, "exit_code": <int>,
     "first_failure_excerpt": "<optional string, only on fail>"}
  ],
  "sidecars": [
    {"name": "<sidecar>", "brought_up": true|false,
     "healthy": true|false, "init_triggered": true|false,
     "error": "<optional string>"}
  ],
  "overall_status": "pass|fail",
  "overall_exit_code": 0|1
}
```

The `---LOCAL-CI-JSON---` marker MUST appear on its own line. Everything
below it is a single valid JSON object matching `report.schema.json`.

## Exit codes (fixed)

| Code | Constant | Meaning |
|---|---|---|
| 0 | `EXIT_OK` | All tiers passed |
| 1 | `EXIT_TIER_FAILED` | ≥1 tier failed |
| 2 | `EXIT_CLI_MISUSE` | Bad args, unknown project/tier |
| 3 | `EXIT_CONFIG_ERROR` | YAML invalid, compose file missing |
| 4 | `EXIT_DOCKER_ERROR` | Daemon down, build/pull failure, sidecar unhealthy |
| 5 | `EXIT_INIT_ERROR` | Sidecar init preflight failed (missing dump, etc.) |

The `overall_exit_code` field in the JSON payload mirrors the process
exit code for codes 0 and 1. For codes 2–5 the process exits before
emitting JSON, so the skill must handle missing-JSON as "CLI aborted
before summary" and fall back to the process exit code + stderr.

## `--dry-run`

`--dry-run` prints the plan (compose invocations + tier argv) and exits
0 with no side effects. When the user requests dry-run the skill:

- Skips `--json`.
- Prints the CLI's plan verbatim.
- Does NOT try to parse a JSON block (none is emitted).

## Backward compatibility

- Field additions to the report JSON are allowed within `local-ci/v1`.
- Field removals or renames require bumping to `local-ci/v2` and the
  skill must handle both tags for a deprecation window.
- Exit-code meanings are fixed for the life of `v1`.
