from pathlib import Path
from uuid import UUID

from teoria.features.semantic_modeling.ontology.blueprint import OntologyBlueprint, apply_ontology_blueprint


ROOT = (Path(__file__).resolve().parents[5] / 'backend')


def test_specification_goods_model_separates_subjects_statements_and_evidence():
    blueprint = OntologyBlueprint.load(ROOT / "authoring/ontology_blueprints/goods.yaml")
    objects = {o.code: o for o in blueprint.objects}
    assert blueprint.namespace == "goods" and blueprint.target_version == "1.0.0"
    assert set(objects) == {
        "specification_document", "specified_item", "property_statement",
        "composition_statement", "requirement_statement", "evidence",
        "classification_scheme", "classification_entry", "classification_assignment",
        "item_type", "characteristic_definition", "specified_service",
        "supply_scope", "supply_membership", "specified_context",
        "specified_deliverable", "item_relation_statement",
    }
    item_properties = {p.code for p in objects["specified_item"].properties}
    assert not item_properties & {
        "memory_capacity", "capacity", "component_role", "classification_code",
        "item_type_concept_id",
    }
    assert {p.code for p in objects["property_statement"].properties} >= {
        "value_kind", "assertion_role", "semantic_scope", "qualifiers", "numeric_value", "unit_ref",
    }
    assert {p.code for p in objects["composition_statement"].properties} >= {
        "quantity_raw", "inclusion_role", "applicability_scope", "evidence_basis",
    }
    links = {r.code: (r.source, r.target) for r in blueprint.relationships}
    assert links["composition_parent"] == ("composition_statement", "specified_item")
    assert links["composition_child"] == ("composition_statement", "specified_item")
    assert links["property_subject"] == ("property_statement", "specified_item")
    assert links["evidence_document"] == ("evidence", "specification_document")
    for code in ["property_evidence", "composition_evidence", "requirement_evidence"]:
        assert links[code][1] == "evidence"
    assert links["item_has_type"] == ("specified_item", "item_type")
    assert links["statement_characteristic"] == ("property_statement", "characteristic_definition")
    assert links["classification_subject"] == ("classification_assignment", "specified_item")
    assert links["resolved_classification"] == ("classification_assignment", "classification_entry")
    assert links["service_subject"] == ("specified_service", "specified_item")
    assert links["membership_scope"] == ("supply_membership", "supply_scope")
    assert links["item_relation_target"] == ("item_relation_statement", "specified_item")
    assert links["requirement_context"] == ("requirement_statement", "specified_context")
    assert links["acceptance_verifies_property"] == ("requirement_statement", "property_statement")


def test_classification_and_composition_have_separate_identity_and_cardinality():
    blueprint = OntologyBlueprint.load(ROOT / "authoring/ontology_blueprints/goods.yaml")
    objects = {o.code: o for o in blueprint.objects}
    assert objects["classification_entry"].identity_properties == ["scheme_id", "edition", "code"]
    assert {p.code for p in objects["classification_assignment"].properties} >= {
        "raw_code", "raw_label", "source_kind", "resolution_status", "source_ref",
    }
    links = {r.code: r for r in blueprint.relationships}
    assert links["broader_classification"].source == "classification_entry"
    assert links["broader_classification"].target_cardinality == "optional"
    assert links["resolved_classification"].target_cardinality == "optional"
    # A grouped requirement for two GPUs needs one parent and one child item,
    # with quantity on the relationship; it must not imply two known assets.
    for endpoint in ["composition_parent", "composition_child"]:
        assert links[endpoint].target_cardinality == "one"
        assert not links[endpoint].transitive
    assert {p.code for p in objects["composition_statement"].properties} >= {
        "quantity_value", "quantity_unit", "quantity_operator", "inclusion_role", "applicability_scope",
    }


class _RecordingAuthoringService:
    """Exercise blueprint materialization without a database or publication."""

    def __init__(self):
        self.items = []
        self.object_ids = set()

    async def list_versions(self, namespace):
        return []

    async def create_ontology(self, **kwargs):
        return {"ontology_version_id": str(UUID(int=1))}

    async def add_item(self, version_id, *, kind, payload, actor):
        concept_id = str(UUID(int=len(self.items) + 2))
        if kind == "object":
            self.object_ids.add(concept_id)
        elif kind == "property":
            assert payload["object_concept_id"] in self.object_ids
        elif kind == "relationship":
            assert payload["source_object_concept_id"] in self.object_ids
            assert payload["target_object_concept_id"] in self.object_ids
        self.items.append((kind, payload))
        return {"concept_id": concept_id}

    async def validate(self, version_id):
        return {"status": "valid"}


async def test_goods_blueprint_materializes_dictionaries_and_links_without_publishing():
    blueprint = OntologyBlueprint.load(ROOT / "authoring/ontology_blueprints/goods.yaml")
    service = _RecordingAuthoringService()
    result = await apply_ontology_blueprint(service, blueprint, actor="test")
    assert result["status"] == "draft"
    assert len(service.items) == len(blueprint.objects) + len(blueprint.relationships) + sum(
        len(obj.properties) for obj in blueprint.objects
    )
    stable_keys = [payload["stable_key"] for _, payload in service.items]
    assert len(stable_keys) == len(set(stable_keys))
    assert not any(kind in {"publish", "approve"} for kind, _ in service.items)


def test_teoria_business_ontology_blueprint_has_shared_publication_boundary() -> None:
    blueprint = OntologyBlueprint.load(
        ROOT
        / "authoring" / "ontology_migrations"
        / "applied"
        / "2026_10_initial_unification"
        / "teoria_business_ontology_v1.yaml"
    )

    assert blueprint.namespace == "teoria"
    assert {item.stable_key for item in blueprint.objects} >= {
        "party.BusinessEntity",
        "party.BusinessRegistration",
        "procurement.BidNotice",
        "procurement.Contract",
        "procurement.ContractParty",
    }
    registration = next(
        item for item in blueprint.objects if item.code == "BusinessRegistration"
    )
    assert registration.identity_properties == ["businessRegistrationNumber"]
    assert any(
        item.source == "BusinessEntity"
        and item.target == "BusinessRegistration"
        and item.target_cardinality == "many"
        for item in blueprint.relationships
    )
    assert any(
        item.source == "ContractParty" and item.target == "BusinessRegistration"
        for item in blueprint.relationships
    )


class _ExistingOntologyRepository:
    async def list_versions(self, namespace: str):
        return [{"version": "0.0.1", "status": "published"}]


async def test_blueprint_does_not_clone_into_an_existing_ontology() -> None:
    blueprint = OntologyBlueprint.load(
        ROOT
        / "authoring" / "ontology_migrations"
        / "applied"
        / "2026_10_initial_unification"
        / "teoria_business_ontology_v1.yaml"
    )

    try:
        await apply_ontology_blueprint(
            _ExistingOntologyRepository(), blueprint, actor="test"
        )
    except ValueError as exc:
        assert "bootstrap cannot add a new version" in str(exc)
    else:
        raise AssertionError("existing ontology must reject blueprint bootstrap")
