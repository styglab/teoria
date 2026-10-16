import asyncio
import inspect

from teoria.cli.binding import (
    run_bind_capabilities,
    run_bind_openmetadata,
    run_plan_openmetadata_bindings,
)
from teoria.cli.database import (
    run_migrate_app,
)
from teoria.cli.ontology import (
    run_apply_business_rules,
    run_apply_ontology_blueprint,
    run_apply_ontology_extension,
    run_enrich_business_ontology,
    run_ontology_migration_report,
    run_promote_business_concepts,
)
from teoria.cli.parser import create_parser
from teoria.cli.registry import (
    run_activate_artifact,
    run_compile_runtime_bundle,
    run_validate_or_publish,
)
from teoria.cli.source_verification import run_verify_source
from teoria.domains.public_procurement.cli import (
    run_profile_ontology_sources,
    run_validate_ontology_shadow,
)
from teoria.settings import bootstrap_settings


def main() -> int:
    settings = bootstrap_settings()
    args = create_parser(settings).parse_args()
    handlers = {
        "migrate-app": run_migrate_app,
        "bind-openmetadata": run_bind_openmetadata,
        "ontology-migration-report": run_ontology_migration_report,
        "promote-business-concepts": run_promote_business_concepts,
        "bind-capabilities": run_bind_capabilities,
        "enrich-business-ontology": run_enrich_business_ontology,
        "apply-ontology-blueprint": run_apply_ontology_blueprint,
        "plan-openmetadata-bindings": run_plan_openmetadata_bindings,
        "apply-business-rules": run_apply_business_rules,
        "validate-ontology-shadow": run_validate_ontology_shadow,
        "apply-ontology-extension": run_apply_ontology_extension,
        "profile-ontology-sources": run_profile_ontology_sources,
        "activate-artifact": run_activate_artifact,
        "compile-runtime-bundle": run_compile_runtime_bundle,
        "verify": run_verify_source,
    }
    result = handlers.get(args.command, run_validate_or_publish)(args, settings)
    return asyncio.run(result) if inspect.isawaitable(result) else result


if __name__ == "__main__":
    raise SystemExit(main())
