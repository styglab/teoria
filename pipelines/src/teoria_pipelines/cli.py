from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml
from psycopg import Error as PostgresError
from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.secrets import EnvironmentSecretProvider

from teoria_pipelines.loader import PipelineLoader, PipelineLoadError
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
    except (
        OSError,
        ValueError,
        yaml.YAMLError,
        json.JSONDecodeError,
        PipelineLoadError,
    ) as exc:
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics:
            for diagnostic in diagnostics:
                print(diagnostic)
        else:
            print(f"ERROR invalid_verification_input: {exc}")
        return 1
    if args.platform_registries:
        from teoria.registry.loader import RegistryLoader, RegistryLoadError

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
    display = (
        success_labels[args.profile]
        if result["status"] == "passed"
        else result["status"].upper()
    )
    print(f"STATUS {display}")
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="teoria-pipelines")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="validate Connector and Pipeline contracts"
    )
    validate_parser.add_argument(
        "path", nargs="?", default=_default_pipeline_root(), type=Path
    )
    validate_parser.add_argument("--connector")

    deployment_docs_parser = subparsers.add_parser(
        "deployment-docs", help="print deployment inventory or check its saved document"
    )
    deployment_docs_parser.add_argument(
        "--pipelines", default=_default_pipeline_root(), type=Path
    )
    deployment_docs_parser.add_argument("--check", type=Path)

    integration_parser = subparsers.add_parser(
        "validate-integration",
        help="validate Pipeline sink and shared data-type contracts against Platform",
    )
    integration_parser.add_argument(
        "path", nargs="?", default=_default_pipeline_root(), type=Path
    )
    integration_parser.add_argument(
        "--platform-registries", default=_default_platform_registry_root(), type=Path
    )

    migrate_parser = subparsers.add_parser(
        "migrate", help="apply Teoria Data DB migrations"
    )
    migrate_parser.add_argument(
        "--migrations",
        default=Path("pipelines/database/migrations"),
        type=Path,
    )

    register_parser = subparsers.add_parser(
        "register", help="register Prefect deployments and queue policies"
    )
    register_parser.add_argument(
        "--backend", choices=("process", "kubernetes"), required=True
    )
    register_parser.add_argument(
        "--kind", choices=("ingestion", "metadata", "all"), default="ingestion"
    )
    register_parser.add_argument(
        "--pipelines", type=Path, default=_default_pipeline_root()
    )

    worker_parser = subparsers.add_parser(
        "worker",
        help="reconcile finished ingestion runs, then start a Prefect process worker",
    )
    worker_parser.add_argument("--pool", required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="verify an ingestion Connector"
    )
    verify_subparsers = verify_parser.add_subparsers(dest="target", required=True)
    connector_parser = verify_subparsers.add_parser("connector")
    connector_parser.add_argument(
        "--profile", choices=("static", "build", "live"), default="static"
    )
    connector_parser.add_argument(
        "--pipelines", default=_default_pipeline_root(), type=Path
    )
    connector_parser.add_argument("--platform-registries", type=Path)
    connector_parser.add_argument("--connector", required=True)
    connector_parser.add_argument("--operation")
    connector_parser.add_argument("--input", type=Path)
    law_parser = subparsers.add_parser("law", help="collect and inspect versioned laws")
    law_subparsers = law_parser.add_subparsers(dest="law_command", required=True)
    law_sync = law_subparsers.add_parser("sync")
    law_sync.add_argument("--pipelines", default=_default_pipeline_root(), type=Path)
    law_sync.add_argument("--target", action="append")
    law_sync.add_argument("--reconcile-all", action="store_true")
    law_sync.add_argument("--requests-per-second", type=float, default=1)
    law_reparse = law_subparsers.add_parser("reparse")
    law_reparse.add_argument("--target")
    law_reparse.add_argument("--all", action="store_true")
    law_versions = law_subparsers.add_parser("versions")
    law_versions.add_argument("--target")
    law_show = law_subparsers.add_parser("show")
    law_show.add_argument("--law-id", required=True)
    law_show.add_argument("--mst", required=True)
    law_show.add_argument("--effective-date", type=date.fromisoformat, required=True)
    law_show.add_argument("--article", help="article number, e.g. 24의2")
    args = parser.parse_args()

    if args.command == "deployment-docs":
        from teoria_pipelines.deployment_docs import render_deployment_docs

        rendered = render_deployment_docs(args.pipelines)
        if args.check:
            if args.check.read_text(encoding="utf-8") != rendered:
                print(
                    "ERROR stale_deployment_docs: regenerate the deployment inventory"
                )
                return 1
            print("Deployment inventory is up to date.")
        else:
            print(rendered, end="")
        return 0

    if args.command == "law":
        settings = bootstrap_pipeline_settings()
        from teoria_pipelines.domains.legal_information.laws.repository import (
            LawRepository,
        )

        if args.law_command == "sync":
            from teoria_pipelines.domains.legal_information.laws.flows import (
                sync_moleg_laws,
            )

            result = asyncio.run(
                sync_moleg_laws(
                    pipeline_root=str(args.pipelines),
                    target_ids=args.target,
                    reconcile_all=args.reconcile_all,
                    requests_per_second=args.requests_per_second,
                )
            )
        elif args.law_command == "reparse":
            from teoria_pipelines.domains.legal_information.laws.flows import (
                reparse_moleg_laws,
            )

            result = asyncio.run(
                reparse_moleg_laws(target_id=args.target, reparse_all=args.all)
            )
        elif args.law_command == "versions":
            result = asyncio.run(
                LawRepository(settings.data_database_url or "").stored_versions(
                    args.target
                )
            )
        else:
            from teoria_pipelines.domains.legal_information.laws.parsing import (
                provider_id,
            )

            result = asyncio.run(
                LawRepository(settings.data_database_url or "").get_provisions(
                    provider_id(args.law_id),
                    provider_id(args.mst),
                    args.effective_date,
                    args.article,
                )
            )
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
        return 0

    if args.command == "worker":
        from teoria_pipelines.deployment import positive_setting
        from teoria_pipelines.recovery import reconcile_finished_pipeline_runs

        limit = positive_setting("TEORIA_PIPELINE_CONCURRENCY", 2)
        settings = bootstrap_pipeline_settings()
        try:
            recovered = asyncio.run(
                reconcile_finished_pipeline_runs(
                    PostgresStore(settings.data_database_url or "")
                )
            )
        except (OSError, ValueError, PostgresError) as exc:
            print(f"ERROR run_reconciliation_failed: {exc}", file=sys.stderr)
            return 1
        for execution_id in recovered:
            print(f"RECOVERED {execution_id}", flush=True)
        os.execvp(
            "prefect",
            [
                "prefect",
                "worker",
                "start",
                "--type",
                "process",
                "--pool",
                args.pool,
                "--limit",
                str(limit),
            ],
        )
        return 0

    if args.command == "register":
        from teoria_pipelines.deployment import register_deployments

        register_deployments(args.pipelines, backend=args.backend, kind=args.kind)
        return 0

    if args.command == "verify":
        return asyncio.run(_verify(args))
    if args.command == "migrate":
        settings = bootstrap_pipeline_settings()
        try:
            applied = asyncio.run(
                PostgresStore(settings.data_database_url or "").apply_migrations(
                    args.migrations
                )
            )
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
            from teoria.registry.loader import RegistryLoader, RegistryLoadError

            from teoria_pipelines.integration import PlatformIntegrationValidator

            platform_catalog = RegistryLoader(args.platform_registries).load()
        except RegistryLoadError as exc:
            for diagnostic in exc.diagnostics:
                print(diagnostic)
            return 1
        diagnostics = PlatformIntegrationValidator().validate(
            pipeline_catalog, platform_catalog
        )
    else:
        diagnostics = PipelineValidator().validate(
            pipeline_catalog, connector_id=args.connector
        )
        if not args.connector:
            from teoria_pipelines.deployment_docs import load_deployments
            from teoria_pipelines.deployment_validation import (
                validate_deployment_contracts,
            )

            diagnostics.extend(
                validate_deployment_contracts(
                    pipeline_catalog, load_deployments(args.path)
                )
            )
    for diagnostic in diagnostics:
        print(diagnostic)
    if diagnostics:
        return 1
    connector_count = (
        1 if getattr(args, "connector", None) else len(pipeline_catalog.connectors)
    )
    print(
        f"Validated {connector_count} ingestion connector{'s' if connector_count != 1 else ''} "
        f"and {len(pipeline_catalog.pipelines)} pipeline{'s' if len(pipeline_catalog.pipelines) != 1 else ''}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
