"""FastMCP discovery and invocation enforcement for reviewed profiles."""

from collections.abc import Sequence

import mcp.types as mt
from fastmcp.resources.base import Resource, ResourceResult
from fastmcp.resources.template import ResourceTemplate, match_uri_template
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult


class ExposureEnforcementMiddleware(Middleware):
    """Filter discovery and reject direct calls outside an immutable allow-set."""

    def __init__(
        self,
        allowed_tool_names: frozenset[str],
        allowed_resource_uris: frozenset[str] = frozenset(),
        allowed_resource_templates: frozenset[str] = frozenset(),
    ) -> None:
        self.allowed_tool_names = allowed_tool_names
        self.allowed_resource_uris = allowed_resource_uris
        self.allowed_resource_templates = allowed_resource_templates

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        """Return only tools admitted by the selected profile."""
        tools = await call_next(context)
        return [tool for tool in tools if tool.name in self.allowed_tool_names]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Reject policy-denied names before tool lookup or execution."""
        if context.message.name not in self.allowed_tool_names:
            raise PermissionError("Tool denied by capability exposure policy")
        return await call_next(context)

    async def on_list_resources(
        self,
        context: MiddlewareContext[mt.ListResourcesRequest],
        call_next: CallNext[mt.ListResourcesRequest, Sequence[Resource]],
    ) -> Sequence[Resource]:
        """Return only resources admitted by the selected profile."""
        resources = await call_next(context)
        return [
            resource
            for resource in resources
            if str(resource.uri) in self.allowed_resource_uris
        ]

    async def on_list_resource_templates(
        self,
        context: MiddlewareContext[mt.ListResourceTemplatesRequest],
        call_next: CallNext[
            mt.ListResourceTemplatesRequest, Sequence[ResourceTemplate]
        ],
    ) -> Sequence[ResourceTemplate]:
        """Return only resource templates admitted by the selected profile."""
        templates = await call_next(context)
        return [
            template
            for template in templates
            if str(template.uri_template) in self.allowed_resource_templates
        ]

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Reject native reads outside the resource allow-set."""
        uri = str(context.message.uri)
        if uri not in self.allowed_resource_uris and not any(
            match_uri_template(uri, template) is not None
            for template in self.allowed_resource_templates
        ):
            raise PermissionError("Resource denied by capability exposure policy")
        return await call_next(context)


__all__ = ["ExposureEnforcementMiddleware"]
