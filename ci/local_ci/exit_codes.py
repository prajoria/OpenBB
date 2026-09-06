"""Exit codes shared across the CLI (spec §5.2)."""

from __future__ import annotations

# Business outcome
EXIT_OK = 0             # all requested tiers passed
EXIT_TIER_FAILED = 1    # >=1 tier failed (test/lint failure)

# Caller error
EXIT_CLI_MISUSE = 2     # bad args, unknown project/tier
EXIT_CONFIG_ERROR = 3   # YAML invalid, compose file missing, schema violation
EXIT_DOCKER_ERROR = 4   # daemon down, build failure, sidecar unhealthy
EXIT_INIT_ERROR = 5     # sidecar init failed (e.g. DBBACKUP_DIR dump missing)
