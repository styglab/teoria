from __future__ import annotations

import asyncio

import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from teoria_mcp.runtime_client import RuntimeAPIClient
from teoria_mcp.settings import bootstrap_mcp_settings
from teoria_mcp.tools import CapabilityMCPService


async def run_stdio() -> None:
    settings = bootstrap_mcp_settings()
    client = RuntimeAPIClient(
        settings.runtime_api_url,
        settings.runtime_api_token,
        timeout_seconds=settings.runtime_timeout_seconds,
    )
    service = CapabilityMCPService(await client.list_capabilities(), client)
    server = Server("teoria")

    @server.list_tools()
    async def list_tools():
        return service.list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        return await service.call_tool(name, arguments)

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
