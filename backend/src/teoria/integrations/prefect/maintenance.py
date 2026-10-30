"""Pause owned pools/schedules and preserve their state across Compose maintenance.

Invoked as a synchronous process entrypoint by the Compose deployment controller.
Only IDs and pause flags cross stdout; credentials remain in the API container.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yaml
from teoria.integrations.prefect.deployment_manifests import deployment_directory

import httpx

from teoria.integrations.prefect.http_client import PrefectManagementClient


def pool_policies() -> dict[str, set[str]]:
    directory = deployment_directory(
        Path(os.environ.get("TEORIA_PIPELINE_PATH", "/app/backend")), "process"
    )
    policies = {
        path.stem: {
            p["name"] for p in yaml.safe_load(path.read_text()).get("pools", [])
        }
        for path in directory.glob("*.yaml")
    }
    if not policies or any(not names for names in policies.values()):
        raise ValueError("Compose Prefect ownership policies are unavailable")
    return policies


async def snapshot(
    client: PrefectManagementClient, retained: dict | None = None
) -> dict:
    pools = await client.request("POST", "/work_pools/filter", {"limit": 200})
    policies = pool_policies()
    owned = set().union(*policies.values())
    pools = [p for p in pools if p["name"] in owned]
    names = {p["name"] for p in pools}
    deployments = []
    offset = 0
    while True:
        page = await client.request(
            "POST", "/deployments/filter", {"offset": offset, "limit": 100}
        )
        deployments.extend(d for d in page if d.get("work_pool_name") in names)
        if len(page) < 100:
            break
        offset += len(page)
    result = {
        "pools": [{"name": p["name"], "is_paused": p["is_paused"]} for p in pools],
        "schedules": [
            {
                "deployment_id": d["id"],
                "id": s["id"],
                "active": s["active"],
                "schedule": s["schedule"],
            }
            for d in deployments
            for s in d.get("schedules", [])
        ],
        "deployment_ids": [d["id"] for d in deployments],
        "deployment_pools": {d["id"]: d["work_pool_name"] for d in deployments},
    }
    # Retain original flags for features intentionally disabled by an earlier deployment.
    if retained:
        for key, identifier in (
            ("pools", lambda p: p["name"]),
            ("schedules", lambda s: s["id"]),
        ):
            previous = {identifier(item): item for item in retained.get(key, [])}
            result[key] = [previous.get(identifier(item), item) for item in result[key]]
    return result


def selected_pools() -> set[str]:
    policies = pool_policies()
    enabled = {
        "model_operations": os.getenv("TEORIA_MODEL_OPERATIONS_ENABLED") == "true",
        "metadata_management": os.getenv("TEORIA_SEMANTIC_MODELING_ENABLED") == "true",
        "legal_information": os.getenv("TEORIA_LEGAL_INFORMATION_ENABLED") == "true",
        "specification_processing": os.getenv("TEORIA_FORMATID_ENABLED") == "true",
    }
    return set().union(
        *(names for feature, names in policies.items() if enabled.get(feature, False))
    )


async def set_paused(
    client: PrefectManagementClient, state: dict, *, restore: bool
) -> dict:
    selected = selected_pools() if restore else {p["name"] for p in state["pools"]}
    for pool in state["pools"]:
        if pool["name"] in selected:
            await client.request(
                "PATCH",
                f"/work_pools/{pool['name']}",
                {"is_paused": pool["is_paused"] if restore else True},
            )
    for schedule in state["schedules"]:
        if state["deployment_pools"][schedule["deployment_id"]] not in selected:
            continue
        identifier = schedule["id"]
        if restore:
            # Registration may replace schedule IDs; match the unchanged schedule definition.
            deployment = await client.request(
                "GET", f"/deployments/{schedule['deployment_id']}", {}
            )
            match = next(
                (
                    item
                    for item in deployment.get("schedules", [])
                    if item["id"] == identifier
                    or item["schedule"] == schedule["schedule"]
                ),
                None,
            )
            if match is None:
                continue
            identifier = match["id"]
        await client.update_schedule(
            schedule["deployment_id"],
            identifier,
            {"active": schedule["active"] if restore else False},
        )
    remaining_ids = [
        i
        for i in state["deployment_ids"]
        if state["deployment_pools"][i] not in selected
    ]
    return {
        "pools": [p for p in state["pools"] if p["name"] not in selected],
        "schedules": [
            s for s in state["schedules"] if s["deployment_id"] in remaining_ids
        ],
        "deployment_ids": remaining_ids,
        "deployment_pools": {i: state["deployment_pools"][i] for i in remaining_ids},
    }


async def active_runs(client: PrefectManagementClient, state: dict) -> int:
    ids = state["deployment_ids"]
    if not ids:
        return 0
    return await client.request(
        "POST",
        "/flow_runs/count",
        {
            "deployments": {"id": {"any_": ids}},
            "flow_runs": {
                "state": {
                    "type": {"any_": ["PENDING", "RUNNING", "CANCELLING", "PAUSED"]}
                }
            },
        },
    )


async def main(action: str, state: dict) -> dict:
    auth = os.environ["TEORIA_MODEL_PREFECT_AUTH"]
    url = os.environ.get("TEORIA_MODEL_PREFECT_URL", "http://prefect-server:4200/api")
    async with httpx.AsyncClient(timeout=30) as http:
        client = PrefectManagementClient(http, url, auth)
        if action == "snapshot":
            return await snapshot(client, state)
        if action in {"pause", "resume"}:
            return await set_paused(client, state, restore=action == "resume")
        if action == "active":
            return {"active": await active_runs(client, state)}
        raise ValueError("Unsupported maintenance action")


if __name__ == "__main__":
    try:
        result = asyncio.run(main(sys.argv[1], json.load(sys.stdin)))
        print(json.dumps(result))
    except Exception as error:
        # URLs, response bodies and credentials are intentionally omitted.
        print(f"Prefect maintenance failed ({type(error).__name__})", file=sys.stderr)
        raise SystemExit(1) from None
