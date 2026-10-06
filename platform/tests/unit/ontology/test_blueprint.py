from pathlib import Path

from teoria.ontology.blueprint import OntologyBlueprint, apply_ontology_blueprint


ROOT = Path(__file__).parents[3]


def test_teoria_business_ontology_blueprint_has_shared_publication_boundary() -> None:
    blueprint = OntologyBlueprint.load(
        ROOT / "ontology_migrations" / "teoria_business_ontology_v1.yaml"
    )

    assert blueprint.namespace == "teoria"
    assert {item.stable_key for item in blueprint.objects} >= {
        "party.BusinessEntity",
        "party.BusinessRegistration",
        "procurement.BidNotice",
        "procurement.Contract",
        "procurement.ContractParty",
    }
    registration = next(item for item in blueprint.objects if item.code == "BusinessRegistration")
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
    def list_versions(self, namespace: str):
        return [{"version": "0.0.1", "status": "published"}]


def test_blueprint_does_not_clone_into_an_existing_ontology() -> None:
    blueprint = OntologyBlueprint.load(
        ROOT / "ontology_migrations" / "teoria_business_ontology_v1.yaml"
    )

    try:
        apply_ontology_blueprint(_ExistingOntologyRepository(), blueprint, actor="test")
    except ValueError as exc:
        assert "bootstrap cannot add a new version" in str(exc)
    else:
        raise AssertionError("existing ontology must reject blueprint bootstrap")
