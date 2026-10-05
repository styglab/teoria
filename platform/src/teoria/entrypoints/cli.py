import argparse
import asyncio
import json
from pathlib import Path

import yaml

from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider
from teoria.config import Settings, bootstrap_settings
from teoria.registry.loader import RegistryLoadError, RegistryLoader
from teoria.registry.release import publish_registry
from teoria.registry.validator import RegistryValidator
from teoria.persistence import apply_migrations
from teoria.binding.repository import BindingRepository
from teoria.binding.capability_manifest import CapabilityBindingManifest, apply_capability_binding_manifest
from teoria.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.ontology.promotion import BusinessConceptPromotion, apply_business_concept_promotion
from teoria.ontology.enrichment import OntologyEnrichmentManifest, apply_ontology_enrichment
from teoria.registry.verification.source.graph import SourceVerificationServices, create_source_verification_graph


def _add_verify_parser(subparsers: argparse._SubParsersAction, settings: Settings) -> None:
    verify_parser = subparsers.add_parser("verify", help="run a registry verification workflow")
    verify_subparsers = verify_parser.add_subparsers(dest="registry_type", required=True)
    source_parser = verify_subparsers.add_parser("source", help="verify a Source Registry")
    source_parser.add_argument("--profile", choices=("static", "build", "live"), default="static")
    source_parser.add_argument("--registries", default=settings.registry_path, type=Path)
    source_parser.add_argument("--source")
    source_parser.add_argument("--operation")
    source_parser.add_argument("--input", type=Path)


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
        print(f"{diagnostic['severity'].upper()} {diagnostic['code']}: {diagnostic['path']}{location}: {diagnostic['message']}")
    if result.get("prepared_request"):
        request = result["prepared_request"]
        print(f"REQUEST {request['method']} {request['url']}")
        if request.get("authentication"):
            print(f"AUTH {request['authentication']['environment_variable']}")
    status = result.get("status", "failed")
    success_labels = {"static": "VALID", "build": "BUILDABLE", "live": "VERIFIED"}
    display_status = success_labels[args.profile] if status == "passed" else status.upper()
    print(f"STATUS {display_status}")
    return 0 if result.get("status") == "passed" else 1


def main() -> int:
    settings = bootstrap_settings()
    parser = argparse.ArgumentParser(prog="teoria")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate authored registries")
    validate_parser.add_argument("path", nargs="?", default=settings.registry_path, type=Path)
    validate_parser.add_argument("--source", help="validate only one source id")
    publish_parser = subparsers.add_parser("publish", help="validate and publish an immutable registry release")
    publish_parser.add_argument("path", nargs="?", default=settings.registry_path, type=Path)
    publish_parser.add_argument("--version", required=True)
    publish_parser.add_argument("--output", type=Path)
    publish_parser.add_argument("--git-commit")
    migrate_parser = subparsers.add_parser("migrate-app", help="apply Teoria application DB migrations")
    migrate_parser.add_argument("--migrations", type=Path, default=Path("platform/database/migrations"))
    binding_parser = subparsers.add_parser("bind-openmetadata", help="bind a confirmed OpenMetadata reference to an ontology property")
    binding_parser.add_argument("--ontology-ref", required=True, help="namespace.Object.property")
    binding_parser.add_argument("--target-type", choices=("glossary_term", "data_asset"), required=True)
    binding_parser.add_argument("--external-id", required=True)
    binding_parser.add_argument("--entity-type", required=True)
    binding_parser.add_argument("--fqn", required=True)
    binding_parser.add_argument("--external-version")
    binding_parser.add_argument("--locator", required=True)
    binding_parser.add_argument("--binding-type", default="represents")
    binding_parser.add_argument("--purpose")
    binding_parser.add_argument("--authority", choices=("authoritative", "preferred", "supplemental"), default="preferred")
    binding_parser.add_argument("--priority", type=int, default=100)
    binding_parser.add_argument("--actor", default="system:openmetadata-sync")
    migration_report_parser = subparsers.add_parser("ontology-migration-report", help="validate and report legacy Registry to Ontology v2 migration")
    migration_report_parser.add_argument("--manifest", type=Path, default=Path("platform/ontology-migrations/ontology-v2.yaml"))
    migration_report_parser.add_argument("--registries", type=Path, default=settings.registry_path)
    promotion_parser = subparsers.add_parser("promote-business-concepts", help="author legacy business concepts in Ontology v2")
    promotion_parser.add_argument("--manifest", type=Path, default=Path("platform/ontology-migrations/business-concepts-v1.yaml"))
    promotion_parser.add_argument("--actor", default="system:ontology-migration")
    promotion_parser.add_argument("--publish", action="store_true")
    capability_binding_parser = subparsers.add_parser("bind-capabilities", help="apply reviewed Ontology-to-Capability bindings")
    capability_binding_parser.add_argument("--manifest", type=Path, default=Path("platform/ontology-migrations/capability-bindings-v1.yaml"))
    capability_binding_parser.add_argument("--registries", type=Path, default=settings.registry_path)
    capability_binding_parser.add_argument("--actor", default="system:ontology-migration")
    capability_binding_parser.add_argument("--approve", action="store_true")
    enrichment_parser = subparsers.add_parser("enrich-business-ontology", help="apply reviewed properties and relationships to Ontology v2")
    enrichment_parser.add_argument("--manifest", type=Path, default=Path("platform/ontology-migrations/business-ontology-enrichment-v1.yaml"))
    enrichment_parser.add_argument("--actor", default="system:ontology-migration")
    enrichment_parser.add_argument("--publish", action="store_true")
    _add_verify_parser(subparsers, settings)
    args = parser.parse_args()

    if args.command == "migrate-app":
        if not settings.app_database_url:
            print("ERROR TEORIA_APP_DATABASE_URL is required")
            return 1
        for version in apply_migrations(settings.app_database_url, args.migrations):
            print(f"Applied {version}")
        return 0

    if args.command == "bind-openmetadata":
        if not settings.app_database_url:
            print("ERROR TEORIA_APP_DATABASE_URL is required")
            return 1
        parts = args.ontology_ref.split(".")
        if len(parts) != 3:
            print("ERROR --ontology-ref must be namespace.Object.property")
            return 1
        try:
            binding_id = BindingRepository(settings.app_database_url).bind_openmetadata_reference(
                namespace=parts[0], object_code=parts[1], property_code=parts[2],
                target_type=args.target_type, external_entity_id=args.external_id,
                entity_type=args.entity_type, fully_qualified_name=args.fqn,
                external_version=args.external_version, locator=args.locator,
                binding_type=args.binding_type, purpose=args.purpose,
                authority=args.authority, priority=args.priority, created_by=args.actor,
            )
        except ValueError as exc:
            print(f"ERROR {exc}")
            return 1
        print(f"Bound {args.ontology_ref} to {args.locator} ({binding_id})")
        return 0

    if args.command == "ontology-migration-report":
        try:
            catalog = RegistryLoader(args.registries).load()
            manifest = OntologyMigrationManifest.load(args.manifest)
            report = build_migration_report(catalog, manifest, application_database_url=settings.app_database_url)
        except (OSError, ValueError) as exc:
            print(f"ERROR ontology_migration_report_failed: {exc}")
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "valid" else 1

    if args.command == "promote-business-concepts":
        if not settings.app_database_url:
            print("ERROR TEORIA_APP_DATABASE_URL is required")
            return 1
        try:
            result = apply_business_concept_promotion(
                OntologyAuthoringRepository(settings.app_database_url),
                BusinessConceptPromotion.load(args.manifest),
                actor=args.actor,
                publish=args.publish,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR business_concept_promotion_failed: {exc}")
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "bind-capabilities":
        if not settings.app_database_url:
            print("ERROR TEORIA_APP_DATABASE_URL is required")
            return 1
        try:
            catalog = RegistryLoader(args.registries).load()
            result = apply_capability_binding_manifest(
                BindingRepository(settings.app_database_url), catalog,
                CapabilityBindingManifest.load(args.manifest),
                actor=args.actor, approve=args.approve,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR capability_binding_failed: {exc}")
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "enrich-business-ontology":
        if not settings.app_database_url:
            print("ERROR TEORIA_APP_DATABASE_URL is required")
            return 1
        try:
            result = apply_ontology_enrichment(
                OntologyAuthoringRepository(settings.app_database_url),
                OntologyEnrichmentManifest.load(args.manifest), actor=args.actor, publish=args.publish,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR ontology_enrichment_failed: {exc}")
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "verify" and args.registry_type == "source":
        return asyncio.run(_verify_source(args, settings))

    try:
        catalog = RegistryLoader(args.path).load()
    except RegistryLoadError as exc:
        for diagnostic in exc.diagnostics:
            print(diagnostic)
        return 1

    diagnostics = RegistryValidator().validate(catalog, source_id=getattr(args, "source", None))
    for diagnostic in diagnostics:
        print(diagnostic)
    if diagnostics:
        return 1

    if args.command == "publish":
        try:
            release = publish_registry(
                args.path,
                version=args.version,
                output=args.output,
                git_commit=args.git_commit,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR registry_publish_failed: {exc}")
            return 1
        print(
            f"Published Registry {release.version} ({release.checksum}) "
            f"from commit {release.git_commit}."
        )
        return 0

    source_count = 1 if args.source else len(catalog.sources)
    source_label = "source" if source_count == 1 else "sources"
    ontology_count = len(catalog.ontologies)
    mapping_count = len(catalog.mappings)
    capability_count = len(catalog.capabilities)
    active_reference_count = sum(reference.status == "active" for reference in catalog.references.values())
    draft_reference_count = sum(reference.status == "draft" for reference in catalog.references.values())
    mapping_label = "mapping" if mapping_count == 1 else "mappings"
    ontology_label = "ontology" if ontology_count == 1 else "ontologies"
    active_reference_label = "reference" if active_reference_count == 1 else "references"
    draft_reference_label = "reference" if draft_reference_count == 1 else "references"
    print(
        f"Validated {source_count} {source_label}, {ontology_count} {ontology_label}, "
        f"{mapping_count} {mapping_label}, {len(catalog.data_types)} data types, "
        f"{len(catalog.value_sets)} value sets, {active_reference_count} active provider {active_reference_label}, "
        f"{draft_reference_count} draft provider {draft_reference_label}, and {capability_count} capabilities."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
