from __future__ import annotations

import asyncio
import os
from pathlib import Path

import mcp.server.stdio
from dotenv import load_dotenv
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from teoria.mcp.service import CapabilityMCPService
from teoria.registry.loader import RegistryLoader


def create_server(registry_root: Path | str = "registries") -> tuple[Server, CapabilityMCPService]:
    catalog = RegistryLoader(registry_root).load()
    service = CapabilityMCPService(catalog)
    server = Server("teoria")

    @server.list_tools()
    async def list_tools():
        return service.list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        return await service.call_tool(name, arguments)

    return server, service


async def run_stdio() -> None:
    load_dotenv(override=False)
    registry_root = Path(os.environ.get("TEORIA_REGISTRIES", "registries"))
    server, _ = create_server(registry_root)
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
