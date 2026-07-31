from __future__ import annotations

import asyncio
from pathlib import Path

import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider
from teoria_mcp.tools import CapabilityMCPService
from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability import CapabilityRunner
from teoria_mcp.settings import MCPSettings, bootstrap_mcp_settings


def create_server(
    registry_root: Path | str = "platform/registries",
    settings: MCPSettings | None = None,
) -> tuple[Server, CapabilityMCPService]:
    catalog = RegistryLoader(registry_root).load()
    runner = None
    if settings is not None:
        runner = CapabilityRunner(
            ProviderExecutor(
                timeout_seconds=settings.embedded_source_timeout_seconds,
                max_attempts=settings.embedded_source_max_attempts,
                secret_provider=EnvironmentSecretProvider(),
            ),
            timeout_seconds=settings.embedded_capability_timeout_seconds,
            max_pages=settings.embedded_source_max_pages,
        )
    service = CapabilityMCPService(catalog, runner=runner)
    server = Server("teoria")

    @server.list_tools()
    async def list_tools():
        return service.list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        return await service.call_tool(name, arguments)

    return server, service


async def run_stdio() -> None:
    settings = bootstrap_mcp_settings()
    if settings.runtime_mode != "embedded":
        raise RuntimeError("remote MCP mode requires the Runtime API client, which is not implemented yet")
    server, _ = create_server(settings.embedded_registry_path, settings)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="teoria",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
