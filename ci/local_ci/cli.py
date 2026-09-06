"""local-ci CLI dispatch (argparse).

Spec: docs/Specs/Local-CI-Skill-Spec.md §5.2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from local_ci.compose import ComposeRunner, DockerError, InitError, TierResult
from local_ci.config import (
    ConfigError,
    ProjectConfig,
    discover_projects,
    load_project,
)
from local_ci.exit_codes import (
    EXIT_CLI_MISUSE,
    EXIT_CONFIG_ERROR,
    EXIT_DOCKER_ERROR,
    EXIT_INIT_ERROR,
    EXIT_OK,
    EXIT_TIER_FAILED,
)
from local_ci.report import RunReport, print_dry_run, print_json_block, print_summary


def _find_ci_root(start: Path | None = None) -> Path:
    """Locate the ci/ directory relative to this file (installed alongside)."""
    # ci/local_ci/cli.py -> ci/
    return Path(__file__).resolve().parent.parent


def _detect_project_from_cwd(configs: list[ProjectConfig], cwd: Path) -> ProjectConfig | None:
    """If CWD is inside a project's dir, pick it."""
    cwd = cwd.resolve()
    for cfg in configs:
        try:
            cwd.relative_to(cfg.project_dir)
            return cfg
        except ValueError:
            continue
    return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local-ci",
        description="Deterministic project-scoped local CI runner.",
    )
    p.add_argument("project", nargs="?", help="Project id (from local-ci.yml)")
    p.add_argument("tiers", nargs="*", help="Tier names to run (default: default_tiers)")
    p.add_argument("--fresh", action="store_true",
                   help="Drop sidecar named-volumes before up (force re-init).")
    p.add_argument("--keep-up", action="store_true",
                   help="Leave stack running after tier completes (default: down).")
    p.add_argument("--json", dest="emit_json", action="store_true",
                   help="Emit machine-readable summary after human log.")
    p.add_argument("--list", dest="do_list", action="store_true",
                   help="List discovered projects and their tiers.")
    p.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="Print planned commands without executing.")
    p.add_argument("--pull", action="store_true",
                   help="docker compose pull before up.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Stream all docker compose stderr.")
    p.add_argument("--ci-root", type=Path, default=None,
                   help="Override the ci/ directory (advanced/testing).")
    p.add_argument("--project-yaml", type=Path, default=None,
                   help="Load a single local-ci.yml directly (advanced/testing).")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    ci_root = args.ci_root.resolve() if args.ci_root else _find_ci_root()

    # --project-yaml: load one config directly (bypasses discovery). Useful
    # for fixtures/tests when a config lives outside the ci/*/ layout.
    if args.project_yaml:
        try:
            single = load_project(args.project_yaml)
        except ConfigError as exc:
            print(f"local-ci: config error: {exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
        configs = [single]
    else:
        try:
            configs = discover_projects(ci_root)
        except ConfigError as exc:
            print(f"local-ci: config error: {exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR

    if args.do_list:
        return _cmd_list(configs, emit_json=args.emit_json)

    # Resolve project.
    cfg = _resolve_project(configs, args.project)
    if cfg is None:
        if args.project:
            print(
                f"local-ci: unknown project {args.project!r}. "
                f"Known: {sorted(c.project for c in configs)}",
                file=sys.stderr,
            )
        else:
            print(
                "local-ci: no project specified and CWD isn't inside any "
                "ci/*/ project. Pass a project name or use --list.",
                file=sys.stderr,
            )
        return EXIT_CLI_MISUSE

    # Resolve tier set.
    tier_names = list(args.tiers) if args.tiers else list(cfg.default_tiers)
    if not tier_names:
        print(
            f"local-ci: project {cfg.project!r} declares no default_tiers "
            f"and none were passed. Available: {sorted(cfg.tiers)}",
            file=sys.stderr,
        )
        return EXIT_CLI_MISUSE
    unknown = [t for t in tier_names if t not in cfg.tiers]
    if unknown:
        print(
            f"local-ci: unknown tier(s) {unknown} for project {cfg.project!r}. "
            f"Available: {sorted(cfg.tiers)}",
            file=sys.stderr,
        )
        return EXIT_CLI_MISUSE

    # Collect sidecars needed for these tiers.
    needed_sidecar_names: list[str] = []
    for t in tier_names:
        for s in cfg.tiers[t].requires_services:
            if s not in needed_sidecar_names:
                needed_sidecar_names.append(s)
    needed_sidecars = [cfg.sidecars[s] for s in needed_sidecar_names]

    runner = ComposeRunner(cfg, verbose=args.verbose)

    if args.dry_run:
        return _cmd_dry_run(
            cfg, runner, tier_names, needed_sidecar_names, fresh=args.fresh,
            pull=args.pull,
        )

    report = RunReport(project=cfg.project)

    try:
        if args.pull:
            runner.pull()
        if needed_sidecars:
            report.sidecars = runner.ensure_sidecars(
                needed_sidecars,
                fresh=args.fresh,
                dbbackup_dir=os.environ.get("DBBACKUP_DIR"),
            )
        runner.ensure_runner_up()

        for tname in tier_names:
            result = runner.exec_tier(cfg.tiers[tname])
            report.tiers.append(result)
    except InitError as exc:
        print(f"local-ci: sidecar init failed: {exc}", file=sys.stderr)
        _maybe_teardown(runner, keep_up=args.keep_up)
        return EXIT_INIT_ERROR
    except DockerError as exc:
        print(f"local-ci: docker error: {exc}", file=sys.stderr)
        _maybe_teardown(runner, keep_up=args.keep_up)
        return EXIT_DOCKER_ERROR
    finally:
        pass

    print_summary(report)
    if args.emit_json:
        print_json_block(report)

    _maybe_teardown(runner, keep_up=args.keep_up)

    return EXIT_OK if report.overall_status == "pass" else EXIT_TIER_FAILED


def _maybe_teardown(runner: ComposeRunner, *, keep_up: bool) -> None:
    if keep_up:
        return
    try:
        runner.teardown()
    except DockerError:
        # Teardown failures shouldn't override the tier-outcome exit code.
        pass


def _resolve_project(
    configs: list[ProjectConfig], name: str | None
) -> ProjectConfig | None:
    if name:
        for cfg in configs:
            if cfg.project == name:
                return cfg
        return None
    return _detect_project_from_cwd(configs, Path.cwd())


# ----------------------------------------------------------------------
# Sub-command implementations
# ----------------------------------------------------------------------


def _cmd_list(configs: list[ProjectConfig], *, emit_json: bool) -> int:
    if emit_json:
        payload = {
            "schema": "local-ci/v1",
            "projects": [
                {
                    "project": cfg.project,
                    "description": cfg.description,
                    "yaml_path": str(cfg.yaml_path),
                    "default_tiers": list(cfg.default_tiers),
                    "tiers": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "command": t.command,
                            "requires_services": list(t.requires_services),
                        }
                        for t in cfg.tiers.values()
                    ],
                    "sidecars": sorted(cfg.sidecars),
                }
                for cfg in configs
            ],
        }
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        print("")
        return EXIT_OK

    if not configs:
        print("local-ci: no projects discovered under ci/*/local-ci.yml")
        return EXIT_OK
    print(f"local-ci: {len(configs)} project(s) discovered")
    for cfg in configs:
        default = f" (default: {', '.join(cfg.default_tiers)})" if cfg.default_tiers else ""
        print(f"  {cfg.project}{default}")
        if cfg.description:
            print(f"      {cfg.description}")
        for t in cfg.tiers.values():
            svc = f"  [sidecars: {', '.join(t.requires_services)}]" if t.requires_services else ""
            print(f"      - {t.name:12s} {t.description}{svc}")
    return EXIT_OK


def _cmd_dry_run(
    cfg: ProjectConfig,
    runner: ComposeRunner,
    tier_names: list[str],
    sidecar_names: list[str],
    *,
    fresh: bool,
    pull: bool,
) -> int:
    compose_argvs: list[list[str]] = []
    if pull:
        compose_argvs.append(runner.build_pull_argv())
    if fresh:
        for scn in sidecar_names:
            sc = cfg.sidecars[scn]
            if sc.init and sc.init.get("volume"):
                compose_argvs.append(runner.build_volume_rm_argv(sc.init["volume"]))
    if sidecar_names:
        compose_argvs.append(
            runner.build_sidecar_up_argv([cfg.sidecars[n].service for n in sidecar_names])
        )
    compose_argvs.append(runner.build_runner_up_argv())
    tier_argvs = [(n, runner.build_tier_argv(cfg.tiers[n])) for n in tier_names]
    print_dry_run(cfg.project, compose_argvs, tier_argvs)
    return EXIT_OK
