"""local-ci: deterministic project-scoped local CI runner.

CLI + YAML config that runs each project's real CI commands inside Docker Compose.
Source of truth for both direct human invocation and agent skill wrapper.

Spec: docs/Specs/Local-CI-Skill-Spec.md
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
