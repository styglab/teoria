from pathlib import Path

from teoria.platform.ontology.authoring.blueprint import OntologyBlueprint
from teoria.platform.ontology.authoring.extension import OntologyExtensionManifest
from teoria.platform.ontology.contracts.ontology_migration import OntologyMigrationManifest
from teoria.platform.ontology.authoring.unification import OntologyUnificationManifest, validate_unification_plan


ROOT = (Path(__file__).resolve().parents[4])
MIGRATION = ROOT / "authoring" / "ontology_migrations" / "applied" / "2026_10_initial_unification"


def test_every_legacy_business_concept_has_a_real_unified_target() -> None:
    result = validate_unification_plan(
        OntologyMigrationManifest.load(MIGRATION / "ontology_v2.yaml"),
        OntologyUnificationManifest.load(MIGRATION / "ontology_unification_v1.yaml"),
        OntologyBlueprint.load(MIGRATION / "teoria_business_ontology_v1.yaml"),
        [
            OntologyExtensionManifest.load(MIGRATION / "teoria_enterprise_context_v1.yaml"),
            OntologyExtensionManifest.load(MIGRATION / "teoria_legacy_concepts_v1.yaml"),
        ],
    )
    assert result == {
        "status": "valid",
        "legacy_business_concept_count": 23,
        "planned_concept_count": 23,
        "missing_legacy_concepts": [],
        "unknown_legacy_concepts": [],
        "missing_target_concepts": [],
    }
