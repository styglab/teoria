"""The repository MCP command must work without a Compose network or container image."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

ROOT = Path(__file__).resolve().parents[4]


async def test_configured_command_initializes_and_discovers_over_runtime_http():
    if not shutil.which("uv"):
        pytest.skip("uv is required to run the repository MCP command")
    requests = []
    capability = {
        "id": "synthetic_goods_lookup", "version": "1.0.0", "name": "Synthetic goods",
        "description": "Isolated protocol fixture", "returns": ["fixture.goods"],
        "input_schema": {"type": "object", "properties": {}},
    }

    async def runtime(reader, writer):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            requests.append(request)
            payload = json.dumps({"capabilities": [capability]}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                         + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(runtime, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        config = tomllib.loads((ROOT / ".codex/config.toml").read_text())["mcp_servers"]["teoria"]
        assert "tools" not in config
        parameters = StdioServerParameters(
            command=config["command"],
            # Do not sync the shared environment while pytest is using it.
            args=[config["args"][0], "--no-sync", *config["args"][1:]],
            cwd=str(ROOT),
            env={**os.environ, "TEORIA_ENV_FILE": str(ROOT / ".missing_mcp_test.env"),
                 "TEORIA_MCP_RUNTIME_MODE": "remote",
                 "TEORIA_MCP_RUNTIME_API_URL": f"http://127.0.0.1:{port}",
                 "TEORIA_MCP_RUNTIME_API_TOKEN": "synthetic-mcp-token"},
        )
        async with asyncio.timeout(30):
            async with stdio_client(parameters) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
        assert [tool.name for tool in listed.tools] == [capability["id"]]
        assert len(requests) == 1
        assert requests[0].startswith(b"GET /v1/capabilities HTTP/1.1\r\n")
        assert b"Authorization: Bearer synthetic-mcp-token\r\n" in requests[0]
