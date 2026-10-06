from pathlib import Path

from teoria.ontology.blueprint import OntologyBlueprint
from teoria.ontology.extension import OntologyExtensionManifest
from teoria.ontology.migration import OntologyMigrationManifest
from teoria.ontology.unification import OntologyUnificationManifest, validate_unification_plan


ROOT = Path(__file__).parents[3]


def test_every_legacy_business_concept_has_a_real_unified_target() -> None:
    result = validate_unification_plan(
        OntologyMigrationManifest.load(ROOT / "ontology-migrations/ontology-v2.yaml"),
        OntologyUnificationManifest.load(ROOT / "ontology-migrations/ontology-unification-v1.yaml"),
        OntologyBlueprint.load(ROOT / "ontology-migrations/teoria-business-ontology-v1.yaml"),
        [
            OntologyExtensionManifest.load(ROOT / "ontology-migrations/teoria-enterprise-context-v1.yaml"),
            OntologyExtensionManifest.load(ROOT / "ontology-migrations/teoria-legacy-concepts-v1.yaml"),
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
