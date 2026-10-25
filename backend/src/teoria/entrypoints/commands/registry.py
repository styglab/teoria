import argparse

import psycopg

from teoria.features.semantic_modeling.registry.artifact import (
    RegistryArtifactError,
    RegistryArtifactLoader,
    RegistryArtifactStore,
    RuntimeBundleCompiler,
)
from teoria.features.semantic_modeling.registry.artifact_snapshot import (
    RuntimeBundleSnapshotRepository,
    select_registry_bindings,
)
from teoria.features.semantic_modeling.registry.composition import create_registry_validator
from teoria.features.semantic_modeling.registry.loader import RegistryLoader, RegistryLoadError
from teoria.features.semantic_modeling.registry.release import publish_registry
from teoria.settings import Settings


def run_activate_artifact(args: argparse.Namespace, settings: Settings) -> int:
    try:
        active = RegistryArtifactStore(args.store).activate(args.version)
    except (OSError, RegistryArtifactError) as exc:
        print(f"ERROR registry_artifact_activation_failed: {exc}")
        return 1
    print(f"Activated Runtime bundle {active.version} ({active.checksum}).")
    return 0


async def run_compile_runtime_bundle(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not args.database_url:
        print(
            "ERROR runtime_bundle_compile_failed: application database URL is required"
        )
        return 1
    try:
        ontologies, bindings = await RuntimeBundleSnapshotRepository(
            args.database_url
        ).snapshot(ontology_namespaces=set(args.ontology_namespaces or ["teoria"]))
        catalog = RegistryArtifactLoader(args.registry_artifact).load()
        selected_bindings = select_registry_bindings(catalog, bindings)
        manifest = RuntimeBundleCompiler().compile(
            args.registry_artifact,
            ontologies=ontologies,
            bindings=selected_bindings,
            output=args.output,
            version=args.version,
        )
    except (OSError, ValueError, RegistryArtifactError, psycopg.Error) as exc:
        print(f"ERROR runtime_bundle_compile_failed: {exc}")
        return 1
    print(f"Compiled Runtime bundle {manifest.version} ({manifest.bundle_checksum}); "
          f"excluded {len(bindings) - len(selected_bindings)} bindings to retired targets.")
    return 0


def run_validate_or_publish(args: argparse.Namespace, settings: Settings) -> int:
    try:
        catalog = RegistryLoader(args.path).load()
    except RegistryLoadError as exc:
        for diagnostic in exc.diagnostics:
            print(diagnostic)
        return 1

    diagnostics = create_registry_validator().validate(
        catalog, source_id=getattr(args, "source", None)
    )
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
    runtime_contract_count = len(catalog.runtime_contracts)
    mapping_count = len(catalog.mappings)
    capability_count = len(catalog.capabilities)
    active_reference_count = sum(
        reference.status == "active" for reference in catalog.references.values()
    )
    draft_reference_count = sum(
        reference.status == "draft" for reference in catalog.references.values()
    )
    mapping_label = "mapping" if mapping_count == 1 else "mappings"
    runtime_contract_label = (
        "runtime contract" if runtime_contract_count == 1 else "runtime contracts"
    )
    active_reference_label = (
        "reference" if active_reference_count == 1 else "references"
    )
    draft_reference_label = "reference" if draft_reference_count == 1 else "references"
    print(
        f"Validated {source_count} {source_label}, {runtime_contract_count} {runtime_contract_label}, "
        f"{mapping_count} {mapping_label}, {len(catalog.data_types)} data types, "
        f"{len(catalog.value_sets)} value sets, {active_reference_count} active provider {active_reference_label}, "
        f"{draft_reference_count} draft provider {draft_reference_label}, and {capability_count} capabilities."
    )
    return 0
