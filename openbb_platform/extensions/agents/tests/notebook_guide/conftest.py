"""Shared fixtures for the Notebook MCP Companion tests (#2213, N03).

Every test here runs with the network denied and the home directory moved to
a temporary root, so no test can reach a provider or touch the operator's real
``~/.portfolio_importer`` data. Scenarios are frozen, hand-computed inputs and
expectations; their provenance is mandatory.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SCENARIOS = Path(__file__).resolve().parent / "fixtures" / "scenarios"


class ScenarioProvenance(BaseModel):
    """Where a scenario came from; synthetic and redistributable only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["synthetic"]
    computed_by: Literal["hand"]
    redistributable: Literal[True]
    rationale: str = Field(min_length=10)


class Scenario(BaseModel):
    """Frozen inputs and independently computed expectations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    id: str
    provenance: ScenarioProvenance
    stories: list[str] = Field(min_length=1)
    inputs: dict[str, Any]
    expected: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        """Expose inputs as attributes, so ``scenario.weights`` reads naturally."""
        inputs = self.__dict__.get("inputs", {})
        if name in inputs:
            return inputs[name]
        raise AttributeError(name)


def load_scenarios() -> dict[str, Scenario]:
    """Return every committed scenario, keyed by ID."""
    scenarios = {}
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        if scenario.id != path.stem:
            raise ValueError(f"{path.name}: id '{scenario.id}' does not match file")
        scenarios[scenario.id] = scenario
    return scenarios


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    """Fail any attempt to open a network connection."""

    def deny(*_args, **_kwargs):
        raise AssertionError("notebook_guide tests must not open network connections")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point every home-directory lookup at a temporary root."""
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def scenario_factory():
    """Return a loader for one frozen scenario by ID."""
    scenarios = load_scenarios()

    def factory(scenario_id: str) -> Scenario:
        return scenarios[scenario_id]

    return factory


def _write_notebook(path: Path, cells: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "cells": cells,
        "metadata": {"kernelspec": {"name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def notebook_factory(tmp_path):
    """Return a factory writing one notebook whose outputs and metadata vary."""

    def factory(
        output: str = "saved-output",
        root: Path | None = None,
        source: str = "from openbb import obb\nobb.equity.price.historical('SYNTH')",
        relative: str = "portfolio/01-synthetic.ipynb",
        execution_count: int = 1,
    ) -> Path:
        root = root or tmp_path / "notebooks"
        _write_notebook(
            root / relative,
            [
                {"cell_type": "markdown", "metadata": {}, "source": ["# Synthetic"]},
                {
                    "cell_type": "code",
                    "execution_count": execution_count,
                    "metadata": {"execution": {"started": output}},
                    "outputs": [{"output_type": "stream", "text": [output]}],
                    "source": source,
                },
            ],
        )
        return root

    return factory


SHA = "a" * 64


@pytest.fixture
def manifest_factory():
    """Return a factory that builds a manifest from compact stage data."""
    # pylint: disable=import-outside-toplevel
    from openbb_agents.notebook_guide.contracts import StoryManifest

    def factory(
        *,
        dependencies: dict[str, list[str]] | None = None,
        capabilities: dict[str, list[str]] | None = None,
        inputs: dict[str, list[dict]] | None = None,
        outputs: dict[str, list[str]] | None = None,
        cells: dict[str, list[int]] | None = None,
        extra_stage_fields: dict | None = None,
    ) -> StoryManifest:
        dependencies = dependencies or {"a": [], "b": ["a"]}
        stages = []
        for index, (stage_id, depends_on) in enumerate(dependencies.items(), 1):
            stage = {
                "id": stage_id,
                "title": f"Stage {stage_id}",
                "kind": "analysis",
                "cells": (cells or {}).get(stage_id, [index]),
                "depends_on": depends_on,
                "capabilities": (capabilities or {}).get(
                    stage_id, ["platform:equity_profile"]
                ),
                "inputs": (inputs or {}).get(stage_id, []),
                "outputs": (outputs or {}).get(stage_id, [f"{stage_id}_result"]),
                "optional": False,
            }
            stage.update(extra_stage_fields or {})
            stages.append(stage)
        return StoryManifest.model_validate(
            {
                "schema_version": 1,
                "story_id": "portfolio/01",
                "family": "portfolio/01",
                "variant": "portfolio",
                "notebook_path": "notebooks/portfolio/01-synthetic.ipynb",
                "source_sha256": SHA,
                "stages": stages,
                "acceptance_cases": ["portfolio/01:fixture"],
                "limitations": [],
            }
        )

    return factory
