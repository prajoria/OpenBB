"""Job registry and discovery helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from openbb_core.app.jobs.models import JobDefinition
from pydantic import BaseModel


class DuplicateJobDefinitionError(ValueError):
    """Raised when two job definitions share a name."""


class UnknownJobDefinitionError(KeyError):
    """Raised when a job name is not present in the registry."""


class JobProvider(Protocol):
    """Callable that returns job definitions for registration."""

    def __call__(self) -> list[JobDefinition]:
        """Return job definitions."""


class JobRegistry:
    """Registry of allowlisted job definitions."""

    def __init__(self, definitions: Iterable[JobDefinition] | None = None) -> None:
        """Initialize a registry, optionally pre-loading definitions."""
        self._definitions: dict[str, JobDefinition] = {}

        for definition in definitions or ():
            self.register(definition)

    @property
    def definitions(self) -> tuple[JobDefinition, ...]:
        """Return registered definitions sorted by job name."""
        return tuple(
            self._definitions[name] for name in sorted(self._definitions.keys())
        )

    def __contains__(self, job_name: str) -> bool:
        """Return whether a job is registered."""
        return job_name in self._definitions

    def __len__(self) -> int:
        """Return the number of registered jobs."""
        return len(self._definitions)

    @classmethod
    def discover(cls, providers: Iterable[JobProvider]) -> JobRegistry:
        """Build a registry from provider callables."""
        registry = cls()

        for provider in providers:
            definitions = provider()
            if not isinstance(definitions, list):
                definitions = list(definitions)

            for definition in definitions:
                if not isinstance(definition, JobDefinition):
                    raise TypeError(
                        "Job providers must return JobDefinition instances"
                    )
                registry.register(definition)

        return registry

    def register(self, definition: JobDefinition) -> None:
        """Register a single job definition."""
        if definition.name in self._definitions:
            raise DuplicateJobDefinitionError(
                f"Duplicate job definition: {definition.name}"
            )

        self._definitions[definition.name] = definition

    def get(self, job_name: str) -> JobDefinition:
        """Return a registered definition or raise when absent."""
        try:
            return self._definitions[job_name]
        except KeyError as error:
            raise UnknownJobDefinitionError(job_name) from error

    def validate_params(
        self,
        job_name: str,
        params: Mapping[str, Any] | BaseModel | None = None,
    ) -> BaseModel:
        """Validate parameters against a job definition's Pydantic model."""
        definition = self.get(job_name)

        if params is None:
            params_dict: Mapping[str, Any] = {}
        elif isinstance(params, definition.params_model):
            return params
        elif isinstance(params, BaseModel):
            params_dict = params.model_dump()
        else:
            params_dict = params

        return definition.params_model.model_validate(params_dict)
