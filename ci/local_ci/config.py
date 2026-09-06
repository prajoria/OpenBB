"""YAML config loading + JSON Schema validation for local-ci.yml.

Loads and validates ci/*/local-ci.yml against schema/local-ci.schema.json,
performs cross-checks the schema can't express (default_tiers ⊆ tiers,
compose file exists, requires_services ⊆ sidecars), and discovers projects
by scanning the ci/ tree.

Spec: docs/Specs/Local-CI-Skill-Spec.md §5.1
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from local_ci.exit_codes import EXIT_CONFIG_ERROR


class ConfigError(Exception):
    """Raised for any config-level failure. Carries exit code EXIT_CONFIG_ERROR."""

    exit_code = EXIT_CONFIG_ERROR


SCHEMA_PATH = Path(__file__).parent / "schema" / "local-ci.schema.json"
REPORT_SCHEMA_PATH = Path(__file__).parent / "schema" / "report.schema.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Tier:
    name: str
    command: str
    description: str = ""
    requires_services: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sidecar:
    name: str
    service: str
    healthcheck_timeout_s: int = 60
    init: dict[str, Any] | None = None


@dataclass(frozen=True)
class Compose:
    file: Path  # absolute path
    runner_service: str
    env_file: str | None = None  # relative to yaml_path.parent


@dataclass(frozen=True)
class ProjectConfig:
    """Parsed + validated local-ci.yml, tied to its on-disk path."""

    yaml_path: Path  # absolute
    project: str
    description: str
    compose: Compose
    tiers: dict[str, Tier]
    default_tiers: tuple[str, ...]
    sidecars: dict[str, Sidecar] = field(default_factory=dict)

    @property
    def project_dir(self) -> Path:
        return self.yaml_path.parent


def load_project(yaml_path: Path) -> ProjectConfig:
    """Load and validate one local-ci.yml. Raises ConfigError on any failure."""
    yaml_path = yaml_path.resolve()
    if not yaml_path.is_file():
        raise ConfigError(f"local-ci.yml not found at {yaml_path}")

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {yaml_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{yaml_path}: top-level YAML must be a mapping")

    # Schema validation — additionalProperties:false ensures no silent drift.
    try:
        jsonschema.validate(raw, _load_schema())
    except jsonschema.ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ConfigError(
            f"{yaml_path}: schema violation at '{path}': {exc.message}"
        ) from exc

    # Parse into typed structures.
    tiers = {
        name: Tier(
            name=name,
            command=body["command"],
            description=body.get("description", ""),
            requires_services=tuple(body.get("requires_services", [])),
        )
        for name, body in raw["tiers"].items()
    }
    sidecars = {
        name: Sidecar(
            name=name,
            service=body["service"],
            healthcheck_timeout_s=body.get("healthcheck_timeout_s", 60),
            init=body.get("init"),
        )
        for name, body in (raw.get("sidecars") or {}).items()
    }
    default_tiers = tuple(raw.get("default_tiers") or [])

    compose_file_rel = raw["compose"]["file"]
    compose_file = (yaml_path.parent / compose_file_rel).resolve()

    compose = Compose(
        file=compose_file,
        runner_service=raw["compose"]["runner_service"],
        env_file=raw["compose"].get("env_file"),
    )

    cfg = ProjectConfig(
        yaml_path=yaml_path,
        project=raw["project"],
        description=raw.get("description", ""),
        compose=compose,
        tiers=tiers,
        default_tiers=default_tiers,
        sidecars=sidecars,
    )

    _cross_validate(cfg)
    return cfg


def _cross_validate(cfg: ProjectConfig) -> None:
    """Checks the schema can't express."""
    # default_tiers ⊆ tiers
    unknown_defaults = [t for t in cfg.default_tiers if t not in cfg.tiers]
    if unknown_defaults:
        raise ConfigError(
            f"{cfg.yaml_path}: default_tiers references unknown tier(s): "
            f"{unknown_defaults}"
        )

    # tier.requires_services ⊆ sidecars
    for tier in cfg.tiers.values():
        unknown = [s for s in tier.requires_services if s not in cfg.sidecars]
        if unknown:
            raise ConfigError(
                f"{cfg.yaml_path}: tier '{tier.name}' requires_services "
                f"references unknown sidecar(s): {unknown}"
            )

    # compose file must exist (relative to yaml_path.parent).
    # We don't parse it — that's docker's job — but we fail fast on typos.
    if not cfg.compose.file.is_file():
        raise ConfigError(
            f"{cfg.yaml_path}: compose file not found at {cfg.compose.file}"
        )


def discover_projects(ci_root: Path) -> list[ProjectConfig]:
    """Find every ci/*/local-ci.yml under ci_root. Sorted by project name."""
    ci_root = ci_root.resolve()
    if not ci_root.is_dir():
        return []
    configs: list[ProjectConfig] = []
    for yml in sorted(ci_root.glob("*/local-ci.yml")):
        # Skip fixtures dir starting with underscore for --list; discoverable
        # only by explicit path load.
        if yml.parent.name.startswith("_"):
            continue
        configs.append(load_project(yml))
    return configs
