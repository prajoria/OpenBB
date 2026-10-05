"""Custom Prompt classes for FastMCP."""

# FastMCP Prompt fields are Pydantic descriptors at static-analysis time.
# pylint: disable=abstract-method,no-member

from typing import Any

from fastmcp.exceptions import PromptError
from fastmcp.prompts import Prompt
from mcp.types import PromptMessage, TextContent
from pydantic import BaseModel, ConfigDict, Field


class PromptDependencies(BaseModel):
    """Structured runtime requirements for one bundled prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_tools: tuple[str, ...] = ()
    any_tool_groups: tuple[tuple[str, ...], ...] = ()
    providers: tuple[str, ...] = ()
    optional_packages: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()


class PromptReadiness(BaseModel):
    """Resolved dependency readiness."""

    available: bool
    reasons: tuple[str, ...] = ()


def evaluate_prompt_dependencies(
    dependencies: PromptDependencies,
    *,
    tools: set[str],
    providers: set[str],
    packages: set[str],
    resources: set[str],
) -> PromptReadiness:
    """Evaluate against the full discoverable surface, not startup activation."""
    reasons = [
        f"missing tool: {name}"
        for name in dependencies.required_tools
        if name not in tools
    ]
    reasons.extend(
        f"missing one-of tools: {', '.join(group)}"
        for group in dependencies.any_tool_groups
        if not set(group) & tools
    )
    reasons.extend(
        f"missing provider: {name}"
        for name in dependencies.providers
        if name not in providers
    )
    reasons.extend(
        f"missing optional package: {name}"
        for name in dependencies.optional_packages
        if name not in packages
    )
    reasons.extend(
        f"missing resource: {name}"
        for name in dependencies.resources
        if name not in resources
    )
    return PromptReadiness(available=not reasons, reasons=tuple(reasons))


class StaticPrompt(Prompt):
    """A prompt that is a static string template."""

    content: str
    argument_defaults: dict[str, Any] = Field(default_factory=dict)
    dependencies: PromptDependencies = Field(default_factory=PromptDependencies)
    readiness: PromptReadiness = Field(
        default_factory=lambda: PromptReadiness(available=True)
    )

    async def render(
        self,
        arguments: dict[str, Any] | None = None,
    ) -> list[PromptMessage]:
        """Render the prompt with arguments."""
        if not self.readiness.available:
            raise PromptError(
                "Prompt unavailable: " + "; ".join(self.readiness.reasons)
            )
        # Start with stored defaults, then overlay caller-supplied values
        args = {**self.argument_defaults, **(arguments or {})}

        # Validate required arguments
        if self.arguments:
            required = {arg.name for arg in self.arguments if arg.required}
            provided = set(args)
            missing = required - provided
            if missing:
                raise PromptError(f"Missing required arguments: {missing}")

        try:
            rendered_content = (
                self.content.format(**args) if self.arguments or args else self.content
            )
            return [
                PromptMessage(
                    role="user", content=TextContent(type="text", text=rendered_content)
                )
            ]
        except KeyError as e:
            raise PromptError(f"Missing argument for formatting: {e}") from e
