from __future__ import annotations

import asyncio
from pathlib import Path

import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from teoria.adapters.secrets import EnvironmentSecretProvider
from teoria.adapters.mcp.tools import CapabilityMCPService
from teoria.config import Settings, bootstrap_settings
from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability import CapabilityRunner
from teoria.runtime.source.executor import SourceExecutor


def create_server(
    registry_root: Path | str = "registries",
    settings: Settings | None = None,
) -> tuple[Server, CapabilityMCPService]:
    catalog = RegistryLoader(registry_root).load()
    runner = None
    if settings is not None:
        runner = CapabilityRunner(
            SourceExecutor(
                timeout_seconds=settings.source_timeout_seconds,
                max_attempts=settings.source_max_attempts,
                secret_provider=EnvironmentSecretProvider(),
            ),
            timeout_seconds=settings.capability_timeout_seconds,
            max_pages=settings.source_max_pages,
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
    settings = bootstrap_settings()
    server, _ = create_server(settings.registry_path, settings)
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
