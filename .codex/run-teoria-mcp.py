#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    environment = os.environ.copy()
    repository_root = Path(__file__).resolve().parents[1]
    env_files = []
    if configured_env_file := environment.get("TEORIA_ENV_FILE"):
        env_files.append(Path(configured_env_file).expanduser())
    env_files.extend([
        repository_root / "deploy" / "compose" / ".env",
        repository_root / ".env",
    ])
    token = (
        environment.get("TEORIA_MCP_RUNTIME_API_TOKEN")
        or environment.get("TEORIA_RUNTIME_API_TOKEN")
    )
    for env_file in env_files:
        if token:
            break
        token = dotenv_values(env_file).get("TEORIA_RUNTIME_API_TOKEN")
    if not token:
        raise SystemExit(
            "TEORIA_RUNTIME_API_TOKEN is required in the process environment, "
            "TEORIA_ENV_FILE, deploy/compose/.env, or .env"
        )
    environment["TEORIA_MCP_RUNTIME_API_TOKEN"] = token
    arguments = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "teoria_default",
        "-e",
        "TEORIA_MCP_RUNTIME_MODE=remote",
        "-e",
        "TEORIA_MCP_RUNTIME_API_URL=http://runtime-api:8000",
        "-e",
        "TEORIA_MCP_RUNTIME_API_TOKEN",
    ]
    arguments.append("teoria-mcp:latest")

    os.execvpe(arguments[0], arguments, environment)


if __name__ == "__main__":
    main()
