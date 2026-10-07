from pathlib import Path
from uuid import uuid4

from teoria.ontology.enrichment import OntologyEnrichmentManifest, apply_ontology_enrichment


ROOT = Path(__file__).parents[3]


def test_enrichment_manifest_has_unique_concepts_and_valid_endpoints() -> None:
    manifest = OntologyEnrichmentManifest.load(
        ROOT / "ontology_migrations" / "applied" / "2026_10_initial_unification" / "business_ontology_enrichment_v1.yaml"
    )
    for ontology in manifest.ontologies:
        property_keys = [(item.object, item.code) for item in ontology.properties]
        relationship_codes = [item.code for item in ontology.relationships]
        assert len(property_keys) == len(set(property_keys))
        assert len(relationship_codes) == len(set(relationship_codes))

    assert sum(len(item.properties) for item in manifest.ontologies) == 23
    assert sum(len(item.relationships) for item in manifest.ontologies) == 14


class _AuthoringRepositoryStub:
    def __init__(self) -> None:
        self.version_id = uuid4()
        self.object_concept_id = uuid4()
        self.deleted: list[dict] = []
        self.added: list[dict] = []

    def list_versions(self, namespace):
        return [{"version": "0.1.3", "status": "published"}]

    def create_draft(self, namespace, *, version, actor):
        return {"ontology_version_id": str(self.version_id)}

    def get_version(self, version_id):
        return {
            "objects": [{
                "code": "BidNotice",
                "concept_id": str(self.object_concept_id),
                "stable_key": "procurement.BidNotice",
                "properties": [{
                    "code": "estimatedPrice",
                    "concept_id": str(uuid4()),
                    "stable_key": "teoria.BidNotice.estimatedPrice",
                }],
            }],
            "relationships": [],
        }

    def delete_item(self, version_id, **kwargs):
        self.deleted.append(kwargs)

    def add_item(self, version_id, **kwargs):
        self.added.append(kwargs)

    def validate(self, version_id):
        return {"status": "valid", "diagnostics": []}


def test_enrichment_replaces_incorrect_property_stable_key() -> None:
    manifest = OntologyEnrichmentManifest.model_validate({
        "schema_version": "1.0",
        "ontologies": [{
            "namespace": "teoria",
            "target_version": "0.1.4",
            "properties": [{
                "object": "BidNotice",
                "code": "estimatedPrice",
                "name": "추정가격",
                "stable_key": "procurement.BidNotice.estimatedPrice",
                "value_type": "decimal",
                "unit": "KRW",
            }],
        }],
    })
    repository = _AuthoringRepositoryStub()

    result = apply_ontology_enrichment(
        repository, manifest, actor="user:test", publish=False,
    )

    assert result["ontologies"][0]["status"] == "draft"
    assert repository.deleted[0]["kind"] == "property"
    assert repository.added[0]["payload"]["stable_key"] == (
        "procurement.BidNotice.estimatedPrice"
    )
