from pathlib import Path

from teoria.ontology.migration import OntologyMigrationManifest
from teoria.ontology.promotion import BusinessConceptPromotion


ROOT = Path(__file__).parents[3]


def test_promotion_manifest_covers_every_planned_business_concept() -> None:
    migration = OntologyMigrationManifest.load(ROOT / "ontology_migrations" / "ontology_v2.yaml")
    promotion = BusinessConceptPromotion.load(ROOT / "ontology_migrations" / "business_concepts_v1.yaml")

    promoted = {
        ref
        for ref, item in migration.objects.items()
        if item.classification == "BUSINESS_CONCEPT"
        and item.target_stable_key
        and ref not in {
            "public_procurement.bid_notice",
            "public_procurement.procurement_supplier",
            "public_procurement.bid_award",
            "public_procurement.contract",
            "public_procurement.public_organization",
        }
    }

    assert promotion.legacy_refs == promoted
    assert len(promotion.legacy_refs) == 18
    assert {item.namespace for item in promotion.ontologies} == {"company", "procurement"}
