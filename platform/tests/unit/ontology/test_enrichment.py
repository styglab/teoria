from pathlib import Path

from teoria.ontology.enrichment import OntologyEnrichmentManifest


ROOT = Path(__file__).parents[3]


def test_enrichment_manifest_has_unique_concepts_and_valid_endpoints() -> None:
    manifest = OntologyEnrichmentManifest.load(
        ROOT / "ontology-migrations" / "business-ontology-enrichment-v1.yaml"
    )
    for ontology in manifest.ontologies:
        property_keys = [(item.object, item.code) for item in ontology.properties]
        relationship_codes = [item.code for item in ontology.relationships]
        assert len(property_keys) == len(set(property_keys))
        assert len(relationship_codes) == len(set(relationship_codes))

    assert sum(len(item.properties) for item in manifest.ontologies) == 23
    assert sum(len(item.relationships) for item in manifest.ontologies) == 14
