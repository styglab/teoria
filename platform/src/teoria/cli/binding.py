import argparse
import json

from teoria.binding.capability_manifest import (
    CapabilityBindingManifest,
    apply_capability_binding_manifest,
)
from teoria.binding.openmetadata_manifest import (
    OpenMetadataBindingManifest,
    apply_openmetadata_binding_manifest,
)
from teoria.binding.repository import BindingRepository
from teoria.registry.artifact import (
    RegistryArtifactLoader,
)
from teoria.registry.loader import RegistryLoader
from teoria.settings import Settings


async def run_bind_openmetadata(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    parts = args.ontology_ref.split(".")
    if len(parts) != 3:
        print("ERROR --ontology-ref must be namespace.Object.property")
        return 1
    try:
        binding_id = await BindingRepository(
            settings.app_database_url
        ).bind_openmetadata_reference(
            namespace=parts[0],
            object_code=parts[1],
            property_code=parts[2],
            target_type=args.target_type,
            external_entity_id=args.external_id,
            entity_type=args.entity_type,
            fully_qualified_name=args.fqn,
            external_version=args.external_version,
            locator=args.locator,
            binding_type=args.binding_type,
            purpose=args.purpose,
            authority=args.authority,
            priority=args.priority,
            created_by=args.actor,
        )
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 1
    print(f"Bound {args.ontology_ref} to {args.locator} ({binding_id})")
    return 0


async def run_bind_capabilities(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        catalog = (
            RegistryArtifactLoader(args.registry_artifact).load()
            if args.registry_artifact is not None
            else RegistryLoader(args.registries).load()
        )
        result = await apply_capability_binding_manifest(
            BindingRepository(settings.app_database_url),
            catalog,
            CapabilityBindingManifest.load(args.manifest),
            actor=args.actor,
            approve=args.approve,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR capability_binding_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def run_plan_openmetadata_bindings(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        result = await apply_openmetadata_binding_manifest(
            BindingRepository(settings.app_database_url),
            OpenMetadataBindingManifest.load(args.manifest),
            actor=args.actor,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR openmetadata_binding_plan_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
