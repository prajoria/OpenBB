"""Docker Compose orchestration for local-ci.

Turns ProjectConfig + a tier list into concrete `docker compose` invocations.
Handles sidecar bring-up ordering, `--fresh` volume drop, and sidecar init
handlers (currently: mysql_restore).

Spec: docs/Specs/Local-CI-Skill-Spec.md §5.1, §10.1
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from local_ci.config import ProjectConfig, Sidecar, Tier
from local_ci.exit_codes import EXIT_DOCKER_ERROR, EXIT_INIT_ERROR


class InitError(Exception):
    """Sidecar init handler failed (e.g. DBBACKUP_DIR dump missing)."""

    exit_code = EXIT_INIT_ERROR


class DockerError(Exception):
    """Docker daemon / compose error (down, build failure, unhealthy)."""

    exit_code = EXIT_DOCKER_ERROR


@dataclass
class TierResult:
    name: str
    status: str  # "pass" | "fail" | "skipped"
    duration_s: float
    exit_code: int
    first_failure_excerpt: str = ""


@dataclass
class SidecarResult:
    name: str
    brought_up: bool
    healthy: bool = False
    # NB: this is TRIGGERED (volume dropped so init hook will re-fire on next
    # boot), not VERIFIED (we didn't peek inside the container to confirm the
    # SQL replayed). Overclaiming here would mask restore failures.
    init_triggered: bool = False
    error: str = ""


class ComposeRunner:
    """Wraps `docker compose` for one ProjectConfig.

    All external process calls funnel through here so `--dry-run` in cli.py
    can substitute a NullRunner that records the same argv without executing.
    """

    def __init__(self, cfg: ProjectConfig, *, verbose: bool = False) -> None:
        self.cfg = cfg
        self.verbose = verbose
        self._compose_argv_base = [
            "docker",
            "compose",
            "-f",
            str(cfg.compose.file),
        ]
        env_file_rel = cfg.compose.env_file
        if env_file_rel:
            env_file_abs = cfg.project_dir / env_file_rel
            if env_file_abs.is_file():
                self._compose_argv_base.extend(["--env-file", str(env_file_abs)])

    # ------------------------------------------------------------------
    # Public API (called by cli.py)
    # ------------------------------------------------------------------

    def build_tier_argv(self, tier: Tier) -> list[str]:
        """The exact argv that will be run for this tier. Used by --dry-run."""
        return [
            *self._compose_argv_base,
            "exec",
            "-T",
            self.cfg.compose.runner_service,
            "sh",
            "-c",
            tier.command,
        ]

    def build_sidecar_up_argv(self, services: list[str]) -> list[str]:
        return [*self._compose_argv_base, "up", "-d", *services]

    def build_runner_up_argv(self) -> list[str]:
        return [
            *self._compose_argv_base,
            "up",
            "-d",
            self.cfg.compose.runner_service,
        ]

    def build_down_argv(self) -> list[str]:
        return [*self._compose_argv_base, "down"]

    def build_volume_rm_argv(self, volume: str) -> list[str]:
        return ["docker", "volume", "rm", "-f", volume]

    def build_pull_argv(self) -> list[str]:
        return [*self._compose_argv_base, "pull"]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        """Run a compose command; stream stderr in verbose, capture stdout."""
        result = subprocess.run(
            argv,
            check=False,
            capture_output=not self.verbose,
            text=True,
        )
        if check and result.returncode != 0:
            stderr = result.stderr if not self.verbose else "(streamed)"
            raise DockerError(
                f"command failed ({result.returncode}): {' '.join(argv)}\n{stderr}"
            )
        return result

    def exec_tier(self, tier: Tier) -> TierResult:
        """docker compose exec runner sh -c <tier.command>.

        Streams stdout+stderr live (so devs watch progress) AND tees the
        combined stream to a bounded ring buffer so we can surface a
        first-failure excerpt in the JSON report. Without this the report's
        `first_failure_excerpt` is silently always empty — the schema field
        implies capture, so the runtime must actually capture (MED finding
        #3 from PR #1009 review).
        """
        argv = self.build_tier_argv(tier)
        started = time.monotonic()
        # Use Popen so we can tee. subprocess.run with capture=True would
        # buffer everything until exit — bad UX for long tiers.
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        tail: list[str] = []
        max_tail_lines = 200
        assert proc.stdout is not None  # for type-checkers; PIPE guarantees this
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line.rstrip("\n"))
            if len(tail) > max_tail_lines:
                tail.pop(0)
        proc.wait()
        elapsed = time.monotonic() - started
        status = "pass" if proc.returncode == 0 else "fail"
        excerpt = ""
        if status == "fail":
            # Prefer the first line matching a common failure marker; fall
            # back to last ~40 lines so the JSON consumer always gets *some*
            # signal on failure rather than an empty string.
            for line in tail:
                if any(
                    marker in line
                    for marker in ("FAILED ", "Traceback", "ERROR ", "error:", "assert ")
                ):
                    excerpt = line
                    break
            if not excerpt:
                excerpt = "\n".join(tail[-40:])
        return TierResult(
            name=tier.name,
            status=status,
            duration_s=round(elapsed, 2),
            exit_code=proc.returncode,
            first_failure_excerpt=excerpt,
        )

    def ensure_sidecars(
        self,
        sidecars: list[Sidecar],
        *,
        fresh: bool = False,
        dbbackup_dir: str | None = None,
    ) -> list[SidecarResult]:
        """Bring up each sidecar, running any init handlers on --fresh boot.

        Returns per-sidecar SidecarResult. Raises InitError / DockerError.
        """
        results: list[SidecarResult] = []
        if not sidecars:
            return results

        # 1. Drop init volumes on --fresh, before up.
        for sc in sidecars:
            if fresh and sc.init and sc.init.get("volume"):
                vol = sc.init["volume"]
                # `volume rm -f` is idempotent when the volume doesn't exist.
                self.run(self.build_volume_rm_argv(vol), check=False)

        # 2. Pre-flight init handlers (e.g. verify DBBACKUP_DIR/dump exists).
        for sc in sidecars:
            if sc.init:
                _preflight_init(sc, dbbackup_dir=dbbackup_dir)

        # 3. Bring services up.
        try:
            self.run(self.build_sidecar_up_argv([sc.service for sc in sidecars]))
        except DockerError as exc:
            for sc in sidecars:
                results.append(
                    SidecarResult(name=sc.name, brought_up=False, error=str(exc))
                )
            raise

        # 4. Wait for health (MySQL first-boot restore can be slow).
        for sc in sidecars:
            healthy = _wait_healthy(
                self._compose_argv_base, sc.service, sc.healthcheck_timeout_s
            )
            results.append(
                SidecarResult(
                    name=sc.name,
                    brought_up=True,
                    healthy=healthy,
                    # We can only report we TRIGGERED init (dropped the volume so
                    # MySQL will re-run /docker-entrypoint-initdb.d on next boot);
                    # verifying the SQL actually replayed would require querying
                    # inside the container. Naming avoids overclaiming (LOW #7).
                    init_triggered=fresh and sc.init is not None,
                )
            )
            if not healthy:
                raise DockerError(
                    f"sidecar '{sc.name}' (service '{sc.service}') did not "
                    f"become healthy within {sc.healthcheck_timeout_s}s"
                )
        return results

    def ensure_runner_up(self) -> None:
        self.run(self.build_runner_up_argv())

    def teardown(self) -> None:
        self.run(self.build_down_argv(), check=False)

    def pull(self) -> None:
        # check=True: a --pull request whose purpose is "guarantee fresh"
        # must NOT silently fall through to stale local images on a
        # registry/network error. Surfaces as EXIT_DOCKER_ERROR (HIGH #1).
        self.run(self.build_pull_argv(), check=True)


# ----------------------------------------------------------------------
# Init handlers (only mysql_restore in v1, dispatched by kind).
# ----------------------------------------------------------------------


def _preflight_init(sidecar: Sidecar, *, dbbackup_dir: str | None) -> None:
    """Verify sidecar init prerequisites before docker compose up.

    Fails loudly (InitError → exit 5) if a required file is missing rather
    than letting the sidecar boot with an empty DB.
    """
    if not sidecar.init:
        return
    kind = sidecar.init.get("kind")
    if kind == "mysql_restore":
        _preflight_mysql_restore(sidecar, dbbackup_dir=dbbackup_dir)
    else:
        raise InitError(f"unknown sidecar init kind: {kind!r}")


def _preflight_mysql_restore(sidecar: Sidecar, *, dbbackup_dir: str | None) -> None:
    assert sidecar.init is not None
    source_env = sidecar.init["source_env"]
    source_file = sidecar.init["source_file"]

    # Resolution order: explicit dbbackup_dir override (unused today) > host env.
    root = dbbackup_dir or os.environ.get(source_env)
    if not root:
        raise InitError(
            f"sidecar '{sidecar.name}': ${source_env} is not set and no "
            f"override provided. Set it in .env.ci or the host environment."
        )
    dump = Path(root) / source_file
    if not dump.is_file():
        raise InitError(
            f"sidecar '{sidecar.name}': expected dump file not found at "
            f"{dump}. Check ${source_env}={root} and that {source_file} "
            f"exists there."
        )
    if not os.access(dump, os.R_OK):
        raise InitError(
            f"sidecar '{sidecar.name}': dump file {dump} exists but is not "
            f"readable by the current user."
        )


def _wait_healthy(
    compose_argv_base: list[str], service: str, timeout_s: int
) -> bool:
    """Poll `docker compose ps` for a healthy state, up to timeout_s.

    HIGH #2 hardening: empty `{{.Health}}` (no healthcheck declared) is
    ONLY treated as healthy when the container's State is also `running`.
    Without the State cross-check, an exited container reports `Health=""`
    and would falsely count as healthy — the tier then runs against a
    dead sidecar and tests that tolerate empty rows produce a false green.
    """
    deadline = time.monotonic() + timeout_s
    ps_argv = [
        *compose_argv_base, "ps", "--format",
        "{{.Health}}|{{.State}}", service,
    ]
    while time.monotonic() < deadline:
        result = subprocess.run(ps_argv, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            health, _, state = line.partition("|")
            health = health.strip().lower()
            state = state.strip().lower()
            if health == "healthy":
                return True
            if health == "unhealthy":
                return False
            # Empty health (no healthcheck) → only OK if State is running.
            if health == "" and state == "running":
                return True
            if health == "" and state in {"exited", "dead", "removing"}:
                return False
        time.sleep(1)
    return False
