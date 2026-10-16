import argparse
from pathlib import Path

from teoria.settings import Settings


def _add_verify_parser(
    subparsers: argparse._SubParsersAction, settings: Settings
) -> None:
    verify_parser = subparsers.add_parser(
        "verify", help="run a registry verification workflow"
    )
    verify_subparsers = verify_parser.add_subparsers(
        dest="registry_type", required=True
    )
    source_parser = verify_subparsers.add_parser(
        "source", help="verify a Source Registry"
    )
    source_parser.add_argument(
        "--profile", choices=("static", "build", "live"), default="static"
    )
    source_parser.add_argument(
        "--registries", default=settings.registry_path, type=Path
    )
    source_parser.add_argument("--source")
    source_parser.add_argument("--operation")
    source_parser.add_argument("--input", type=Path)


def create_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teoria")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="validate authored registries"
    )
    validate_parser.add_argument(
        "path", nargs="?", default=settings.registry_path, type=Path
    )
    validate_parser.add_argument("--source", help="validate only one source id")
    publish_parser = subparsers.add_parser(
        "publish", help="validate and publish an immutable registry release"
    )
    publish_parser.add_argument(
        "path", nargs="?", default=settings.registry_path, type=Path
    )
    publish_parser.add_argument("--version", required=True)
    publish_parser.add_argument("--output", required=True, type=Path)
    publish_parser.add_argument("--git-commit")
    activate_parser = subparsers.add_parser(
        "activate-artifact", help="atomically activate a validated Registry artifact"
    )
    activate_parser.add_argument("store", type=Path)
    activate_parser.add_argument("--version", required=True)
    bundle_parser = subparsers.add_parser(
        "compile-runtime-bundle",
        help="freeze a Registry artifact with published Ontologies and approved Bindings",
    )
    bundle_parser.add_argument("registry_artifact", type=Path)
    bundle_parser.add_argument("--output", type=Path, required=True)
    bundle_parser.add_argument("--version", required=True)
    bundle_parser.add_argument("--database-url", default=settings.app_database_url)
    bundle_parser.add_argument(
        "--ontology-namespace",
        action="append",
        dest="ontology_namespaces",
        help="published Ontology namespace to include; defaults to teoria",
    )
    migrate_parser = subparsers.add_parser(
        "migrate-app", help="apply Teoria application DB migrations"
    )
    migrate_parser.add_argument(
        "--migrations", type=Path, default=Path("platform/database/migrations")
    )
    binding_parser = subparsers.add_parser(
        "bind-openmetadata",
        help="bind a confirmed OpenMetadata reference to an ontology property",
    )
    binding_parser.add_argument(
        "--ontology-ref", required=True, help="namespace.Object.property"
    )
    binding_parser.add_argument(
        "--target-type", choices=("glossary_term", "data_asset"), required=True
    )
    binding_parser.add_argument("--external-id", required=True)
    binding_parser.add_argument("--entity-type", required=True)
    binding_parser.add_argument("--fqn", required=True)
    binding_parser.add_argument("--external-version")
    binding_parser.add_argument("--locator", required=True)
    binding_parser.add_argument("--binding-type", default="represents")
    binding_parser.add_argument("--purpose")
    binding_parser.add_argument(
        "--authority",
        choices=("authoritative", "preferred", "supplemental"),
        default="preferred",
    )
    binding_parser.add_argument("--priority", type=int, default=100)
    binding_parser.add_argument("--actor", default="system:openmetadata-sync")
    migration_report_parser = subparsers.add_parser(
        "ontology-migration-report",
        help="validate and report legacy Registry to Ontology v2 migration",
    )
    migration_report_parser.add_argument("--manifest", type=Path, required=True)
    migration_report_parser.add_argument(
        "--registries", type=Path, default=settings.registry_path
    )
    promotion_parser = subparsers.add_parser(
        "promote-business-concepts",
        help="author legacy business concepts in Ontology v2",
    )
    promotion_parser.add_argument("--manifest", type=Path, required=True)
    promotion_parser.add_argument("--actor", default="system:ontology-migration")
    promotion_parser.add_argument("--publish", action="store_true")
    capability_binding_parser = subparsers.add_parser(
        "bind-capabilities", help="apply reviewed Ontology-to-Capability bindings"
    )
    capability_binding_parser.add_argument("--manifest", type=Path, required=True)
    capability_binding_parser.add_argument(
        "--registries", type=Path, default=settings.registry_path
    )
    capability_binding_parser.add_argument(
        "--registry-artifact",
        type=Path,
        help="published Registry artifact; required when --approve is used",
    )
    capability_binding_parser.add_argument(
        "--actor", default="system:ontology-migration"
    )
    capability_binding_parser.add_argument("--approve", action="store_true")
    enrichment_parser = subparsers.add_parser(
        "enrich-business-ontology",
        help="apply reviewed properties and relationships to Ontology v2",
    )
    enrichment_parser.add_argument("--manifest", type=Path, required=True)
    enrichment_parser.add_argument("--actor", default="system:ontology-migration")
    enrichment_parser.add_argument("--publish", action="store_true")
    blueprint_parser = subparsers.add_parser(
        "apply-ontology-blueprint",
        help="create a reviewed ontology blueprint as a draft",
    )
    blueprint_parser.add_argument("--manifest", type=Path, required=True)
    blueprint_parser.add_argument("--actor", default="system:ontology-migration")
    metadata_binding_parser = subparsers.add_parser(
        "plan-openmetadata-bindings",
        help="create draft bindings from a reviewed OpenMetadata manifest",
    )
    metadata_binding_parser.add_argument("--manifest", type=Path, required=True)
    metadata_binding_parser.add_argument("--actor", default="system:ontology-migration")
    rule_parser = subparsers.add_parser(
        "apply-business-rules",
        help="add reviewed derivation rules to an ontology draft",
    )
    rule_parser.add_argument("--manifest", type=Path, required=True)
    rule_parser.add_argument("--actor", default="system:ontology-migration")
    shadow_parser = subparsers.add_parser(
        "validate-ontology-shadow",
        help="compare ontology identity rules with operational procurement data",
    )
    shadow_parser.add_argument("--bid-notice-id", required=True)
    extension_parser = subparsers.add_parser(
        "apply-ontology-extension",
        help="add reviewed objects and relationships to an ontology draft",
    )
    extension_parser.add_argument("--manifest", type=Path, required=True)
    extension_parser.add_argument("--actor", default="system:ontology-migration")
    profile_parser = subparsers.add_parser(
        "profile-ontology-sources",
        help="profile Data DB identity and lifecycle coverage",
    )
    profile_parser.add_argument(
        "--deep",
        action="store_true",
        help="include expensive cross-table collision and linkage checks",
    )
    profile_parser.add_argument("--statement-timeout-ms", type=int, default=30_000)
    _add_verify_parser(subparsers, settings)
    return parser
