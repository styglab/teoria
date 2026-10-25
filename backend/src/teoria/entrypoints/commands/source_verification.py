import argparse
import asyncio
import json
from pathlib import Path

import yaml
from teoria.integrations.provider_api.executor import ProviderExecutor
from teoria.integrations.provider_api.secrets import EnvironmentSecretProvider

from teoria.features.semantic_modeling.registry.verification.source.graph import (
    SourceVerificationServices,
    create_source_verification_graph,
)
from teoria.settings import Settings


def _load_input(path: Path | None) -> dict:
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("verification input must be an object")
    return value


async def _verify_source(args: argparse.Namespace, settings: Settings) -> int:
    try:
        input_data = _load_input(args.input)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"ERROR invalid_verification_input: {exc}")
        return 1
    graph = create_source_verification_graph(
        SourceVerificationServices(
            executor=ProviderExecutor(
                timeout_seconds=settings.source_timeout_seconds,
                max_attempts=settings.source_max_attempts,
                secret_provider=EnvironmentSecretProvider(),
            )
        )
    )
    result = await graph.ainvoke(
        {
            "registry_root": str(args.registries),
            "source_id": args.source,
            "operation_id": args.operation,
            "profile": args.profile,
            "input_data": input_data,
            "diagnostics": [],
            "completed_steps": [],
            "step_results": [],
            "status": "pending",
        }
    )
    for step in result.get("step_results", []):
        print(f"{step['status'].upper()} {step['name']}")
    for diagnostic in result.get("diagnostics", []):
        location = f" [{diagnostic['location']}]" if diagnostic.get("location") else ""
        print(
            f"{diagnostic['severity'].upper()} {diagnostic['code']}: {diagnostic['path']}{location}: {diagnostic['message']}"
        )
    if result.get("prepared_request"):
        request = result["prepared_request"]
        print(f"REQUEST {request['method']} {request['url']}")
        if request.get("authentication"):
            print(f"AUTH {request['authentication']['environment_variable']}")
    status = result.get("status", "failed")
    success_labels = {"static": "VALID", "build": "BUILDABLE", "live": "VERIFIED"}
    display_status = (
        success_labels[args.profile] if status == "passed" else status.upper()
    )
    print(f"STATUS {display_status}")
    return 0 if result.get("status") == "passed" else 1


def run_verify_source(args, settings):
    return asyncio.run(_verify_source(args, settings))
