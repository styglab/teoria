import argparse
import json

from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService
from teoria.features.semantic_modeling.ontology.blueprint import (
    OntologyBlueprint,
    apply_ontology_blueprint,
)
from teoria.features.semantic_modeling.ontology.enrichment import (
    OntologyEnrichmentManifest,
    apply_ontology_enrichment,
)
from teoria.features.semantic_modeling.ontology.extension import (
    OntologyExtensionManifest,
    apply_ontology_extension,
)
from teoria.features.semantic_modeling.ontology.migration import (
    OntologyMigrationManifest,
    build_migration_report,
)
from teoria.features.semantic_modeling.ontology.promotion import (
    BusinessConceptPromotion,
    apply_business_concept_promotion,
)
from teoria.features.semantic_modeling.ontology.rule_manifest import (
    BusinessRuleManifest,
    apply_business_rule_manifest,
)
from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.settings import Settings


async def run_ontology_migration_report(
    args: argparse.Namespace, settings: Settings
) -> int:
    try:
        catalog = RegistryLoader(args.registries).load()
        manifest = OntologyMigrationManifest.load(args.manifest)
        report = await build_migration_report(
            catalog, manifest, application_database_url=settings.app_database_url
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR ontology_migration_report_failed: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "valid" else 1


async def run_promote_business_concepts(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        result = await apply_business_concept_promotion(
            OntologyAuthoringService(settings.app_database_url),
            BusinessConceptPromotion.load(args.manifest),
            actor=args.actor,
            publish=args.publish,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR business_concept_promotion_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def run_enrich_business_ontology(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        result = await apply_ontology_enrichment(
            OntologyAuthoringService(settings.app_database_url),
            OntologyEnrichmentManifest.load(args.manifest),
            actor=args.actor,
            publish=args.publish,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR ontology_enrichment_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def run_apply_ontology_blueprint(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        result = await apply_ontology_blueprint(
            OntologyAuthoringService(settings.app_database_url),
            OntologyBlueprint.load(args.manifest),
            actor=args.actor,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR ontology_blueprint_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def run_apply_business_rules(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        result = await apply_business_rule_manifest(
            OntologyAuthoringService(settings.app_database_url),
            BusinessRuleManifest.load(args.manifest),
            actor=args.actor,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR business_rule_manifest_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def run_apply_ontology_extension(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    try:
        result = await apply_ontology_extension(
            OntologyAuthoringService(settings.app_database_url),
            OntologyExtensionManifest.load(args.manifest),
            actor=args.actor,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR ontology_extension_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
