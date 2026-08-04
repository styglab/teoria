#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REQUIRED_TOOLS = {
    "get_public_procurement_contract",
    "search_public_procurement_contracts",
    "get_company_public_procurement_contracts",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the Teoria MCP STDIO server")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--date-from", default="2026-01-01")
    parser.add_argument("--date-to", default="2026-08-03")
    return parser.parse_args()


async def smoke_test(args: argparse.Namespace) -> None:
    config_path = args.repo / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    server = config["mcp_servers"]["teoria"]
    parameters = StdioServerParameters(
        command=server["command"],
        args=server.get("args", []),
        cwd=server.get("cwd", str(args.repo)),
        env=server.get("env"),
    )

    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            missing = REQUIRED_TOOLS - names
            if missing:
                raise RuntimeError(f"missing required MCP tools: {', '.join(sorted(missing))}")

            result = await session.call_tool(
                "search_public_procurement_contracts",
                {
                    "concluded_date_from": args.date_from,
                    "concluded_date_to": args.date_to,
                    "_options": {"max_objects": 1},
                },
            )
            if result.isError:
                message = getattr(result.content[0], "text", str(result.content[0]))
                raise RuntimeError(f"MCP tool call failed: {message}")

            payload = json.loads(result.content[0].text)
            if payload.get("status") != "success":
                raise RuntimeError(f"unexpected MCP result status: {payload.get('status')}")

            print(f"tool_count={len(names)}")
            print("required_procurement_tools=present")
            print("search_status=success")
            print(f"total_objects={payload.get('total_objects', 0)}")
            print(f"total_links={payload.get('total_links', 0)}")
            print(f"truncated={payload.get('truncated', False)}")


if __name__ == "__main__":
    asyncio.run(smoke_test(parse_args()))
