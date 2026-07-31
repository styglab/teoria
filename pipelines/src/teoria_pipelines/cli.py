from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import yaml
from psycopg import Error as PostgresError

from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider
from teoria_pipelines.loader import PipelineLoadError, PipelineLoader
from teoria_pipelines.persistence import PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings
from teoria_pipelines.validator import PipelineValidator
from teoria_pipelines.verification import verify_connector


def _default_pipeline_root() -> Path:
    return Path(os.environ.get("TEORIA_PIPELINE_PATH", "pipelines"))


def _default_platform_registry_root() -> Path:
    return Path(os.environ.get("TEORIA_PLATFORM_REGISTRY_PATH", "platform/registries"))


def _load_input(path: Path | None) -> dict:
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("verification input must be an object")
    return value


async def _verify(args: argparse.Namespace) -> int:
    try:
        input_data = _load_input(args.input)
        pipeline_catalog = PipelineLoader(args.pipelines).load()
        data_types = None
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError, PipelineLoadError) as exc:
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics:
            for diagnostic in diagnostics:
                print(diagnostic)
        else:
            print(f"ERROR invalid_verification_input: {exc}")
        return 1
    if args.platform_registries:
        from teoria.registry.loader import RegistryLoadError, RegistryLoader
        try:
            data_types = RegistryLoader(args.platform_registries).load().data_types
        except RegistryLoadError as exc:
            for diagnostic in exc.diagnostics:
                print(diagnostic)
            return 1
    settings = bootstrap_pipeline_settings()
    result = await verify_connector(
        pipeline_catalog,
        connector_id=args.connector,
        operation_id=args.operation,
        profile=args.profile,
        input_data=input_data,
        data_types=data_types,
        executor=ProviderExecutor(
            timeout_seconds=settings.source_timeout_seconds,
            max_attempts=settings.source_max_attempts,
            secret_provider=EnvironmentSecretProvider(),
        ),
    )
    for step in result["step_results"]:
        print(f"{step['status'].upper()} {step['name']}")
    for diagnostic in result["diagnostics"]:
        location = f" [{diagnostic['location']}]" if diagnostic.get("location") else ""
        print(
            f"{diagnostic['severity'].upper()} {diagnostic['code']}: "
            f"{diagnostic['path']}{location}: {diagnostic['message']}"
        )
    if result.get("prepared_request"):
        request = result["prepared_request"]
        print(f"REQUEST {request['method']} {request['url']}")
        if request.get("authentication"):
            print(f"AUTH {request['authentication']['environment_variable']}")
    success_labels = {"static": "VALID", "build": "BUILDABLE", "live": "VERIFIED"}
    display = success_labels[args.profile] if result["status"] == "passed" else result["status"].upper()
    print(f"STATUS {display}")
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="teoria-pipelines")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate Connector and Pipeline contracts")
    validate_parser.add_argument("path", nargs="?", default=_default_pipeline_root(), type=Path)
    validate_parser.add_argument("--connector")

    integration_parser = subparsers.add_parser(
        "validate-integration", help="validate Pipeline sink and shared data-type contracts against Platform"
    )
    integration_parser.add_argument("path", nargs="?", default=_default_pipeline_root(), type=Path)
    integration_parser.add_argument("--platform-registries", default=_default_platform_registry_root(), type=Path)

    migrate_parser = subparsers.add_parser("migrate", help="apply Teoria Data DB migrations")
    migrate_parser.add_argument(
        "--migrations",
        default=Path("pipelines/database/migrations"),
        type=Path,
    )

    verify_parser = subparsers.add_parser("verify", help="verify an ingestion Connector")
    verify_subparsers = verify_parser.add_subparsers(dest="target", required=True)
    connector_parser = verify_subparsers.add_parser("connector")
    connector_parser.add_argument("--profile", choices=("static", "build", "live"), default="static")
    connector_parser.add_argument("--pipelines", default=_default_pipeline_root(), type=Path)
    connector_parser.add_argument("--platform-registries", type=Path)
    connector_parser.add_argument("--connector", required=True)
    connector_parser.add_argument("--operation")
    connector_parser.add_argument("--input", type=Path)
    args = parser.parse_args()

    if args.command == "verify":
        return asyncio.run(_verify(args))
    if args.command == "migrate":
        settings = bootstrap_pipeline_settings()
        try:
            applied = PostgresStore(settings.data_database_url or "").apply_migrations(args.migrations)
        except (OSError, ValueError, PostgresError) as exc:
            print(f"ERROR migration_failed: {exc}")
            return 1
        if applied:
            for version in applied:
                print(f"APPLIED {version}")
        else:
            print("Database schema is up to date.")
        return 0
    try:
        pipeline_catalog = PipelineLoader(args.path).load()
    except PipelineLoadError as exc:
        for diagnostic in exc.diagnostics:
            print(diagnostic)
        return 1
    if args.command == "validate-integration":
        try:
            from teoria.registry.loader import RegistryLoadError, RegistryLoader
            from teoria_pipelines.integration import PlatformIntegrationValidator
            platform_catalog = RegistryLoader(args.platform_registries).load()
        except RegistryLoadError as exc:
            for diagnostic in exc.diagnostics:
                print(diagnostic)
            return 1
        diagnostics = PlatformIntegrationValidator().validate(pipeline_catalog, platform_catalog)
    else:
        diagnostics = PipelineValidator().validate(pipeline_catalog, connector_id=args.connector)
    for diagnostic in diagnostics:
        print(diagnostic)
    if diagnostics:
        return 1
    connector_count = 1 if getattr(args, "connector", None) else len(pipeline_catalog.connectors)
    print(
        f"Validated {connector_count} ingestion connector{'s' if connector_count != 1 else ''} "
        f"and {len(pipeline_catalog.pipelines)} pipeline{'s' if len(pipeline_catalog.pipelines) != 1 else ''}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
