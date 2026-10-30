"""Verify the selected Compose API modules before starting workers or pruning images."""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

from teoria.settings import bootstrap_settings


async def verify(expected: dict[str, bool]) -> None:
    settings = bootstrap_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "http://localhost:8001/v1/admin/auth/session",
            headers={"Authorization": f"Bearer {settings.admin_api_token}"},
        )
        response.raise_for_status()
        response = await client.get("http://localhost:8001/v1/admin/deployment")
        response.raise_for_status()
        if response.json() != expected:
            raise ValueError("Selected modules do not match the running Admin API")
        if expected["semantic"]:
            response = await client.get(
                settings.context_runtime_api_url.rstrip("/") + "/v1/version",
                headers={
                    "Authorization": f"Bearer {settings.context_runtime_api_token}"
                },
            )
            response.raise_for_status()
            if not response.json().get("runtime_artifact", {}).get("bundle_checksum"):
                raise ValueError("Published Runtime artifact is unavailable")
        if expected["mlops"]:
            response = await client.get(
                settings.model_mlflow_url.rstrip("/") + "/health"
            )
            response.raise_for_status()
    print("Authenticated Admin API and selected module connections verified")


if __name__ == "__main__":
    try:
        asyncio.run(verify(json.loads(sys.argv[1])))
    except Exception as error:
        print(
            f"Deployment verification failed ({type(error).__name__}); workers remain stopped",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
